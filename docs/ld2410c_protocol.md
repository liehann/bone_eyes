# HLK-LD2410C UART protocol notes

Sources: Hi-Link *HLK-LD2410C Serial Communication Protocol V1.00*
(https://www.sudo.is/docs/esphome/components/ld2410/HLK-LD2410C_Serial_communication_protocol_v1.00.pdf),
ESPHome `components/ld2410/ld2410.cpp`, ncmreynolds/ld2410.

256000 baud 8N1, little endian, 3.3 V IO, 5 V >200 mA supply.

## Data frame (total = len + 10 bytes)

| Off | Field |
|---|---|
| 0–3 | `F4 F3 F2 F1` |
| 4–5 | len u16 (13 basic, 35 engineering) |
| 6 | type: 0x02 basic, 0x01 engineering |
| 7 | 0xAA |
| 8 | state: bit0 moving, bit1 stationary (0 none … 3 both) |
| 9–10 | moving distance cm |
| 11 | moving energy 0–100 |
| 12–13 | still distance cm |
| 14 | still energy |
| 15–16 | detection distance cm |
| engineering: 17 | max moving gate N |
| engineering: 18 | max still gate N |
| engineering: 19–27 | moving energy gates 0–8 |
| engineering: 28–36 | still energy gates 0–8 |
| engineering: 37, 38 | light (0–255), OUT state (ESPHome's reading; undocumented by Hi-Link) |
| len+4, len+5 | `55 00` |
| last 4 | `F8 F7 F6 F5` |

Example basic: `F4 F3 F2 F1 0D 00 02 AA 02 51 00 00 00 00 3B 00 00 55 00 F8 F7 F6 F5`

## Commands (`FD FC FB FA | len u16 | cmd u16 | value | 04 03 02 01`)

ACK echoes `cmd | 0x0100`, status u16 at bytes 8–9 (0 = ok). Every command
must be wrapped in enable-config / end-config. Periodic reports stop while in
config mode.

- enable config: `FD FC FB FA 04 00 FF 00 01 00 04 03 02 01`
- end config: `FD FC FB FA 02 00 FE 00 04 03 02 01`
- engineering on: `FD FC FB FA 02 00 62 00 04 03 02 01`
- engineering off: `FD FC FB FA 02 00 63 00 04 03 02 01`
- read params: `FD FC FB FA 02 00 61 00 04 03 02 01`
- read firmware: `FD FC FB FA 02 00 A0 00 04 03 02 01`
- set max gates + unmanned duration (0x0060): words 0x0000 move gate, 0x0001
  still gate, 0x0002 duration s, each value u32.
- 0x00AA resolution: 0 = 0.75 m/gate (default), 1 = 0.2 m/gate (restart needed).

## Behaviour

- No angle/azimuth. Distance-only single target (LD2450 does angles).
- Gates 0–8 → ~6 m max at 0.75 m.
- Unmanned duration default 5 s: stays "occupied" that long after the area empties.
- OUT pin high while presence detected.
- Report rate undocumented (community: ~10 Hz). Measure it.
