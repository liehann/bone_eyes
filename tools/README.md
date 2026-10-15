# tools

- `make_envelopes.py`: voice clips → `data/clips/<name>.wav` (22.05 kHz mono)
  plus `<name>.env` (30 fps jaw envelope). Run `--help` for the tuning knobs.
  The clip workflow is in [../README.md#adding-voice-clips](../README.md#adding-voice-clips).
- `eye_preview.cpp` (+ `host_shim/`): renders the firmware's eye renderer on
  the host into a PPM contact sheet. Build command is in the top-level README.

Wiring is in [../README.md#wiring](../README.md#wiring). The single source of
truth for pins is `include/config.h`.
