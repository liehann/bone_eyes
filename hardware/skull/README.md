# Printable skull

An animatronic skull built from Peter from Belgium's CC0 anatomical skull
(Printables 2770): a removable face, the cranium back, a servo-driven jaw, an
electronics tray and a stand. Everything comes from `build.py` and is
reproducible.

![front](skull_front.png)

| Preview | |
|---|---|
| `skull_front.png`, `skull_side.png`, `skull_iso.png` | assembled, on the stand |
| `skull_jaw_open.png` | jaw at the full 18° opening |
| `skull_exploded.png` | parts pulled apart |
| `skull_bottom.png` | underside (servo cup, pivot boss, neck boss, USB exit) |
| `skull_section_orbits.png` | sections through the orbit centres and through one eye |
| `skull_section_jaw.png` | sections through the servo/neck and along the hinge axis |

## Build

```sh
cd hardware
python3 -m venv .venv && .venv/bin/pip install -r skull/requirements.txt
.venv/bin/python skull/build.py          # ~1 min; --no-render skips the PNGs
```

The script needs the source meshes, which are git-ignored because they are
65 MB. Download them from the links in `skull_src/*/LICENSE.txt` into the
same folders:

- `peter_belgium_2770/skull_mesh.stl`
- `peter_belgium_2770/skull_w_jaw.stl`
- `gage_recut_293680/jaw_top.stl`
- `gage_recut_293680/jaw_lower.stl`

The renders use the OpenSCAD CLI (`/Applications/OpenSCAD.app`). The script
writes `out/*.stl` (already in print orientation) and
`out/build_report.json` (measurements and checks), and caches the source
union in `cache/`.

## What the pipeline does

1. **Sources.** It unions the 35 watertight cranium shells into one solid,
   dropping zero-volume slivers. It unions `jaw_top` + `jaw_lower` and moves
   them into the articulated pose by an ICP fit onto the jaw inside
   `skull_w_jaw.stl`. It then rotates the jaw about the condyle axis until the
   teeth are `TEETH_GAP` (0.8 mm) apart. That is 9° more closed than Peter's
   pose, which has the mouth slightly open.
2. **Scale.** The orbit opening is the iso-depth contour (seen from the front)
   through the lateral orbital rim crest. It follows the medial, superior and
   inferior margins. The centre is the midpoint of the opening's breadth and
   height. The centres measure **59.0 mm** apart in the source, so the scale is
   **0.932×**. The origin is the midpoint between the orbits: Y = 0 is the
   median rim depth, the face looks toward −Y, and +Z is up.
3. **Clean shell.** The skull is voxelised at 0.5 mm.
   - Closing walls go into the eyes and the nose. Gaps narrower than about
     14 mm everywhere, 30 mm on the base and 44 mm round the zygomatic arches
     get a web recessed 3.5 mm behind the bridged surface (the temples, round
     the jaw hinge, the foramen magnum and the other base openings). The jaw's
     swept volume is carved out.
   - The script then flood-fills the outside air and keeps a uniform
     **2.6 mm** shell under everything you can see. Internal anatomy
     (sphenoid, conchae, orbit walls, cranial base interior) disappears.
   - The build fails if the brain cavity can be reached from outside.
   - The visible surface is Peter's original mesh; the inside is marching
     cubes.
4. **Parts and features**: split, posts, joints, servo, pivot, tray, neck. See
   below.
5. **Checks.** Every STL is re-read after export: each must be watertight and
   a single body. No two placed parts may overlap by more than 0.005 cm³:
   the face, back, jaw, eye bar, eye modules, servo, servo bracket, ESP32 + pin
   headers, radar, tray, stand and joint brackets. The jaw is swept from the
   closed stop to the open stop in 1° steps against the face, back, servo,
   bracket and stand. The joint brackets are slid on along Y to check that the
   back part can be fitted. The current build reports no collisions, a clear
   sweep, and stops that engage 1.5° past each end.

## Size

Assembled skull: **134 W × 184 L × 162 H mm** (cranium), about 205 mm tall
with the jaw. The stand adds 78 mm.

## Parts

| STL (`out/`) | Size as printed (mm) | Volume | Print orientation | Supports | Time (rough) |
|---|---|---|---|---|---|
| `face.stl` | 109 × 151 × 52 | 83 cm³ | cut face on the bed, face up | tree: eye plates/nasal wall (they print as roofs), eye-bar post ends, brow | ~3.5 h |
| `back.stl` | 134 × 147 × 132 | 192 cm³ | cut face on the bed, crown up | tree: neck boss, pivot boss, servo-flange bosses, base underside | ~8 h |
| `jaw.stl` | 99 × 97 × 69 | 49 cm³ | upright, as in the skull | tree under the lower border and the two hinge pads | ~2 h |
| `servo_bracket.stl` | 40 × 18 × 27 | 2.4 cm³ | mounting plate on the bed | none | 15 min |
| `tray.stl` | 72 × 74 × 24 | 22 cm³ | plate on the bed, cradle up | none | 45 min |
| `stand.stl` | Ø110 × 78 | 87 cm³ | base on the bed | none | ~2 h |
| `joint_bracket_*.stl` ×4 | about 19 × 12 × 19 | 1.3–2.2 cm³ | as exported | small, under the arm | 10 min each |
| `dowel.stl` (print 2) | Ø4 × 13 | — | upright | none | 5 min |

Times are estimates for a Bambu H2D with PLA at 0.2 mm (about 10 mm³/s
average plus support overhead). Check them in Bambu Studio. Everything fits
the H2D bed. The cranium back is the largest part at 134 × 147 × 132.

**Settings:** PLA (PETG if it will sit in sun or heat). 0.2 mm layers;
0.16 mm on the face for the teeth if you like. 4 walls, 25 % gyroid. Tree
supports (auto), threshold 30°, *on build plate only* (every support region
inside the parts is open to the bed through the cut face). Brim on the jaw.
The minimum designed wall is 1.6 mm. The shell is 2.6 mm, and the eye
plates/bezels and nasal wall are about 1.9 mm after the inner skin.

**Paint:** the eye plates (round the screens) and the nasal wall black, like
a prop skull. The radar sees through the nasal wall. Use paint without metal
flakes there.

## Mechanism

### Eyes
- The eye bar is `../eye_mount.scad` in `mount_style = "skull"`. Each module
  is turned 90° so its tip points at the nose, because the skull narrows
  quickly behind the orbits. **Rotate the picture 90° in firmware.**
- **Glass face: 6.0 mm behind the orbit rim plane.** That is 0.6 mm behind
  an eye plate whose Ø19.2 bezel frames the 18 mm active circle.
- Behind the plate, the orbit walls and the inner cavity are cleared for the
  modules (0.75 mm all round), the bar, the M2 heads, the connectors and their
  cables (a 16 mm channel behind each window), and screwdriver access to the
  bar bolts.
- The bar back face is at Y = 17.85 and the face/back cut at Y = 24. With the
  back off, all three bar bolts face you.
- Three posts on the inside of the face carry M3 inserts at (0, 0) and
  (±27.5, +16). The bar's slots are Ø3.6 with 3 mm vertical travel, so you can
  centre the screens in the bezels.

### Jaw: direct drive
- The hinge axis is the condyle axis (Y = 65.1, Z = −27.4), parallel to X.
- An MG90S sits in a closed cup in the cranium floor on the +X side, its
  output shaft on the hinge axis. The cup is part of the shell, so nothing
  inside is visible.
- The servo screws onto a separate L-bracket with its own tab screws. The
  bracket's flange drops in from inside and bolts down onto two insert bosses
  (M3×8, vertical).
- The horn (single or double arm, pointing down the ramus) screws to a flat
  pad on the inside of the jaw. There are Ø1.5 pilot holes at 8/10/12/14 mm
  from the axis for the horn screws, and a Ø7 hole over the horn screw.
- The other side pivots on an **M3×20** shoulder of the bolt. The head sits
  in a counterbore on the outside of the condyle, and the bolt runs into an
  insert in a boss hanging from the skull base, with a 0.5 mm gap. Add a
  washer.
- **Range: 0 to 18° nominal** (JAW_OPEN_DEG). That gives about 33 mm of chin
  travel, which reads clearly for a talking skull; 15–20° is the usual prop
  range. Set the servo limits in firmware.
- Hard stops: a finger on the pivot-side jaw pad runs in a slot in the skull
  boss and stops at −0.5° (teeth just clear; checked) and +20°.
- The condyle heads are trimmed 3.5 mm above the axis.
- The cranium is carved 1.2 mm clear of the jaw swept from −1.5° to +21.5°,
  and the shell wraps the carve, so the hinge region stays closed.
- Why direct drive works here: the hinge sits right at the level of the skull
  base. A vertical servo body (22.8 mm) fits mostly inside the cranium, with
  the cup bulging about 15 mm below the base, hidden between the jaw rami.
  There are no linkages to set up.

### Face/back joint
- The cut is a coronal plane at Y = 24, about 6 mm behind the eye bar.
- There are 4 **bracket joints**: two at the temples (screws from the side)
  and two in the base (screws from below).
  - Each bracket is a separate L-part. It bolts to an insert boss on the face
    with an M3×12 along Y (head toward the back, so you reach it while the back
    is off).
  - The back then slides on, and an M3×12 goes from outside through a
    counterbored pad in the back shell into an insert in the bracket.
  - The brackets are trimmed so the back slides on without catching (checked).
  - Every part prints with its cut face on the bed, which is why nothing
    sticks out of the cut.
- **2 dowels** (printed, Ø4 in Ø5 holes) at the top of the seam help line it
  up. The screws do the real locating.

### Electronics
- **ESP32-DevKitC-VIE** (no mounting holes). It sits in a cradle on a
  separate tray: two end walls with ledges 16 mm up, so the pin headers and
  DuPont housings fit underneath, and a zip-tie slot pair across the module
  end.
  - The board stands vertical, long axis up, USB at the bottom.
  - The tray bolts with 3× M3×8 onto three insert posts that come forward
    from the occipital wall (front faces at Y = 125).
- **USB exit:** a Ø13 hole in the floor at Y = 112, behind the neck boss, big
  enough for a micro-USB plug.
- **HLK-LD2410C** (35 × 7 mm, no holes) lies horizontal and faces forward
  behind the **1.9 mm nasal wall**. The wall is recessed 5 mm behind the
  piriform rim and sits between the radar and the room.
  - It sits in a frame pocket (0.6 mm clearance), open at the back for the
    header and cable.
  - Fix it with a dab of hot glue or tape. Antenna side to the wall.

### Stand
- The neck boss is Ø28 under the foramen magnum (Y = 90), with an M5
  heat-set insert (Ø6.4 × 10 hole) from below.
- The stand is a Ø110 base and a hollow Ø28 × 78 column. Bolt it from
  inside the column with an **M5×16**.
- To use a camera tripod instead, swap the insert for a 1/4-20 insert and
  change `NECK['insert_d']`.

## Fasteners

| Item | Qty | Where |
|---|---|---|
| M3 heat-set insert (Ø4.1 × 5.7 hole) | 17 | 3 eye-bar posts, 4 face joint bosses, 4 joint brackets, 1 jaw pivot boss, 2 servo-bracket bosses, 3 tray posts |
| M5 heat-set insert | 1 | neck boss |
| M3×12 | 11 | 3 eye bar, 4 brackets to face, 4 back to brackets |
| M3×20 | 1 | jaw pivot (+ M3 washer) |
| M3×8 | 5 | 2 servo bracket, 3 tray |
| M2×8 | 4 | modules to eye bar (existing stack) |
| M5×16 | 1 | stand to neck |
| servo tab screws (supplied) | 2 | servo to bracket (Ø1.8 pilots) |
| horn screws (supplied) | 1 + 2 | horn to spline; horn to jaw pad pilots |
| printed dowel | 2 | top of the seam |

## Assembly

1. Heat-set all the inserts. Do the face posts and bosses and the joint
   brackets from their open side.
2. **Face:**
   - Fit the modules to the eye bar (M2×8, tips toward the nose).
   - Plug in the cables through the windows.
   - Bolt the bar to the three posts (M3×12 from behind) and centre the
     screens in the bezels.
   - Fit the radar in its pocket behind the nose.
   - Bolt the four joint brackets to the face bosses (M3×12 along Y).
3. **Back:**
   - Screw the servo into its bracket. Lower it into the cup from inside, with
     the gear tower going down the slot in the cup wall. Bolt the flange
     (2× M3×8).
   - Bolt the tray with the ESP32 to the rear posts (3× M3×8) and route the
     USB cable out of the floor hole.
4. **Jaw:**
   - Centre the servo at the closed angle and push the horn on, pointing down
     the ramus.
   - Offer up the jaw, screw the horn to the jaw pad, then put the M3×20 pivot
     bolt (with a washer) through the other condyle into the pivot boss.
5. **Join:**
   - Put the dowels in.
   - Slide the back onto the face brackets and fit the 4 M3×12 from outside
     (two at the temples, two underneath).
6. Bolt the skull onto the stand (M5×16 from inside the column).

## Parameters you are likely to touch (top of `build.py`)

| Parameter | Default | Effect |
|---|---|---|
| `EYE_SPACING` | 55.0 | screen spacing, and so the overall scale |
| `EYE_PLATE_DEPTH`, `SCREEN_GAP` | 2.8, 0.6 | eye plate depth behind the rim; glass = plate + 2.6 + gap |
| `BEZEL_D` | 19.2 | bezel opening |
| `EYE_DZ` | 0 | move the eyes up/down in the orbits |
| `STANDOFF_H`, `MODULE_T` | 3.0, 3.2 | **measure your modules**; they set the bar depth |
| `SHELL_T` | 2.6 | wall thickness |
| `WEB_CLOSE_R`, `BASE_CLOSE_R`, `TEMPLE_CLOSE_R`, `WEB_RECESS` | 7, 15, 22, 3.5 | how big a gap gets webbed, and how deep the web sits |
| `NASAL_RECESS`, `NASAL_T` | 5, 1.8 | nasal wall / radar window |
| `JAW_OPEN_DEG`, `JAW_STOP_MARGIN`, `JAW_CLOSE_STOP`, `TEETH_GAP` | 18, 2, −0.5, 0.8 | jaw range and stops |
| `SERVO`, `SERVO_SIDE`, `HORN_FACE_X` | MG90S | servo dimensions and side |
| `Y_SPLIT`, `JOINTS`, `DOWELS` | 24 | cut plane and joint positions |
| `RADAR`, `ESP32`, `TRAY`, `TRAY_POSTS`, `USB_EXIT` | | electronics |
| `NECK`, `STAND` | M5 | neck insert and stand size |
| `FIT` | 0.75 | clearance round dropped-in parts |

## Compromises

- **Scale is 0.932×, not ~0.89×.** Measured at the rim crest as described
  above, the source orbit centres are 59 mm apart, not 62. The skull is
  therefore close to life size (134 × 184 × 162 mm).
- **The modules are rotated 90° and need a firmware rotation.** Behind the
  orbits the skull narrows to about ±31 mm at the bar depth. With the original
  layout, the outer M2 screws (x = ±35.4) would go through the temple wall.
- **The eye plates are flat bezels**, coronal round the screen and bent back
  toward the lateral rim. The sockets are therefore only about 3 mm deep before
  the plate. Paint them black.
- **The arches are webbed, not free.** The temple and infratemporal gaps are
  closed by a recessed web, so the zygomatic arches read in relief rather than
  as free bars.
- **The servo cup and the jaw-pivot boss show from below.** They hang 10–15 mm
  under the skull base between the jaw rami. The tip of the servo horn shows
  just behind the ramus.
- The jaw is a pure hinge about the condyle axis; a real jaw also slides
  forward.
- **The module stack is estimated.** `STANDOFF_H` and `MODULE_T` are
  estimates from photos. If your modules differ, change them and rebuild.
- The inner surfaces are marching cubes at 1 mm. They are hidden, but faceted.
- A few pinch edges (where two surfaces touch at a line) are filled with
  1 mm blobs so every STL is strictly watertight.
