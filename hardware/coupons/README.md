# M3 heat-set insert practice coupon

Generate: `hardware/.venv/bin/python hardware/coupons/insert_practice.py` (STLs go to `out/`).

Both parts print flat, top face up, no supports, 4 wall loops. 0.5 mm bottom chamfer.

## insert_block.stl (77 x 30 x 12 mm, boss to 20 mm)

Pilots are 6.7 deep with a 3 mm Ø3.2 relief below. Holes run left to right
(x = 5.5 + 11 n mm, y = 15). V-grooves up the front face under each hole give
the count.

| # | Pilot Ø | Notches |
|---|---------|---------|
| 1 | 3.8 | 1 |
| 2 | 3.9 | 2 |
| 3 | 4.0 | 3 (skull size) |
| 4 | 4.0 | 4 (skull size, spare) |
| 5 | 4.1 | 5 |
| 6 | 4.2 | 6 |
| boss | 4.0 | none: Ø9 x 8 tall boss at the right end, bore from its top |

## screw_plate.stl (66 x 30 x 3 mm)

Ø3.4 clearance holes over holes 1 to 6. Lay it on the block (left-aligned) and
screw M3x8 / M3x12 through. The boss sits outside the plate; test it with a
screw straight into the insert.
