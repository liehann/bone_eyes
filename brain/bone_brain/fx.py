"""The skull's voice treatment: pitch down, a little grit, a crypt-ish reverb."""
import numpy as np
from pedalboard import Chorus, Compressor, Limiter, Pedalboard, PitchShift, Reverb


class Fx:
    def __init__(self, rate: int, semitones: float, reverb: float):
        self.rate = rate
        self.board = Pedalboard([
            PitchShift(semitones=semitones),
            Chorus(rate_hz=0.6, depth=0.15, mix=0.2),
            Compressor(threshold_db=-20, ratio=3),
            Reverb(room_size=0.55, damping=0.6, wet_level=reverb, dry_level=0.85, width=0.6),
            Limiter(threshold_db=-1.0),
        ])

    def __call__(self, x: np.ndarray) -> np.ndarray:
        # Pad so the reverb tail isn't cut off at the end of each sentence.
        x = np.concatenate([x, np.zeros(int(self.rate * 0.25), dtype=np.float32)])
        return self.board(x[None, :], self.rate, reset=True)[0].astype(np.float32)
