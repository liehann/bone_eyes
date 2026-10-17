"""Microphone capture and speaker playback (sounddevice / CoreAudio).

The player carries a jaw level alongside the audio and reports it at the moment
that audio reaches the speaker (using the stream's DAC timestamps), minus a
small lead for the servo's lag.
"""
import collections
import queue
import threading
import time

import numpy as np
import sounddevice as sd

from .config import Config
from .jaw import BLOCK_S


def output_devices() -> list[str]:
    return [d["name"] for d in sd.query_devices() if d["max_output_channels"] > 0]


def input_devices() -> list[str]:
    return [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]


def default_name(kind: str) -> str:
    return sd.query_devices(kind=kind)["name"]


class Mic:
    BLOCK = 512  # 32 ms at 16 kHz: Silero VAD's frame size

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self.level_db = -90.0
        self.stream = sd.InputStream(samplerate=cfg.mic_rate, channels=1, dtype="float32",
                                     blocksize=self.BLOCK, device=cfg.mic_device,
                                     callback=self._cb)

    def _cb(self, indata, frames, t, status):
        x = indata[:, 0].copy()
        self.level_db = float(20 * np.log10(np.sqrt(np.mean(x * x)) + 1e-9))
        try:
            self.q.put_nowait(x)
        except queue.Full:
            pass

    def start(self):
        self.stream.start()

    def drain(self):
        while not self.q.empty():
            self.q.get_nowait()

    def read(self, timeout: float = 0.5) -> np.ndarray | None:
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None


class Player:
    def __init__(self, cfg: Config, on_jaw=None):
        self.cfg = cfg
        self.rate = cfg.out_rate
        self.on_jaw = on_jaw or (lambda level: None)
        self.lock = threading.Lock()
        self.chunks: collections.deque = collections.deque()  # (audio, jaw levels, pos)
        self.jaw_q: collections.deque = collections.deque()   # (dac_time, level)
        self.idle = threading.Event()
        self.idle.set()
        self.last_sound = 0.0  # time.monotonic() when audio last played
        self.started_at: float | None = None  # monotonic time of first audio this utterance
        self.stream = self._open(cfg.out_device)
        self._stop = False
        threading.Thread(target=self._jaw_loop, daemon=True).start()

    def _open(self, device):
        return sd.OutputStream(samplerate=self.rate, channels=1, dtype="float32",
                               blocksize=int(self.rate * BLOCK_S), device=device,
                               callback=self._cb, latency="low")

    def start(self):
        self.stream.start()

    def set_device(self, device):
        """Switch speakers live (device name, or None for the system default)."""
        self.flush()
        old = self.stream
        self.stream = self._open(device)
        self.jaw_q.clear()
        self.stream.start()
        old.stop()
        old.close()
        self.cfg.out_device = device

    @property
    def latency_s(self) -> float:
        return float(self.stream.latency)

    def play(self, audio: np.ndarray, jaw: np.ndarray):
        with self.lock:
            self.chunks.append([audio.astype(np.float32), jaw, 0])
            self.idle.clear()

    def flush(self):
        with self.lock:
            self.chunks.clear()
            self.idle.set()

    def busy(self) -> bool:
        return not self.idle.is_set()

    def _cb(self, out, frames, t, status):
        buf = out[:, 0]
        buf.fill(0)
        level = 0.0
        filled = 0
        with self.lock:
            while filled < frames and self.chunks:
                audio, jaw, pos = self.chunks[0]
                n = min(frames - filled, len(audio) - pos)
                buf[filled:filled + n] = audio[pos:pos + n]
                bi = min(int(pos / (self.rate * BLOCK_S)), len(jaw) - 1)
                level = max(level, float(jaw[bi]))
                pos += n
                filled += n
                if pos >= len(audio):
                    self.chunks.popleft()
                else:
                    self.chunks[0][2] = pos
            if filled:
                now = time.monotonic()
                self.last_sound = now
                if self.started_at is None:
                    self.started_at = now
            elif not self.chunks:
                self.idle.set()
        self.jaw_q.append((t.outputBufferDacTime, level))

    def _jaw_loop(self):
        """~50 Hz: forward jaw levels whose audio is about to be heard."""
        last = -1.0
        while not self._stop:
            now = self.stream.time + self.cfg.jaw_lead_ms / 1000
            level = None
            while self.jaw_q and self.jaw_q[0][0] <= now:
                level = self.jaw_q.popleft()[1]
            if level is not None and (abs(level - last) > 0.01 or (level == 0 and last != 0)):
                self.on_jaw(level)
                last = level
            time.sleep(0.02)
