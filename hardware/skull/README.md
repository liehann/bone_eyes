# Printable skull

An animatronic skull built from Peter from Belgium's CC0 anatomical skull
(Printables 2770): a removable face, the cranium back, a servo-driven jaw, an
electronics tray and a stand. Everything comes from `build.py` and is
reproducible.

![front](skull_front.png)

| Preview | |
|---|---|
| `skull_front.png`, `skull_iso.png`, `skull_side.png` | assembled, on the stand; sockets/nose drawn painted black, screens gold |
| `skull_jaw_open.png` | jaw at the full 18° opening |
| `skull_exploded.png` | parts pulled apart |
| `skull_bottom.png` | underside (servo cup, pivot boss, neck boss, USB slot) |
| `skull_face_from_behind.png`, `skull_face_from_behind_34.png` | the face part from behind: open, nothing between you and the eye/radar mounts |
| `skull_face_from_behind_hw.png` | the same with the eye bar, modules, radar and joint brackets in place |
| `skull_back_from_front.png`, `skull_back_from_front_34.png` | the cranium back seen through its cut, with the servo and the ESP32 tray |
| `skull_section_orbits.png` | sections through the orbit centres and through one eye (socket bowls, modules, bar) |
| `skull_section_jaw.png` | sections through the servo/neck and along the hinge axis |

## Build

```sh
cd hardware
python3 -m venv .venv && .venv/bin/pip install -r skull/requirements.txt
.venv/bin/python skull/build.py          # ~2.5 min; --no-render skips the PNGs
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
   median rim depth, the face looks toward −Y, and +Z is up (2 mm above the
   orbit centres, `EYE_DZ`).
3. **Eye sockets and nose.** Each is a smooth bowl lofted analytically in
   manifold3d (not voxels). It starts at the measured rim outline, runs
   straight back, then curves in (a quarter-ellipse profile per angle).
   - Eyes: each bowl ends in a flat bezel with a Ø18.5 opening. The glass sits
     **15 mm behind the rim plane**.
   - Nose: the bowl ends in a flat 1.8 mm window 6 mm behind the piriform rim.
     The radar looks through it.
4. **Clean shell.** The skull is voxelised at 0.5 mm.
   - The bowls seal the eyes and nose.
   - Recessed webs (3.5 mm behind the bridged surface) close gaps narrower
     than about 14 mm everywhere, 30 mm on the base and 44 mm round the
     zygomatic arches. That covers round the jaw hinge, the foramen magnum and
     the other base openings.
   - The temporal fossae above the arches are filled flush (a closing of 30 mm
     radius), giving full, smooth temples like a prop skull. This is also what
     makes room behind the eyes.
   - The jaw's swept volume is carved out.
   - Everything behind the eyes is sealed at the outer hull (`BEHIND_EYES`),
     and a wall closes the back of the nasal cavity (`CHOANA`). Without these,
     outside air reached in beside the arches and through the throat, and the
     shell lined that air with walls. Those walls formed a plate behind the
     eyes that blocked assembly. The build now asserts that the space behind
     the eyes and the nasal cavity are inside.
   - The script then flood-fills the outside air and keeps a uniform
     **2.6 mm** shell under everything you can see. Internal anatomy
     (sphenoid, conchae, orbit walls, cranial base interior) disappears.
   - The build fails if the brain cavity can be reached from outside.
   - The visible bone surface is Peter's original mesh. Web and inner surfaces
     are marching cubes on a smoothed distance field. The bowls are then cut
     in exactly, so their visible surfaces are smooth.
5. **Parts and features**: split, posts, joints, servo, pivot, tray, neck. See
   below.
6. **Checks.** Every STL is re-read after export: each must be watertight and
   a single body. No two placed parts may overlap by more than 0.005 cm³:
   the face, back, jaw, eye bar, eye modules, servo, servo bracket, ESP32 + pin
   headers, radar, tray, stand and joint brackets. The jaw is swept from the
   closed stop to the open stop in 1° steps against the face, back, servo,
   bracket and stand. The joint brackets are slid on along Y to check that the
   back part can be fitted. Every clearance cut (modules, bar, cables, screw
   access, radar) must stay inside the skull's closed envelope, so none of
   them opens a hole in the surface.
   - **Assembly paths.** The eye bar with both modules and their plugged-in
     cables goes in straight from behind, and so does the radar. Their swept
     paths, from the final position back past the cut, are kept free of face
     material, including screwdriver access to the three bar bolts. That path
     also must not leave the skull. The joint bosses and dowel bosses are
     placed outside it. The current build reports no collisions, a clear
   sweep, and stops that engage 1.5° past each end.

## Size

Assembled skull: **134 W × 184 L × 162 H mm** (cranium), about 205 mm tall
with the jaw. The stand adds 78 mm.

## Parts

| STL (`out/`) | Size as printed (mm) | Volume | Print orientation | Supports | Time (rough) |
|---|---|---|---|---|---|
| `face.stl` | 113 × 154 × 61 | 113 cm³ | cut face on the bed, face up | tree: socket bowls and nasal bowl (their backs face the bed), eye-bar post ends, brow | ~4.5 h |
| `back.stl` | 134 × 145 × 123 | 183 cm³ | cut face on the bed, crown up | tree: neck boss, pivot boss, servo-flange bosses, base underside | ~7.5 h |
| `jaw.stl` | 99 × 97 × 69 | 49 cm³ | upright, as in the skull | tree under the lower border and the two hinge pads | ~2 h |
| `servo_bracket.stl` | 40 × 18 × 27 | 2.4 cm³ | mounting plate on the bed | none | 15 min |
| `tray.stl` | 72 × 74 × 24 | 22 cm³ | plate on the bed, cradle up | none | 45 min |
| `stand.stl` | Ø110 × 78 | 87 cm³ | base on the bed | none | ~2 h |
| `joint_bracket_*.stl` ×4 | about 20 × 16 × 12 | ~2 cm³ | as exported | small, under the arm | 10 min each |
| `dowel.stl` (print 2) | Ø4 × 13 | — | upright | none | 5 min |

Times are estimates for a Bambu H2D with PLA at 0.2 mm (about 10 mm³/s
average plus support overhead). Check them in Bambu Studio. Everything fits
the H2D bed. The cranium back is the largest part at 134 × 145 × 123.

**Settings:** PLA (PETG if it will sit in sun or heat). 0.2 mm layers;
0.16 mm on the face for the teeth if you like. 4 walls, 25 % gyroid. Tree
supports (auto), threshold 30°, *on build plate only* (every support region
inside the parts is open to the bed through the cut face). Brim on the jaw.
The minimum designed wall is 1.6 mm. The shell is 2.6 mm, the socket bowls
2.0 mm and the nasal window 1.8 mm.

**Paint:** the socket bowls and the nose bowl black, like a prop skull. The
radar sees through the nasal window. Use paint without metal flakes there.

## Mechanism

### Eyes
- **Glass face: 15.0 mm behind the orbit rim plane** (`EYE_DEPTH`).
  - Each socket is a smooth black bowl from the rim outline down to a flat
    2 mm bezel with a Ø18.5 opening (the active circle is 18 mm). The glass
    sits 0.6 mm behind it.
  - I tried 12–18 mm. At 16 mm and deeper the module or bar clearance breaks
    through the skull wall just behind the lower outer orbit, so 15 is the
    deepest clean value.
  - The eyes sit 2 mm above the measured orbit centres (`EYE_DZ`) for the
    same reason. That also helps the look.
- **The eye bar is `../eye_mount.scad` (`mount_style = "skull"`).** Each
  module is turned 90° so its tip points at the nose.
  - Even with the filled temples, the outer M2 screws of the unrotated layout
    (x = ±35.4) would break through the temple wall at the bar's depth
    (y = 21–27). **The firmware has to rotate the picture 90°.**
  - The bar plate is now ±10.4 mm tall with its lower outer corners chamfered
    by 4 mm. That corner of the skull is the tightest spot.
- Behind the bowls, everything is cleared with 0.75 mm round it: the
  modules, the bar, the M2 heads, the connectors and their cables (a 16 mm
  channel behind each window), and screwdriver access to the bar bolts.
- The bar back face is at Y = 26.85. The face/back cut is placed 6 mm
  behind it (Y = 32.9, `Y_SPLIT = None` means automatic). With the back off,
  all three bar bolts face you.
- Three posts on the inside of the face carry M3 inserts at (0, 0) and
  (±27.5, +16). The bar's slots are Ø3.6 with 3 mm vertical travel, so you
  can centre the screens in the bezels.

### Jaw: direct drive
- The hinge axis is the condyle axis (Y = 65.1, Z = −29.4 in the eye frame), parallel to X.
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
- The cut is a coronal plane at Y = 32.9, 6 mm behind the eye bar.
- **From behind, the face part is open:** you see only the socket bowl backs
  with their screen openings, the three eye-bar posts, the radar frame, four
  small joint bosses near the outer wall, and two dowel bosses at the top.
  Nothing bridges between the bowls.
- There are 4 **bracket joints**, all with screws from the side:
  - two at the temples (z = +28, 9 mm behind the cut);
  - two just above the arches (z = 0, 7 mm behind the cut).
  - The script picks each position from a short list. A position is accepted
    when:
    - the bracket, trimmed so the back slides on without catching, still has
      solid material round its insert and its screw;
    - the face boss stays out of the eye-bar and radar insertion path.
  - Each bracket is a separate L-part. Its flange sticks out sideways and
    bolts to a compact insert boss on the face with an M3×12 along Y. The head
    faces back, so you reach it while the back is off.
  - The back then slides on, and an M3×12 goes from outside through a
    counterbored pad in the back shell into an insert in the bracket. The
    counterbore leaves 3 mm under the head.
  - Every part prints with its cut face on the bed, which is why nothing
    sticks out of the cut.
- The cranial-base level of the seam has no joint. There is no room there
  outside the eye-bar path, and the shells are stiff enough.
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
- **Power: USB cable slot.** An 18 × 11 mm slot with round ends goes through
  the floor at x = 0, Y = 114, just behind the neck boss. It is underneath
  and invisible from the front, and a USB-A plug passes through it.
  - A zip-tie arch (`TIE_BAR`, tunnel 7 × 5 mm) stands on the floor 13 mm
    behind the slot for strain relief.
  - Power comes from outside: a power bank or the laptop. There is no
    internal battery bay.
- **HLK-LD2410C** (35 × 7 mm, no holes) lies horizontal and faces forward
  behind the **1.8 mm nasal window**: the flat bottom of the nose bowl, 6 mm
  behind the piriform rim.
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
   - Then bolt the four joint brackets to the face bosses (M3×12 along Y).
     Do this after the bar, because the brackets sit beside the bar's
     insertion path.
3. **Back:**
   - Screw the servo into its bracket. Lower it into the cup from inside, with
     the gear tower going down the slot in the cup wall. Bolt the flange
     (2× M3×8).
   - Bolt the tray with the ESP32 to the rear posts (3× M3×8) and route the
     USB cable out of the floor slot. Zip-tie it to the arch behind the slot.
4. **Join:**
   - Put the dowels in.
   - Slide the back onto the face brackets and fit the 4 M3×12 from outside
     (all four from the sides).
5. **Jaw:**
   - Centre the servo at the closed angle and push the horn on, pointing down
     the ramus.
   - Offer up the jaw, screw the horn to the jaw pad, then put the M3×20 pivot
     bolt (with a washer) through the other condyle into the pivot boss.
6. Bolt the skull onto the stand (M5×16 from inside the column).

## Parameters you are likely to touch (top of `build.py`)

| Parameter | Default | Effect |
|---|---|---|
| `EYE_SPACING` | 55.0 | screen spacing, and so the overall scale |
| `EYE_DEPTH` | 15 | glass depth behind the rim plane (the bowl depth) |
| `SOCKET_WALL`, `SCREEN_GAP`, `APERTURE_D` | 2.0, 0.6, 18.5 | bowl wall, bezel to glass gap, bezel opening |
| `ORBIT_SHRINK` | 0 | pull the socket rim outline in (fraction) |
| `EYE_DZ` | 2 | eyes this far above the measured orbit centres |
| `STANDOFF_H`, `MODULE_T` | 3.0, 3.2 | **measure your modules**; they set the bar depth |
| `SHELL_T` | 2.6 | wall thickness |
| `WEB_CLOSE_R`, `BASE_CLOSE_R`, `TEMPLE_CLOSE_R`, `WEB_RECESS` | 7, 15, 22, 3.5 | how big a gap gets webbed, and how deep the web sits |
| `FOSSA_CLOSE_R`, `FOSSA_RECESS` | 30, 0 | temple fill (flush) |
| `SMOOTH_SIGMA`, `MC_SIGMA` | 1.5, 1.2 | smoothing of web and inner surfaces |
| `NASAL_RECESS`, `NASAL_T`, `NASAL_BOTTOM` | 6, 1.8, 0.72 | nose bowl depth, window thickness, window size |
| `JAW_OPEN_DEG`, `JAW_STOP_MARGIN`, `JAW_CLOSE_STOP`, `TEETH_GAP` | 18, 2, −0.5, 0.8 | jaw range and stops |
| `SERVO`, `SERVO_SIDE`, `HORN_FACE_X` | MG90S | servo dimensions and side |
| `Y_SPLIT`, `JOINTS`, `DOWELS` | auto (32.9) | cut plane and candidate joint positions |
| `RADAR`, `ESP32`, `TRAY`, `TRAY_POSTS`, `USB_SLOT`, `TIE_BAR` | | electronics and power cable |
| `BEHIND_EYES`, `CHOANA` | | interior sealing (keeps the face open from behind) |
| `NECK`, `STAND` | M5 | neck insert and stand size |
| `FIT` | 0.75 | clearance round dropped-in parts |

## Compromises

- **Scale is 0.932×, not ~0.89×.** Measured at the rim crest as described
  above, the source orbit centres are 59 mm apart, not 62. The skull is
  therefore close to life size (134 × 184 × 162 mm).
- **Eye depth is 15 mm, not deeper.** The skull narrows behind the orbits,
  and at 16 mm and deeper the eye hardware would break through the wall
  behind the lower outer orbit.
- **The modules are still rotated 90° and need a firmware rotation.**
  Unrotated, the outer M2 screws would come through the temple wall.
- **The temples are filled flush and the arches are webbed**, so the
  zygomatic arches read in relief rather than as free bars. This is closer to
  a prop skull than to real anatomy.
- **The servo cup and the jaw-pivot boss show from below.** They hang 10–15 mm
  under the skull base between the jaw rami. The tip of the servo horn shows
  just behind the ramus.
- **Some surfaces show faint faceting.** The underside webs and parts of the
  temple fill are marching cubes, smoothed, at 1 mm. The bowls are exact.
- The jaw is a pure hinge about the condyle axis; a real jaw also slides
  forward.
- **The module stack is estimated.** `STANDOFF_H` and `MODULE_T` are
  estimates from photos. If your modules differ, change them and rebuild.
- A few pinch edges (where two surfaces touch at a line) are filled with
  1 mm blobs so every STL is strictly watertight.
