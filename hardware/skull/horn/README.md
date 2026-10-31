# Printed jaw horn (MG90S)

A printed replacement for the stock single-arm horn that drives the jaw. It
takes the stock horn's place exactly, so the jaw sits where it does now.

```
hardware/.venv/bin/python hardware/skull/horn/make_horn.py --check
```

It writes `out/horn_b44.stl` … `out/horn_b47.stl` and `out/horn_plate.stl`
(all four, 10 mm apart). `--check` also runs the assembly check (below); it
needs `hardware/skull/cache` (symlink it from the main checkout).

## Shape

| | |
|---|---|
| size | 22.0 × 9.0 × 3.2 mm (plate 22 × 66 × 3.2) |
| arm | hull of the Ø9 hub and a Ø7 tip disc at 14 mm, along `horn_dir()` (20° forward of straight down) |
| thickness | 3.2 mm everywhere: hub and arm (the stock arm is about 2 mm) |
| jaw pilots | Ø1.7 through at 10 and 14 mm (`HORN_JAW_HOLES`), 2.65 mm wall at the sides and the tip |
| hub | blind press-fit bore from the top, 2.2 deep, with a 0.3 lead-in; 1.0 mm floor over the spline top |
| horn screw | Ø2.5 through the floor, centred; the head sits on the outer face |
| bore marks | notches in the tip end: 1 = Ø4.4, 2 = Ø4.5, 3 = Ø4.6, 4 = Ø4.7 |

In the servo frame of `build.py` the outer face is the jaw pad face
(|x| = `HORN_FACE_X` = 33.0), the bore floor is the spline top (1.0 mm in), and
the hub bottom is 0.2 mm above the modelled gear bump.

- **Screw engagement:** the M2×16 jaw screws reach 3.2 mm past the pad face
  (build report, `fastener_check`: clamp 12.8 mm). The arm is 3.2 mm thick, so
  each screw engages the full 3.2 mm in the Ø1.7 pilot. The stock horn gave
  about 2 mm. A thicker arm adds no thread unless the screws get longer.
- **Head seat:** the horn-screw head stands proud of the outer face, inside
  the jaw's Ø7 × 4 (`HORN_HUB_CB`) counterbore. Any M2 or M2.5 pan head up to
  Ø6.5 × 3.5 fits, so the jaw sits flat on the arm.

## Checks (`--check`)

- Each variant is watertight and one body. `printability.analyse()` reports
  no overhang and no support. The bed contact is about 137 mm².
- In the assembled pose (from `cache/render`) the outer face lands on
  |x| = 33.00. The horn does not overlap the jaw, and both jaw pilots line up
  with the horn pilots.
- Over the jaw sweep from −2.5° to 22° (both stops plus margin), the minimum
  gaps are:
  - servo case and gear bump: 0.20 mm (hub bottom over the bump; the spline itself is excluded);
  - servo bracket: ≥ 3 mm;
  - chassis (face): 2.26 mm.
- Maximum radius 17.5 mm, inside `HORN_R` = 19.

## Print

- **Pose:** flat, with the outer (jaw-side) face on the bed. The bore opens
  upward. No supports. There is a 0.3 mm chamfer on the bed edge.
- **Settings:**
  - 0.12–0.16 mm layers, 100 % infill (tiny parts print best solid), 4 walls;
  - PLA (PETG is fine too);
  - no brim needed; glue stick helps on a small footprint.
- Layers run along the arm, so the arm bends in plane with the layers.
- Print the whole plate; it takes a few minutes.

## Fit

1. **Centre the servo first.** Power it and command the jaw's closed position
   (or the servo centre the firmware uses for the horn), so the arm can go on
   pointing down the ramus as before.
2. **Pick the bore.** Try each horn on the spline by hand, starting from the
   largest bore (4 notches). Use the one that needs a firm press to start, not
   the one that slides on. If none starts by hand, use the largest.
3. **Warm and press.**
   - Warm the hub for about 20 s with a hair dryer, or briefly with hot air,
     until it is warm to the touch but not soft.
   - Press it on straight along the shaft. The metal spline cuts its own teeth.
   - Push until the bore floor sits on the spline top. The outer face is then
     flush with where the stock horn's face was.
   - Hold the arm square while it cools. Don't rock it.
4. **Horn screw.** Fit the supplied horn screw through the centre and snug it.
   Don't overtighten: the floor under the head is 1.0 mm.
5. **Fit the jaw** as before: 2× M2×16 self-tapping from outside the ramus,
   through the jaw's Ø2.2 pilots into the horn's Ø1.7 pilots. Let them cut
   their thread slowly, and stop when the head seats.

## Check before fitting

- **Spline diameter:** the `SERVO` model uses Ø4.8. The four bores
  (4.4–4.7) assume about Ø4.8 over the teeth. If the spline measures
  differently, change `BORES`.
- **Horn screw:** the clearance hole is Ø2.5, for an M2 screw. If the
  supplied screw is M2.5, drill it out to Ø2.7. The head must be no larger
  than Ø6.5 × 3.5 to stay inside the jaw counterbore.
- **Hub height:** the hub bottom clears the modelled gear bump by only
  0.2 mm. If the hub reaches the case top before the bore floor reaches the
  spline top, sand the hub bottom down a little. Otherwise the jaw stands off
  the pad.
