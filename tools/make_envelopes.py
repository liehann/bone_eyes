#!/usr/bin/env python3
"""Convert voice clips into skull-ready audio + jaw envelopes.

For every input clip this writes two files into the output dir (default:
../data/clips, which `pio run -t uploadfs` puts on LittleFS):

  <name>.wav  16-bit mono PCM at 22050 Hz. The firmware upsamples 2x and
              duplicates to stereo on the fly to feed A2DP / I2S at 44.1 kHz.
  <name>.env  jaw envelope, one byte (0 = closed, 255 = fully open) per frame
              at 30 frames/s (735 samples at 22050 Hz, so frames align exactly
              with the audio).

.env layout (little endian):
  0  char[4]  magic "BENV"
  4  u8       version (1)
  5  u8       frames per second (30)
  6  u16      reserved (0)
  8  u32      frame count N
  12 u8[N]    envelope

Clips whose name starts with "bye_" are goodbye clips; everything else is a
greeting. Inputs can be WAV (any rate/width/channels) or anything ffmpeg can
decode (mp3, m4a, ...) when ffmpeg is on PATH.

Examples:
  tools/make_envelopes.py recordings/*.wav
  tools/make_envelopes.py recordings/ --preview          # also writes PNGs
  tools/make_envelopes.py --synth-test test_beeps        # bench test clip
  tools/make_envelopes.py clip.wav --header include/clip_env.h
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

OUT_RATE = 22050
FPS = 30
FRAME = OUT_RATE // FPS  # 735
ENV_MAGIC = b"BENV"
ENV_VERSION = 1

# Default LittleFS budget for the 8 MB partition table (partitions_8mb.csv).
DEFAULT_BUDGET = 0x5F0000

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".aiff", ".aif"}


def load_audio(path: Path) -> tuple[np.ndarray, int]:
    """Return (mono float32 samples in [-1, 1], sample rate)."""
    if path.suffix.lower() == ".wav":
        try:
            rate, data = wavfile.read(path)
            return to_float_mono(data), rate
        except ValueError:
            pass  # unusual WAV encoding; let ffmpeg try
    if not shutil.which("ffmpeg"):
        sys.exit(f"{path}: can't decode without ffmpeg on PATH")
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1",
         "-ar", str(OUT_RATE), "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0, OUT_RATE


def to_float_mono(data: np.ndarray) -> np.ndarray:
    if data.dtype == np.uint8:
        x = (data.astype(np.float32) - 128.0) / 128.0
    elif data.dtype == np.int16:
        x = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        x = data.astype(np.float32) / 2147483648.0
    else:
        x = data.astype(np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    return x


def resample(x: np.ndarray, rate: int) -> np.ndarray:
    if rate == OUT_RATE:
        return x
    g = np.gcd(rate, OUT_RATE)
    return resample_poly(x, OUT_RATE // g, rate // g).astype(np.float32)


def trim_silence(x: np.ndarray, floor_db: float) -> np.ndarray:
    """Trim leading/trailing frames quieter than floor_db (keeps one frame of pad)."""
    n = len(x) // FRAME
    if n == 0:
        return x
    rms = np.sqrt(np.mean(x[: n * FRAME].reshape(n, FRAME) ** 2, axis=1) + 1e-12)
    loud = np.nonzero(20 * np.log10(rms) > floor_db)[0]
    if len(loud) == 0:
        return x
    start = max(loud[0] - 1, 0) * FRAME
    end = min(loud[-1] + 2, n) * FRAME
    return x[start:end]


def envelope(x: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    """RMS per 30 Hz frame -> dB -> 0..1 -> smoothing -> attack/release -> u8."""
    n = int(np.ceil(len(x) / FRAME))
    padded = np.zeros(n * FRAME, dtype=np.float32)
    padded[: len(x)] = x
    rms = np.sqrt(np.mean(padded.reshape(n, FRAME) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)

    # Map [peak - range, peak - headroom] (in dB) onto [0, 1]. Working relative
    # to the clip's own peak makes quiet and loud recordings move the jaw by
    # similar amounts; floor_db is an absolute gate under that.
    top = db.max() - args.headroom_db
    bottom = max(db.max() - args.range_db, args.floor_db)
    level = np.clip((db - bottom) / max(top - bottom, 1.0), 0.0, 1.0)
    level = level ** args.gamma

    # Light pre-smoothing (centred moving average) to kill single-frame flicker.
    if args.smooth > 1:
        k = np.ones(args.smooth) / args.smooth
        level = np.convolve(level, k, mode="same")

    # One-pole attack/release follower. Fast attack so syllables snap the jaw
    # open; slower release so it falls closed like a real jaw.
    dt = 1.0 / FPS
    a_att = 1 - np.exp(-dt / max(args.attack_ms / 1000, 1e-4))
    a_rel = 1 - np.exp(-dt / max(args.release_ms / 1000, 1e-4))
    out = np.empty_like(level)
    y = 0.0
    for i, v in enumerate(level):
        y += (a_att if v > y else a_rel) * (v - y)
        out[i] = y

    # Snap tiny openings shut so the servo doesn't buzz around "closed".
    out[out < args.min_open] = 0.0
    out[-1] = 0.0  # always end closed
    return np.round(out * 255).astype(np.uint8)


def write_env(path: Path, env: np.ndarray) -> None:
    path.write_bytes(
        ENV_MAGIC + struct.pack("<BBHI", ENV_VERSION, FPS, 0, len(env)) + env.tobytes()
    )


def write_header(path: Path, envs: dict[str, np.ndarray]) -> None:
    lines = ["// Generated by tools/make_envelopes.py - do not edit.", "#pragma once",
             "#include <stdint.h>", f"#define CLIP_ENV_FPS {FPS}", ""]
    for name, env in envs.items():
        ident = "".join(c if c.isalnum() else "_" for c in name)
        body = ",".join(str(int(v)) for v in env)
        lines.append(f"static const uint8_t env_{ident}[{len(env)}] = {{{body}}};")
    path.write_text("\n".join(lines) + "\n")


def write_preview(path: Path, x: np.ndarray, env: np.ndarray) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib not installed; skipping preview)")
        return
    t = np.arange(len(x)) / OUT_RATE
    te = (np.arange(len(env)) + 0.5) / FPS
    fig, ax = plt.subplots(figsize=(12, 3))
    ax.plot(t, x, lw=0.3, color="0.6")
    ax.plot(te, env / 255.0, lw=1.5, color="C3", drawstyle="steps-mid")
    ax.set_xlabel("s")
    ax.set_ylim(-1, 1.05)
    ax.set_title(path.stem)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def synth_test(seconds: float = 6.0) -> np.ndarray:
    """Beeps of varying length/level plus sharp clicks every second.

    The clicks coincide with full-open envelope spikes, which makes the
    Bluetooth latency offset easy to dial in by ear/eye on the bench.
    """
    t = np.arange(int(seconds * OUT_RATE)) / OUT_RATE
    x = np.zeros_like(t, dtype=np.float32)
    rng = np.random.default_rng(31)
    pos = 0.25
    while pos < seconds - 0.5:
        dur = rng.uniform(0.08, 0.35)
        amp = rng.uniform(0.15, 0.8)
        m = (t >= pos) & (t < pos + dur)
        x[m] += amp * np.sin(2 * np.pi * rng.uniform(180, 400) * t[m]) * np.hanning(m.sum())
        pos += dur + rng.uniform(0.08, 0.3)
    for s in np.arange(1.0, seconds, 1.0):
        i = int(s * OUT_RATE)
        x[i : i + 220] += 0.9 * np.sign(np.sin(2 * np.pi * 1000 * t[:220]))
    return np.clip(x, -1, 1).astype(np.float32)


def collect_inputs(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out += sorted(q for q in p.iterdir() if q.suffix.lower() in AUDIO_EXTS)
        else:
            out.append(p)
    return out


def main() -> None:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", type=Path, help="clip files or directories")
    ap.add_argument("-o", "--out", type=Path, default=here.parent / "data" / "clips")
    ap.add_argument("--floor-db", type=float, default=-50.0, help="absolute RMS gate: quieter is always closed (dBFS)")
    ap.add_argument("--range-db", type=float, default=18.0, help="dB below clip peak that maps to closed")
    ap.add_argument("--headroom-db", type=float, default=2.0, help="dB below clip peak that maps to fully open")
    ap.add_argument("--gamma", type=float, default=1.4, help=">1 keeps the jaw nearer closed on quieter sounds")
    ap.add_argument("--smooth", type=int, default=2, help="moving-average width in frames (1 = off)")
    ap.add_argument("--attack-ms", type=float, default=20.0)
    ap.add_argument("--release-ms", type=float, default=50.0)
    ap.add_argument("--min-open", type=float, default=0.06, help="openings below this snap shut (0..1)")
    ap.add_argument("--no-normalize", action="store_true", help="don't peak-normalize audio to -1 dBFS")
    ap.add_argument("--no-trim", action="store_true", help="don't trim leading/trailing silence")
    ap.add_argument("--preview", action="store_true", help="write <name>.png next to outputs (needs matplotlib)")
    ap.add_argument("--header", type=Path, help="also emit envelopes as a C header")
    ap.add_argument("--synth-test", metavar="NAME", help="generate a synthetic bench-test clip called NAME")
    ap.add_argument("--budget", type=lambda s: int(s, 0), default=DEFAULT_BUDGET, help="LittleFS bytes available")
    args = ap.parse_args()

    jobs: list[tuple[str, np.ndarray]] = []
    if args.synth_test:
        jobs.append((args.synth_test, synth_test()))
    for p in collect_inputs(args.inputs):
        x, rate = load_audio(p)
        x = resample(x, rate)
        if not args.no_trim:
            x = trim_silence(x, args.floor_db)
        jobs.append((p.stem, x))
    if not jobs:
        ap.error("no inputs (pass clip files/dirs or --synth-test NAME)")

    args.out.mkdir(parents=True, exist_ok=True)
    envs: dict[str, np.ndarray] = {}
    for name, x in jobs:
        if len(name) > 24:
            sys.exit(f"{name}: keep clip names <= 24 chars (LittleFS path limit is 31 incl. /clips/ + ext)")
        if not args.no_normalize and np.abs(x).max() > 0:
            x = x * (10 ** (-1 / 20) / np.abs(x).max())
        env = envelope(x, args)
        wavfile.write(args.out / f"{name}.wav", OUT_RATE, np.round(np.clip(x, -1, 1) * 32767).astype("<i2"))
        write_env(args.out / f"{name}.env", env)
        if args.preview:
            write_preview(args.out / f"{name}.png", x, env)
        envs[name] = env
        kind = "goodbye" if name.startswith("bye_") else "greeting"
        print(f"{name:24s} {len(x) / OUT_RATE:6.2f}s  {len(env):4d} frames  {kind}")

    if args.header:
        write_header(args.header, envs)

    used = sum(f.stat().st_size for f in args.out.iterdir() if f.suffix in {".wav", ".env"})
    print(f"\n{args.out}: {used / 1024:.0f} KiB of {args.budget / 1024:.0f} KiB LittleFS "
          f"({100 * used / args.budget:.0f}%), ~{(args.budget - used) / (OUT_RATE * 2):.0f}s of audio left")
    if used > args.budget * 0.95:
        print("WARNING: clips won't fit (LittleFS needs some slack); trim or drop clips", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
