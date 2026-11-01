#!/usr/bin/env python3
"""Bake the wizard's cached ElevenLabs lines into clips for standalone mode.

    brain/.venv/bin/python tools/make_standalone_clips.py [--persona wizard] [--budget-kb 4600]

Reads only the brain's on-disk TTS cache (brain/cache/tts/, no API call). Each
whole line (greet, reply, silence; reply first) is joined from its cached
sentences exactly as the brain does, run through the persona's playback
effects (bone_brain.fx) and the brain's jaw follower (bone_brain.jaw, levels
from the dry voice), then written to data/clips/NNN.clp until the budget is
used. Lines with any uncached sentence are skipped.

.clp layout (little endian):
  0   char[4]  "BCLP"
  4   u8       version 1
  5   u8       format 1 = IMA ADPCM, 4 bit, one continuous stream, low nibble first
  6   u16      sample rate (16000)
  8   u32      sample count
  12  u16      jaw frames per second (50)
  14  u16      jaw frame count N
  16  u16[N]   jaw opening 0..1000
  ..  u8[]     ADPCM (predictor 0, step index 0 at the start)
data/clips/index.txt lists NNN, kind and text (for the console `clips` list).
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
BRAIN = Path("/Users/liehann/Projects/bone_eyes/main/brain")
if not (BRAIN / "bone_brain").exists():
    BRAIN = ROOT / "brain"
sys.path.insert(0, str(BRAIN))

from bone_brain.config import Config  # noqa: E402
from bone_brain.fx import Fx  # noqa: E402
from bone_brain.jaw import JawFollower  # noqa: E402
from bone_brain.lines import DIR  # noqa: E402
from bone_brain.llm import split_sentences  # noqa: E402
from bone_brain.personas import PERSONAS  # noqa: E402
import bone_brain.tts as tts  # noqa: E402

RATE = 16000
JAW_HZ = 50

STEPS = [7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80,
         88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598,
         658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327,
         3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289,
         16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767]
IDX = [-1, -1, -1, -1, 2, 4, 6, 8]


def adpcm_encode(pcm: np.ndarray) -> bytes:
    pred, idx = 0, 0
    out = bytearray((len(pcm) + 1) // 2)
    for i, s in enumerate(pcm.tolist()):
        step = STEPS[idx]
        d = s - pred
        code = 0
        if d < 0:
            code, d = 8, -d
        diff = step >> 3
        if d >= step:
            code |= 4; d -= step; diff += step
        step >>= 1
        if d >= step:
            code |= 2; d -= step; diff += step
        step >>= 1
        if d >= step:
            code |= 1; diff += step
        pred = pred - diff if code & 8 else pred + diff
        pred = -32768 if pred < -32768 else 32767 if pred > 32767 else pred
        idx = min(88, max(0, idx + IDX[code & 7]))
        out[i >> 1] |= code << (4 * (i & 1))
    return bytes(out)


def line_audio(text: str, p) -> np.ndarray | None:
    """The brain's Tts._eleven + synth for one line, from the cache only."""
    parts = []
    for s in split_sentences(text) or [text]:
        f = tts.cache_file(p.voice, p.model, s)
        if not f.exists():
            return None
        import soundfile as sf
        a, sr = sf.read(f, dtype="float32")
        if a.ndim > 1:
            a = a.mean(axis=1)
        parts.append(tts.resample(a, sr, 24000))
        parts.append(np.zeros(int(24000 * 0.12), dtype=np.float32))
    a = np.concatenate(parts[:-1])
    peak = float(np.max(np.abs(a)))
    return a * (0.7 / peak) if peak > 1e-4 else a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="wizard")
    ap.add_argument("--budget-kb", type=int, default=4600, help="total size of data/clips")
    ap.add_argument("--out", default=str(ROOT / "data" / "clips"))
    args = ap.parse_args()
    p = PERSONAS[args.persona]
    cfg = Config()
    fx = Fx(RATE, p.semitones, p.reverb, p.chorus)
    jaw = JawFollower(cfg, RATE)

    lines = []
    for kind in ("reply", "greet", "silence"):
        f = DIR / "personas" / p.id / f"{kind}.txt"
        lines += [(kind, l.strip()) for l in f.read_text().splitlines() if l.strip()]
    # Favour reply, then interleave the rest so a budget cut keeps a mix.
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.clp"):
        old.unlink()
    total, n, secs, skipped = 0, 0, 0.0, 0
    index = []
    for kind, text in lines:
        a = line_audio(text, p)
        if a is None:
            skipped += 1
            continue
        dry = tts.resample(a, 24000, RATE)
        tail = np.zeros(int(RATE * 0.25), dtype=np.float32)
        jaw.reset()
        lv = jaw.levels(np.concatenate([dry, tail]))
        wet = fx(dry) if p.effects else np.concatenate([dry, tail])
        # jaw.levels uses 20 ms blocks = 50 Hz.
        env = np.clip(np.round(lv * 1000), 0, 1000).astype("<u2")
        pcm = np.clip(np.round(wet * 32767), -32768, 32767).astype(np.int16)
        data = adpcm_encode(pcm)
        hdr = (b"BCLP" + bytes([1, 1]) + np.array([RATE], "<u2").tobytes() + np.array([len(pcm)], "<u4").tobytes()
               + np.array([JAW_HZ, len(env)], "<u2").tobytes())
        blob = hdr + env.tobytes() + data
        if total + len(blob) > args.budget_kb * 1024:
            break
        (out / f"{n:03d}.clp").write_bytes(blob)
        index.append(f"{n:03d}\t{kind}\t{text}")
        total += len(blob)
        secs += len(pcm) / RATE
        n += 1
    (out / "index.txt").write_text("\n".join(index) + "\n")
    print(f"{n} clips, {secs:.0f} s, {total / 1024:.0f} KB ({skipped} lines skipped: uncached), {len(lines)} lines")


if __name__ == "__main__":
    main()
