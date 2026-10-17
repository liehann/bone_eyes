"""The conversation loop: greet, listen, think, speak, repeat, say goodbye."""
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .audio import Mic, Player
from .config import Config
from .fx import Fx
from .jaw import JawFollower
from .lines import Lines
from .llm import Llm, split_sentences
from .skull import Skull
from .stt import Stt
from .tts import Tts
from .vad import Vad


class Brain:
    def __init__(self, cfg: Config, keys: dict[str, str], emit):
        self.cfg = cfg
        self.emit = emit  # emit(dict) -> broadcast to the web page
        self.loop: asyncio.AbstractEventLoop | None = None
        self.lines = Lines()
        self.llm = Llm(cfg.llm_model, cfg.llm_max_tokens, self.lines, keys.get("ANTHROPIC_API_KEY"))
        self.llm_backend = "claude" if self.llm.available else "canned"
        self.tts = Tts(cfg, keys.get("ELEVENLABS_API_KEY"))
        self.fx = Fx(cfg.out_rate, cfg.fx_semitones, cfg.fx_reverb)
        self.jaw = JawFollower(cfg, cfg.out_rate)
        self.skull = Skull(cfg.skull, on_event=self._skull_event)
        self.player = Player(cfg, on_jaw=self._on_jaw)
        self.mic = Mic(cfg)
        self.vad = Vad()
        self.stt = Stt(cfg.whisper_model)
        self.tts_pool = ThreadPoolExecutor(1, thread_name_prefix="tts")
        self.work_pool = ThreadPoolExecutor(2, thread_name_prefix="work")
        self.state = "starting"
        self.session: asyncio.Task | None = None
        self.present = False

    # ---- lifecycle -------------------------------------------------------
    async def start(self):
        self.loop = asyncio.get_running_loop()
        self.set_state("warming up")
        await self.loop.run_in_executor(self.work_pool, self.stt.warmup)
        await self.loop.run_in_executor(self.tts_pool, self.tts.synth, "Ready.")
        self.player.start()
        self.mic.start()
        self.set_state("idle")

    def set_state(self, state: str, **extra):
        self.state = state
        self.skull.mood({"idle": "idle", "greeting": "alert", "listening": "alert",
                         "thinking": "alert", "speaking": "talking", "goodbye": "goodbye"}.get(state, "idle"))
        self.emit({"type": "state", "state": state, **extra})

    def log(self, who: str, text: str, **extra):
        self.emit({"type": "line", "who": who, "text": text, **extra})

    def _on_jaw(self, level: float):
        self.skull.jaw(level)
        if self.loop:
            self.loop.call_soon_threadsafe(self.emit, {"type": "jaw", "v": round(level, 3)})

    def _skull_event(self, kind: str, value: int):
        if not self.loop:
            return
        if kind == "present":
            self.present = True
            self.loop.call_soon_threadsafe(self.emit, {"type": "radar", "cm": value})
            self.loop.call_soon_threadsafe(self.visitor)
        else:
            self.present = False
            self.loop.call_soon_threadsafe(self.emit, {"type": "radar", "cm": None})

    # ---- commands --------------------------------------------------------
    def visitor(self, typed_questions: list[str] | None = None):
        if self.session and not self.session.done():
            return False
        self.session = asyncio.ensure_future(self._session(typed_questions))
        return True

    def stop(self):
        if self.session and not self.session.done():
            self.session.cancel()
        self.player.flush()
        self.set_state("idle")

    async def say(self, text: str, who: str = "skull"):
        """Speak a fixed line (greeting, test text, ...)."""
        self.log(who, text)
        q: asyncio.Queue = asyncio.Queue()
        for s in split_sentences(text):
            q.put_nowait(s)
        q.put_nowait(None)
        await self._speak_queue(q, time.monotonic())
        await self._wait_quiet()

    # ---- session ---------------------------------------------------------
    async def _session(self, typed: list[str] | None):
        try:
            self.set_state("greeting")
            await self.say(self.lines.pick("greet"))
            history: list[dict] = []
            for turn in range(self.cfg.max_turns):
                timings: dict[str, float] = {}
                if typed is not None:
                    if turn >= len(typed):
                        break
                    question = typed[turn]
                    t_eos = time.monotonic()
                    self.log("visitor", question, typed=True)
                else:
                    self.set_state("listening")
                    audio, t_eos = await self.loop.run_in_executor(self.work_pool, self._listen)
                    if audio is None:
                        await self.say(self.lines.pick("silence"))
                        break
                    self.set_state("thinking")
                    question = await self.loop.run_in_executor(self.work_pool, self.stt.transcribe, audio)
                    timings["stt"] = time.monotonic() - t_eos
                    if not question:
                        self.log("visitor", "(unintelligible)")
                        await self.say(self.lines.pick("unheard"))
                        continue
                    self.log("visitor", question)
                self.set_state("thinking")
                history.append({"role": "user", "content": question})
                reply = await self._answer(history, t_eos, timings)
                history.append({"role": "assistant", "content": reply or "..."})
                self.emit({"type": "timings", **{k: round(v * 1000) for k, v in timings.items()}})
            self.set_state("goodbye")
            await self.say(self.lines.pick("goodbye"))
        except asyncio.CancelledError:
            self.player.flush()
            raise
        except Exception as e:
            self.log("error", f"{type(e).__name__}: {e}")
            self.player.flush()
            try:
                await self.say(self.lines.pick("offline"))
            except Exception:
                pass
        finally:
            self.set_state("idle")

    async def _answer(self, history: list[dict], t_eos: float, timings: dict) -> str:
        q: asyncio.Queue = asyncio.Queue()
        sentences: list[str] = []

        async def produce():
            try:
                async for s in self.llm.reply(history, self.llm_backend):
                    if not sentences:
                        timings["first_sentence"] = time.monotonic() - t_eos
                    sentences.append(s)
                    q.put_nowait(s)
            finally:
                q.put_nowait(None)

        speak = asyncio.ensure_future(self._speak_queue(q, t_eos, timings))
        try:
            await produce()
        except Exception as e:
            self.log("error", f"LLM: {type(e).__name__}: {e}")
            if not sentences:
                speak.cancel()
                await self.say(self.lines.pick("offline"))
                return ""
        await speak
        reply = " ".join(sentences)
        self.log("skull", reply, backend=self.llm_backend)
        await self._wait_quiet()
        return reply

    async def _speak_queue(self, q: asyncio.Queue, t0: float, timings: dict | None = None):
        """Synthesize sentences as they arrive and queue them on the speaker."""
        self.player.started_at = None
        self.jaw.reset()
        first = True
        while (s := await q.get()) is not None:
            audio = await self.loop.run_in_executor(self.tts_pool, self._render, s)
            if first:
                self.set_state("speaking")
                if timings is not None:
                    timings["first_audio"] = time.monotonic() - t0
                first = False
            self.player.play(*audio)

    def _render(self, sentence: str):
        dry = self.tts.synth(sentence)
        tail = np.zeros(int(self.cfg.out_rate * 0.25), dtype=np.float32)
        jaw = self.jaw.levels(np.concatenate([dry, tail]))  # jaw follows the dry voice
        wet = self.fx(dry) if self.cfg.fx else np.concatenate([dry, tail])
        return wet, jaw

    async def _wait_quiet(self):
        while self.player.busy():
            await asyncio.sleep(0.03)

    # ---- listening (worker thread) ---------------------------------------
    def _listen(self):
        """Record one question. Returns (audio, end-of-speech time) or (None, now)."""
        c = self.cfg
        while time.monotonic() - self.player.last_sound < c.echo_guard_s:
            time.sleep(0.02)
        self.mic.drain()
        self.vad.reset()
        frame_s = Mic.BLOCK / c.mic_rate
        preroll: list[np.ndarray] = []
        frames: list[np.ndarray] = []
        started = False
        voiced_run = 0
        silence = 0.0
        t_start = time.monotonic()
        last_emit = 0.0
        while True:
            f = self.mic.read()
            if f is None:
                continue
            p = self.vad.prob(f)
            now = time.monotonic()
            if now - last_emit > 0.1:
                last_emit = now
                self.loop.call_soon_threadsafe(self.emit, {"type": "mic", "db": round(self.mic.level_db, 1),
                                                          "speech": round(p, 2)})
            if not started:
                preroll = (preroll + [f])[-10:]  # keep ~0.3 s before speech starts
                voiced_run = voiced_run + 1 if p > c.vad_threshold else 0
                if voiced_run >= 2:
                    started = True
                    frames = preroll[:]
                elif now - t_start > c.listen_start_timeout_s:
                    return None, now
                continue
            frames.append(f)
            silence = silence + frame_s if p < c.vad_threshold - 0.15 else 0.0
            if silence >= c.end_silence_s or len(frames) * frame_s >= c.max_question_s:
                return np.concatenate(frames), now
