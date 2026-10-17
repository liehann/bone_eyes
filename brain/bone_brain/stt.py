"""Speech-to-text with Whisper on the Mac's GPU (mlx-whisper)."""
import numpy as np


class Stt:
    def __init__(self, model: str):
        import mlx_whisper
        self._mw = mlx_whisper
        self.model = model

    def warmup(self):
        self.transcribe(np.zeros(16000, dtype=np.float32))

    def transcribe(self, audio16k: np.ndarray) -> str:
        r = self._mw.transcribe(audio16k.astype(np.float32), path_or_hf_repo=self.model,
                                language="en", temperature=0.0,
                                condition_on_previous_text=False)
        text = r["text"].strip()
        # Whisper hallucinates these on noise / silence.
        if text.lower().strip(" .!?") in {"", "you", "thank you", "thanks for watching", "bye"}:
            return ""
        return text
