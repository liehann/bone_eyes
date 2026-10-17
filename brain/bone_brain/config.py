"""Settings. Everything tunable lives here; the web page can change some live."""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"


@dataclass
class Config:
    # Audio
    mic_rate: int = 16000          # Silero VAD + Whisper want 16 kHz
    out_rate: int = 24000          # Kokoro's native rate; everything else is resampled
    mic_device: str | int | None = None   # None = system default
    out_device: str | int | None = None

    # Listening
    vad_threshold: float = 0.5
    listen_start_timeout_s: float = 8.0   # nobody talking this long -> tease them once
    end_silence_s: float = 0.6            # this much quiet ends the question
    max_question_s: float = 10.0
    echo_guard_s: float = 0.35            # ignore the mic this long after the skull stops talking

    # Conversation
    max_turns: int = 12                   # safety cap per visit; goodbye normally comes from presence clearing
    thinking_filler: bool = True          # "Hmmm..." as soon as a question arrives
    whisper_model: str = "mlx-community/whisper-small.en-mlx"
    llm_model: str = "claude-haiku-5-5"
    llm_max_tokens: int = 80   # ~2 short sentences; a hard stop if it rambles

    # Voice
    tts: str = "kokoro"                   # kokoro | piper | say | elevenlabs
    kokoro_voice: str = "bm_fable"
    kokoro_speed: float = 0.92
    piper_voice: str = "en_GB-alan-medium"
    say_voice: str = "Daniel"
    elevenlabs_voice_id: str = os.environ.get("ELEVENLABS_VOICE_ID", "")
    elevenlabs_model: str = "eleven_flash_v2_5"
    fx: bool = True
    fx_semitones: float = -6.0
    fx_reverb: float = 0.25

    # Jaw: RMS (dBFS) -> 0..1, same shape as tools/make_envelopes.py
    jaw_top_db: float = -12.0
    jaw_range_db: float = 18.0
    jaw_gamma: float = 1.4
    jaw_attack_ms: float = 20.0
    jaw_release_ms: float = 50.0
    jaw_lead_ms: float = 60.0             # send jaw early: the servo lags the command

    # Skull link: "" = none, a serial port path, or "udp://host:port"
    skull: str = os.environ.get("SKULL_PORT", "")

    web_port: int = 8031
    keep_recordings: bool = False         # visitors' audio is not stored unless enabled

    extra: dict = field(default_factory=dict)


cfg = Config()
