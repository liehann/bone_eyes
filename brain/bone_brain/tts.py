"""Swappable text-to-speech. Each backend turns one sentence into mono float32
audio at the player's rate."""
import hashlib
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf
from pedalboard.io import StreamResampler

from .config import CACHE_TTS, MODELS, Config
from .llm import split_sentences

FALLBACK_VOICE = "bm_george"  # local British voice when ElevenLabs can't render a line


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x.astype(np.float32)
    r = StreamResampler(src, dst, 1)
    y = np.concatenate([r.process(x.astype(np.float32)[None, :])[0], r.process(None)[0]])
    return y.astype(np.float32)


class Kokoro:
    name = "kokoro"

    def __init__(self, cfg: Config):
        from kokoro_onnx import Kokoro as K
        self.cfg = cfg
        self.k = K(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin"))

    def voices(self) -> list[str]:
        return sorted(self.k.get_voices())

    def synth(self, text: str, voice: str, speed: float, model: str) -> tuple[np.ndarray, int]:
        lang = "en-gb" if voice.startswith("b") else "en-us"
        return self.k.create(text, voice=voice, speed=speed, lang=lang)


class Piper:
    name = "piper"

    def __init__(self, cfg: Config):
        from piper import PiperVoice
        self.cfg = cfg
        self._PiperVoice = PiperVoice
        self.loaded: dict[str, object] = {}

    def voices(self) -> list[str]:
        return sorted(p.stem for p in MODELS.glob("*.onnx") if Path(str(p) + ".json").exists())

    def synth(self, text: str, voice: str, speed: float, model: str) -> tuple[np.ndarray, int]:
        from piper import SynthesisConfig
        if voice not in self.loaded:
            self.loaded[voice] = self._PiperVoice.load(str(MODELS / f"{voice}.onnx"))
        chunks = list(self.loaded[voice].synthesize(text, SynthesisConfig(length_scale=1 / max(speed, 0.3))))
        return np.concatenate([c.audio_float_array for c in chunks]), chunks[0].sample_rate


class Say:
    """macOS built-in voices. Zero setup; good for a quick comparison."""
    name = "say"

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def voices(self) -> list[str]:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
        return sorted({l.split()[0] for l in out.splitlines() if "en_" in l})

    def synth(self, text: str, voice: str, speed: float, model: str) -> tuple[np.ndarray, int]:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "say.wav"
            subprocess.run(["say", "-v", voice, "-r", str(int(175 * speed)), "-o", str(p), "--file-format=WAVE",
                            "--data-format=LEF32@22050", text], check=True)
            audio, sr = sf.read(p, dtype="float32")
        return audio, sr


def cache_file(voice: str, model: str, text: str) -> Path:
    """On-disk clip for one ElevenLabs line: keyed on voice + model + text."""
    h = hashlib.sha256(f"{voice}\n{model or 'eleven_flash_v2_5'}\n{text}".encode()).hexdigest()[:24]
    return CACHE_TTS / f"{h}.wav"


class ElevenLabs:
    name = "elevenlabs"

    def __init__(self, cfg: Config, api_key: str | None):
        self.cfg = cfg
        self.key = api_key

    def voices(self) -> list[str]:
        return []  # free-form voice id

    def synth(self, text: str, voice: str, speed: float, model: str) -> tuple[np.ndarray, int]:
        f = cache_file(voice, model, text)
        if f.exists():  # pre-rendered (brain/tools/prerender.py): no network, no API call
            audio, sr = sf.read(f, dtype="float32")
            return audio, sr
        if not self.key or not voice:
            raise RuntimeError("ElevenLabs needs ELEVENLABS_API_KEY and a voice id")
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream?output_format=pcm_24000",
            data=json.dumps({"text": text, "model_id": model or "eleven_flash_v2_5"}).encode(),
            headers={"xi-api-key": self.key, "Content-Type": "application/json"})
        pcm = urllib.request.urlopen(req, timeout=20).read()
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        try:  # keep every live result so the same line is free next time
            f.parent.mkdir(parents=True, exist_ok=True)
            sf.write(f, audio, 24000, subtype="PCM_16")
        except OSError as e:
            print(f"tts: cache write failed: {e}")
        return audio, 24000


class Tts:
    def __init__(self, cfg: Config, elevenlabs_key: str | None = None):
        self.cfg = cfg
        self.backends = {"say": Say(cfg), "elevenlabs": ElevenLabs(cfg, elevenlabs_key)}
        for cls in (Kokoro, Piper):
            try:
                self.backends[cls.name] = cls(cfg)
            except Exception as e:
                print(f"tts: {cls.name} unavailable: {e}")

    def _eleven(self, b, text: str, persona) -> tuple[np.ndarray, int]:
        """ElevenLabs clips are cached per sentence, so render a multi-sentence line
        sentence by sentence. A miss that can't be rendered (no key, no network)
        falls back to a local British Kokoro voice instead of failing."""
        parts = []
        for s in split_sentences(text) or [text]:
            try:
                audio, sr = b.synth(s, persona.voice, persona.speed, persona.model)
            except Exception as e:
                k = self.backends.get("kokoro")
                if k is None:
                    raise
                print(f"tts: WARNING ElevenLabs unavailable for {s!r} ({e}); using Kokoro {FALLBACK_VOICE}")
                audio, sr = k.synth(s, FALLBACK_VOICE, 1.0, "")
            parts.append(resample(np.asarray(audio, dtype=np.float32), sr, 24000))
            parts.append(np.zeros(int(24000 * 0.12), dtype=np.float32))
        return np.concatenate(parts[:-1]), 24000

    def synth(self, text: str, persona) -> np.ndarray:
        """Sentence in a persona's voice -> float32 at cfg.out_rate, peak-normalised so
        the jaw scale is consistent."""
        b = self.backends.get(persona.engine)
        if b is None:
            raise RuntimeError(f"TTS engine {persona.engine!r} unavailable")
        if persona.engine == "elevenlabs":
            audio, sr = self._eleven(b, text, persona)
        else:
            audio, sr = b.synth(text, persona.voice, persona.speed, persona.model)
        audio = resample(np.asarray(audio, dtype=np.float32), sr, self.cfg.out_rate)
        peak = float(np.max(np.abs(audio))) if len(audio) else 0
        return audio * (0.7 / peak) if peak > 1e-4 else audio
