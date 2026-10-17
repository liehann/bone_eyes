"""Speech loudness -> jaw opening (0..1), the live twin of tools/make_envelopes.py.

Levels are computed from the dry voice (before reverb) in fixed blocks, so the
jaw stops when the words stop, not when the echo does.
"""
import numpy as np

from .config import Config

BLOCK_S = 0.02  # one jaw value per 20 ms of audio


class JawFollower:
    def __init__(self, cfg: Config, rate: int):
        self.cfg = cfg
        self.rate = rate
        self.block = int(rate * BLOCK_S)
        self.level = 0.0
        self.a_att = 1 - np.exp(-BLOCK_S / (cfg.jaw_attack_ms / 1000))
        self.a_rel = 1 - np.exp(-BLOCK_S / (cfg.jaw_release_ms / 1000))

    def reset(self):
        self.level = 0.0

    def levels(self, x: np.ndarray) -> np.ndarray:
        """One smoothed level per block of x (the last partial block counts)."""
        c = self.cfg
        n = max(1, int(np.ceil(len(x) / self.block)))
        pad = np.zeros(n * self.block, dtype=np.float32)
        pad[: len(x)] = x
        rms = np.sqrt(np.mean(pad.reshape(n, self.block) ** 2, axis=1) + 1e-12)
        db = 20 * np.log10(rms)
        raw = np.clip((db - (c.jaw_top_db - c.jaw_range_db)) / c.jaw_range_db, 0, 1) ** c.jaw_gamma
        out = np.empty(n, dtype=np.float32)
        lvl = self.level
        for i, target in enumerate(raw):
            lvl += (target - lvl) * (self.a_att if target > lvl else self.a_rel)
            out[i] = lvl
        self.level = lvl
        return out
