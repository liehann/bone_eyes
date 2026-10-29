# tools

- `make_envelopes.py`: voice clips → `data/clips/<name>.wav` (22.05 kHz mono)
  plus `<name>.env` (30 fps jaw envelope). Run `--help` for the tuning knobs.
  The clip workflow is in [../README.md#adding-voice-clips](../README.md#adding-voice-clips).
- `eye_preview.cpp` (+ `host_shim/`): renders the firmware's eye renderer on
  the host into a PPM contact sheet, including `data/uncanny/*.eye` sets and
  a colour tint. Build command is in the top-level README.
- `uncanny_convert.py`, `uncanny_sets.sh`: Uncanny Eyes artwork headers
  (TFT_eSPI `Animated_Eyes_2/data/`) → `data/uncanny/<style>.eye` for
  LittleFS. See [../docs/eye_styles.md](../docs/eye_styles.md).

Wiring is in [../README.md#wiring](../README.md#wiring). The single source of
truth for pins is `include/config.h`.

## fetch_secrets.py

Writes the gitignored `include/secrets.h` with `WIFI_SSID` / `WIFI_PASSWORD`
from the `phloots` Infisical project (default env `prod`; `--env dev` etc.).
Needs `infisical login --domain https://infisical.app.phloots.com` and the
LAN/VPN. Values are never printed. Rebuild and flash afterwards; without the
file the skull runs its own access point (see `include/config.h`).
