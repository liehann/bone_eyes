"""The conversation loop: greet, listen, think, speak, repeat, say goodbye."""
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .audio import Mic, Player
from .config import Config
from .fx import Fx
from .jaw import JawFollower
from .lines import Lines
from .llm import Llm, split_sentences
from .personas import PERSONAS, SKELETON, Persona, Possession
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
        self.fx_cache: dict[tuple, Fx] = {}
        self.jaw = JawFollower(cfg, cfg.out_rate)
        self.skull = Skull(cfg.skull, on_event=self._skull_event)
        self.player = Player(cfg, on_jaw=self._on_jaw)
        self.mic = Mic(cfg)
        self.vad = Vad()
        self.stt = Stt(cfg.whisper_model)
        self.tts_pool = ThreadPoolExecutor(1, thread_name_prefix="tts")
        self.work_pool = ThreadPoolExecutor(2, thread_name_prefix="work")
        self.fillers: dict[str, list] = {}   # persona -> pre-rendered "hmmm" lines
        self.filler_key: dict[str, tuple] = {}
        self.possession = Possession()
        self.persona: Persona = PERSONAS[SKELETON]
        self.state = "starting"
        self.session: asyncio.Task | None = None
        self.present = False
        self.gone = threading.Event()
        self.typed_q: list[str] = []

    # ---- lifecycle -------------------------------------------------------
    async def start(self):
        self.loop = asyncio.get_running_loop()
        self.set_state("warming up")
        await self.loop.run_in_executor(self.work_pool, self.stt.warmup)
        if PERSONAS[SKELETON].engine != "elevenlabs":  # don't spend an API call on a warm-up
            await self.loop.run_in_executor(self.tts_pool, self.tts.synth, "Ready.", PERSONAS[SKELETON])
        self.skull.art()  # drop any override left from an earlier run
        self.player.start()
        self.mic.start()
        await self._refill_fillers(SKELETON)
        self.set_state("idle")
        asyncio.ensure_future(self._prerender_personas())

    def set_state(self, state: str, **extra):
        self.state = state
        self.skull.mood({"idle": "idle", "greeting": "alert", "listening": "alert",
                         "thinking": "alert", "speaking": "talking", "goodbye": "goodbye"}.get(state, "idle"))
        self.emit({"type": "state", "state": state, **extra})

    def log(self, who: str, text: str, **extra):
        print(f"{who:>8}: {text}", flush=True)
        self.emit({"type": "line", "who": who, "text": text, **extra})

    def _on_jaw(self, level: float):
        self.skull.jaw(level)
        if self.loop:
            self.loop.call_soon_threadsafe(self.emit, {"type": "jaw", "v": round(level, 3)})

    def _skull_event(self, kind: str, value: int):
        if not self.loop:
            return
        if kind == "present":
            self.loop.call_soon_threadsafe(self.emit, {"type": "radar", "cm": value})
            if not self.present:
                self.loop.call_soon_threadsafe(self.visitor)
        else:
            self.loop.call_soon_threadsafe(self.emit, {"type": "radar", "cm": None})
            self.loop.call_soon_threadsafe(self.leave)

    # ---- commands --------------------------------------------------------
    def visitor(self, typed_questions: list[str] | None = None):
        """Someone arrived (radar or the page). Typed questions join a visit in progress."""
        self.present = True
        self.gone.clear()
        self.emit({"type": "presence", "present": True})
        if self.session and not self.session.done():
            if typed_questions:
                self.typed_q.extend(typed_questions)  # the listener picks these up
            return False
        self.typed_q = list(typed_questions or [])
        self.session = asyncio.ensure_future(self._session(self.typed_q))
        return True

    def leave(self):
        """Presence cleared: finish the current sentence/reply, then say goodbye."""
        self.present = False
        self.gone.set()
        self.emit({"type": "presence", "present": False})

    def stop(self):
        """Hard stop, no goodbye."""
        self.present = False
        self.gone.set()
        if self.session and not self.session.done():
            self.session.cancel()
        self.player.flush()
        self.set_state("idle")

    async def say(self, text: str, who: str = "skull"):
        """Speak a fixed line (greeting, test text, ...) in the current persona's voice."""
        self.log(who, text, persona=self.persona.id)
        q: asyncio.Queue = asyncio.Queue()
        for s in split_sentences(text):
            q.put_nowait(s)
        q.put_nowait(None)
        await self._speak_queue(q, time.monotonic())
        await self._wait_quiet()

    def busy(self) -> bool:
        return bool(self.session and not self.session.done())

    async def preview(self, pid: str, text: str):
        """Speak a line in any persona's voice (voice editor), outside a visit."""
        persona = PERSONAS[pid]
        audio = await self.loop.run_in_executor(self.tts_pool, self._render, text, persona)
        self.log("test", text, persona=pid)
        self.player.started_at = None
        self.player.play(*audio)
        await self._wait_quiet()

    # ---- session ---------------------------------------------------------
    async def _session(self, typed: list[str] | None):
        """One visit: greet, then answer questions for as long as someone is there.
        The goodbye comes only when presence clears (radar, or the page's Leave button)."""
        typed = self.typed_q
        try:
            self.set_state("greeting")
            await self.say(self.lines.pick("greet", self.persona.id))
            history: list[dict] = []
            prompted_silence = False
            turns = 0
            while self.present and turns < self.cfg.max_turns:
                timings: dict[str, float] = {}
                if typed:
                    question = typed.pop(0)
                    t_eos = time.monotonic()
                    self.log("visitor", question, typed=True)
                else:
                    self.set_state("listening")
                    audio, t_eos = await self.loop.run_in_executor(self.work_pool, self._listen)
                    if not self.present:
                        break
                    if audio is None:
                        # Nobody's talking. Tease them once, then wait quietly until
                        # they speak or leave.
                        if not prompted_silence:
                            prompted_silence = True
                            await self.say(self.lines.pick("silence", self.persona.id))
                        continue
                    self.set_state("thinking")
                    question = await self.loop.run_in_executor(self.work_pool, self.stt.transcribe, audio)
                    timings["stt"] = time.monotonic() - t_eos
                    if not question:
                        self.log("visitor", "(unintelligible)")
                        await self.say(self.lines.pick("unheard", self.persona.id))
                        continue
                    self.log("visitor", question)
                prompted_silence = False
                turns += 1
                self.set_state("thinking")
                history.append({"role": "user", "content": question})
                reply = await self._answer(history, t_eos, timings)
                history.append({"role": "assistant", "content": reply or "..."})
                self.emit({"type": "timings", **{k: round(v * 1000) for k, v in timings.items()}})
            await self._wait_quiet()
            self.set_state("goodbye")
            await self.say(self.lines.pick("goodbye", self.persona.id))
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
            self.possession.end_visit()
            self._set_persona(PERSONAS[SKELETON])
            self.present = False
            self.emit({"type": "presence", "present": False})
            self.set_state("idle")

    def _set_persona(self, persona: Persona):
        if persona.id != self.persona.id:
            self.persona = persona
            # The skeleton is the skull itself: show its saved eye style (set on
            # its web page); possessing spirits override it until they leave.
            self.skull.art(None if persona.id == SKELETON else persona.eyes)
            self.emit({"type": "persona", "id": persona.id, "name": persona.name, "eyes": persona.eyes})

    def _voice_key(self, pid: str):
        return (pid,) + PERSONAS[pid].voice_key()

    async def _refill_fillers(self, pid: str | None = None, n: int | None = None):
        """Render a few thinking fillers ahead of time so they play instantly."""
        pid = pid or SKELETON
        n = n or (8 if pid == SKELETON else 2)
        key = self._voice_key(pid)
        if key != self.filler_key.get(pid):
            self.fillers[pid], self.filler_key[pid] = [], key
        persona = PERSONAS[pid]
        while len(self.fillers[pid]) < n:
            text = self.lines.pick("thinking", pid)
            audio = await self.loop.run_in_executor(self.tts_pool, self._render, text, persona)
            if self._voice_key(pid) != key:
                return
            self.fillers[pid].append((text, audio))

    async def _prerender_personas(self):
        for pid in PERSONAS:
            if pid != SKELETON:
                await self._refill_fillers(pid)

    def _play_now(self, text: str, audio, **extra):
        self.log("skull", text, persona=self.persona.id, **extra)
        if not self.player.busy():
            self.player.started_at = None
        self.player.play(*audio)
        self.set_state("speaking")

    async def _lead_in(self, event: str | None):
        """What the skull says the instant a question arrives: a thinking filler,
        or the possessing spirit's intro, or the skeleton grumbling it's back."""
        pid = self.persona.id
        if event in ("possessed", "released"):
            text = self.lines.pick("intro", pid) if event == "possessed" else self.lines.pick("unpossessed")
            audio = await self.loop.run_in_executor(self.tts_pool, self._render, text, self.persona)
            self._play_now(text, audio, event=event)
            return True
        if not self.cfg.thinking_filler:
            return False
        if self._voice_key(pid) != self.filler_key.get(pid) or not self.fillers.get(pid):
            return False
        text, audio = self.fillers[pid].pop(0)
        self._play_now(text, audio, filler=True)
        return True

    async def _answer(self, history: list[dict], t_eos: float, timings: dict) -> str:
        q: asyncio.Queue = asyncio.Queue()
        sentences: list[str] = []
        persona, event = self.possession.before_reply()
        self._set_persona(persona)
        if await self._lead_in(event):
            timings["filler"] = time.monotonic() - t_eos

        async def produce():
            try:
                async for s in self.llm.reply(history, self.llm_backend, persona):
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
        self.log("skull", reply, backend=self.llm_backend, persona=persona.id)
        await self._wait_quiet()
        asyncio.ensure_future(self._refill_fillers(persona.id))
        return reply

    async def _speak_queue(self, q: asyncio.Queue, t0: float, timings: dict | None = None):
        """Synthesize sentences as they arrive and queue them on the speaker."""
        persona = self.persona
        if not self.player.busy():
            self.player.started_at = None
            self.jaw.reset()
        first = True
        while (s := await q.get()) is not None:
            audio = await self.loop.run_in_executor(self.tts_pool, self._render, s, persona)
            if first:
                self.set_state("speaking")
                if timings is not None:
                    timings["first_audio"] = time.monotonic() - t0  # answer queued (after any filler)
                first = False
            self.player.play(*audio)

    def _fx(self, persona: Persona) -> Fx:
        key = (persona.semitones, persona.reverb, persona.chorus)
        if key not in self.fx_cache:
            self.fx_cache[key] = Fx(self.cfg.out_rate, *key)
        return self.fx_cache[key]

    def _render(self, sentence: str, persona: Persona | None = None):
        persona = persona or PERSONAS[SKELETON]
        dry = self.tts.synth(sentence, persona)
        tail = np.zeros(int(self.cfg.out_rate * 0.25), dtype=np.float32)
        jaw = self.jaw.levels(np.concatenate([dry, tail]))  # jaw follows the dry voice
        wet = self._fx(persona)(dry) if persona.effects else np.concatenate([dry, tail])
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
            if self.gone.is_set() or (not started and self.typed_q):
                return None, time.monotonic()
            f = self.mic.read(timeout=0.1)
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
