"""Silero VAD (v5, ONNX): speech probability per 512-sample frame at 16 kHz."""
import numpy as np
import onnxruntime as ort

from .config import MODELS


class Vad:
    def __init__(self):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(str(MODELS / "silero_vad.onnx"), opts,
                                         providers=["CPUExecutionProvider"])
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros(64, dtype=np.float32)

    def prob(self, frame: np.ndarray) -> float:
        x = np.concatenate([self.context, frame.astype(np.float32)])[None, :]
        out, self.state = self.sess.run(None, {"input": x, "state": self.state,
                                               "sr": np.array(16000, dtype=np.int64)})
        self.context = frame[-64:].astype(np.float32)
        return float(out[0][0])
