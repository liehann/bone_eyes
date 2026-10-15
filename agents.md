# bone_eyes — agent notes

Animatronic talking Halloween skull (deadline 2026-10-31). ESP32-WROVER-IE
firmware (PlatformIO, Arduino core 2.0.17) + offline Python tooling.

## Layout / workflow

- Container layout: `~/Projects/bone_eyes/main` is the `main` checkout;
  feature worktrees live beside it as `~/Projects/bone_eyes/<slug>`. Use
  `/feature-start <slug>` and `/feature-end`. No issue tracker (no §8 key),
  so feature-start is Step 1 only.
- `include/config.h` — every pin and tunable. Change pins only there.
- `src/` — one module per concern (console, eyes, radar, jaw, audio,
  behavior). Modules register their own console commands via `console::add`.
- `tools/make_envelopes.py` — clip → 22.05 kHz mono WAV + 30 fps jaw envelope
  into `data/clips/`; `pio run -t uploadfs` flashes them.
- `docs/` — protocol notes (LD2410C, GC9D01) with sources.

## Build

- `pio run` (A2DP, default env `skull`), `pio run -e skull_i2s` (PCM5102).
- Commit after each milestone (see README milestone list).
