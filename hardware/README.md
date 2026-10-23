# Eye mount

Flat bar holding both Waveshare 0.71" round LCD modules (GC9D01, 160×160),
screens facing forward, with M3 heat-set insert bosses for attaching it to the
skull internals.

| File | What |
|---|---|
| `eye_mount.scad` | Parametric OpenSCAD source (all numbers at the top) |
| `eye_mount.stl` | Export at default parameters |
| `eye_mount_front.png`, `eye_mount_back.png`, `eye_mount_iso.png` | Previews |

Overall size: **102 × 26.1 × 9.45 mm** (X × Y × Z). The bar is 5.65 mm thick.
The locating rims rise to 9.45 mm and the insert bosses to 9.0 mm.

Re-export after changing a parameter:

```sh
OPENSCAD=/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD
$OPENSCAD -o eye_mount.stl eye_mount.scad          # ~2.5 min CGAL render
$OPENSCAD -o eye_mount_iso.png --imgsize=1600,900 \
  --camera=0,0,0,55,0,25,170 --viewall --autocenter --colorscheme=Tomorrow eye_mount.scad
```

## Where the numbers come from

Waveshare dimension drawing
(<https://www.waveshare.com/w/upload/6/68/0.71inch-LCD-Module-details-size.jpg>,
on the [wiki](https://www.waveshare.com/wiki/0.71inch_LCD_Module) under
Dimensions):

| Parameter | Value | Source |
|---|---|---|
| PCB/glass width (round part) | 20.12 ±0.15 | drawing |
| Overall height incl. pointed tip | 22.30 ±0.15 | drawing |
| Active display circle | 18.00 | drawing |
| Tip flat (display FPC wraps round it) | 7.34 | drawing |
| **Standoff spacing** | **15.75** | drawing (the user measured 15.45) |
| Standoff axis to tip edge | 12.10 | drawing |
| Standoff OD | 3.82 | drawing (ΦM2 thread) |
| Connector housing width | 9.20, 8-pin SH1.0 | drawing / product page |
| Connector Y span (2.6–7.7 mm below standoff axis) | approximate | scaled from the drawing photo, not dimensioned |
| Standoff height | 3.0 | **estimate** from product photos; not on the drawing |
| Eye spacing | 55.0 | user |
| Screw left outside standoff (M2×8) | 5.65 | user |

From the drawing:

- **The standoffs lie on a horizontal line** (X axis, parallel to the bar),
  symmetric about the screen's vertical centreline. They sit on the screen's
  horizontal diameter. Taking the round part as a 20.12 mm circle,
  22.30 − 10.06 = 12.24 mm from centre to tip. The standoffs are 12.10 from the
  tip, so they sit 0.14 mm below the screen centre (towards the tip). That is
  within the ±0.15 tolerance and the model uses it (`hole_dy`).
- **The screen is centred on the PCB** horizontally. The 18.00 active circle
  is centred in the 20.12 outline. Vertically the model assumes it is
  concentric with the round part of the PCB.
- **The 8-pin SH1.0 connector is a vertical (top-entry) connector** on the
  back. It is centred left to right and sits between the standoff line and the
  pointed tip, so the cable plugs straight out of the back. The bar has a
  through window (11.6 × 7.5 mm) behind each connector. The cable plugs in
  through the bar, so no side channel is needed.
- **The pointed tip is "down"** (−Y in the model). The display FPC wraps round
  the tip edge, so the rim has a 9 mm notch there.

**Discrepancy:** the drawing gives a standoff spacing of **15.75 mm**, but the
user measured **15.45 mm**. The model uses the drawing value. Before printing,
measure the outer edges of the two brass standoffs and subtract one OD (3.82).
If the result is about 15.45, set `standoff_spacing = 15.45`. The 2.3 mm holes
allow about ±0.15 mm of error, so they will not absorb a 0.3 mm error.

**Measure the standoff height** (PCB back to the standoff end face) and set
`standoff_h`. Only the locating rim height depends on it.

## Stack-up (Z, bed = back face = 0)

```
z = 0      back face / bed. M2 screw head bears here.
z = 5.65   front face of bar = standoff end faces sit here (raised seats)
z = 5.05   relief floor under the rest of the PCB (relief_d = 0.6)
z = 8.65   PCB back face   (5.65 + standoff_h 3.0)
z = 9.45   top of locating rim (5.65 + standoff_h + rim_engage 0.8)
```

- Screw: 8.0 − 5.65 (material under the head) = **2.35 mm in the standoff**.
  This is the user's figure, so the screw just bottoms out with full thread
  engagement.
- The PCB locating pocket is **not** cut into the bar. It is a raised rim
  (1.6 mm wall, 0.3 mm clearance round the PCB outline) standing on the front
  face. The screw seats are therefore still the full 5.65 mm. The rim rises
  `standoff_h + 0.8` mm, so it overlaps the bottom 0.8 mm of the PCB edge,
  which stops the module rotating about the two screws. The rim top stays
  below the PCB front face, so it does not shade the glass.
- The 0.6 mm relief under the PCB (outside two 5.2 mm seats round the
  standoffs) adds clearance for back-side ICs if the standoffs turn out
  shorter than expected. It does not touch the screw stack.
- `plate_t` sets the bar thickness. If you raise it above `screw_t` (5.65),
  the model adds a 4.2 mm counterbore from the back of depth
  `plate_t − screw_t`, so the screw seat stays at 5.65. That counterbore opens
  on the bed side and leaves a small overhang ring. With the default
  `plate_t = 5.65` there is no counterbore.

## Attachment points

- Three **M3 heat-set insert bosses** (Ø9 mm, 9 mm tall) at X = −44, 0, +44.
  Each has a Ø4.1 × 5.7 mm insert hole from the front with a 0.5 mm lead-in
  chamfer, and a Ø3.3 clearance hole through the 3.3 mm floor. Press the
  inserts in from the front. Bolts come from the skull side through the back
  into the insert, so the load pushes the insert onto the floor rather than
  pulling it out.
- Two **M3 adjustment slots** (Ø3.3 × 6 mm travel, vertical) at X = ±9. Use
  them with nuts or with inserts on the mating bracket for height adjustment.
- To move or remove them, edit the `insert_bosses` and `adjust_slots` lists.
  `end_boss_x` and `bar_h` set the bar's length and height.

## Print settings (Bambu Studio)

- Orientation: as exported, **back face down**. There are no overhangs, so
  supports are off.
- PLA or PETG. Use PETG if the skull gets warm.
- 0.2 mm layers, 4 walls (makes the 1.6 mm rims and the bosses solid),
  20–30 % infill, 4 top and 4 bottom layers.
- The model already has the elephant-foot chamfer (0.5 mm on the bed-side
  edges, the cable windows and the M3 holes). You can leave Bambu's "Elephant
  foot compensation" at 0. The M2 holes are deliberately not chamfered, so the
  screw head gets a full flat seat.
- Holes print at nominal + 0.1 mm (`hole_comp`). The M2 holes are 2.3 mm and
  the M3 clearance holes 3.3 mm, as polygons whose flats sit on that
  diameter. If the M2 holes come out tight, raise `hole_comp` or
  `m2_clear_d` (anything from 2.2 to 2.4 works). Tune `insert_d` to your
  inserts' datasheet.

## Assembly

1. Heat-set the three M3 inserts from the front (rim side), flush with the
   boss tops.
2. Drop each module into its rim with the screen facing out and the pointed
   tip in the FPC notch. The standoffs land on the raised seats.
3. Plug the SH1.0 cable through the window from the back into the connector.
   Do this before screwing down if the window is tight for your fingers.
4. Fit the M2×8 screws from the back into the standoffs. Snug them only, as
   the brass standoffs strip easily.
5. Bolt the bar to the skull internals with M3 bolts from behind into the
   inserts, and use the slots for vertical adjustment.
