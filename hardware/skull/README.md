# Printable skull

An animatronic skull built from Peter from Belgium's CC0 anatomical skull
(Printables 2770). It has a face that is also the chassis, a back cover, a
servo-driven jaw, an electronics tray and a stand. Every electronic part and
the jaw mount on the face; the cover goes on last. Everything comes from `build.py` and is
reproducible.

![front](skull_front.png)

| Preview | |
|---|---|
| `skull_front.png`, `skull_iso.png`, `skull_side.png` | assembled, on the stand; sockets/nose drawn painted black, screens gold |
| `skull_jaw_open.png` | jaw at the full 18° opening |
| `skull_exploded.png` | parts pulled apart in assembly order: eye bar, radar, servo, tray, joint brackets, cover; jaw and stand below |
| `skull_bottom.png` | underside (servo cup, pivot boss, neck boss, USB slot) |
| `skull_face_from_behind.png`, `skull_face_from_behind_34.png` | the face part from behind: open, nothing between you and the eye/radar mounts |
| `skull_face_from_behind_hw.png` | the same with the eye bar, modules, radar and joint brackets in place |
| `skull_face_from_behind_hw_34.png` | the face from behind at 3/4, with the jaw, servo, ESP32 tray, eye bar and radar fitted |
| `skull_back_from_front.png`, `skull_back_from_front_34.png` | the back cover seen through its cut (USB notch at the bottom) |
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
     material, including screwdriver access to the two bar bolts. That path
     also must not leave the skull. The joint bosses and dowel bosses are
     placed outside it. The current build reports no collisions, a clear
   sweep, and stops that engage 1.5° past each end.

## Size

Assembled skull: **134 W × 184 L × 162 H mm** (cranium), about 205 mm tall
with the jaw. The stand adds 78 mm.

## Parts

| STL (`out/`) | Size as printed (mm) | Volume | Print orientation | Supports | Time (rough) |
|---|---|---|---|---|---|
| `face.stl` | 134 × 162 × 136 | 211 cm³ | cut face on the bed, face up | tree: socket and nose bowls, eye-bar post ends, tray posts, neck boss, pivot boss, servo-flange bosses, base underside | ~10 h |
| `back.stl` (cover) | 122 × 130 × 48 | 56 cm³ | cut face on the bed, crown up | none to little | ~2 h |
| `jaw.stl` | 99 × 97 × 69 | 49 cm³ | upright, as in the skull | tree under the lower border and the two hinge pads | ~2 h |
| `servo_bracket.stl` | 40 × 18 × 27 | 2.4 cm³ | mounting plate on the bed | none | 15 min |
| `tray.stl` | 72 × 35 × 24 | 12 cm³ | plate on the bed, cradle up | none | 30 min |
| `stand.stl` | Ø110 × 78 | 87 cm³ | base on the bed | none | ~2 h |
| `joint_bracket_*.stl` ×4 | about 8 × 19 × 24 | ~2 cm³ | as exported | small, under the arm | 10 min each |
| `dowel.stl` (print 2) | Ø4 × 13 | — | upright | none | 5 min |

Times are estimates for a Bambu H2D with PLA at 0.2 mm (about 10 mm³/s
average plus support overhead). Check them in Bambu Studio. Everything fits
the H2D bed. The face is the largest part at 134 × 162 × 136.

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
- The bar back face is at Y = 26.85. Both bar bolts face you from the open
  back of the face.
- Two posts on the inside of the face carry M3 inserts at (±27.5, +16). The
  bar's slots are Ø3.6 with 3 mm vertical travel, so you can centre the
  screens in the bezels.
  - There is no centre post. That keeps the slot between the bowls free for
    the radar to go in.

### Jaw: direct drive
- The hinge axis is the condyle axis (Y = 65.1, Z = −29.4 in the eye frame), parallel to X.
- **The face part is the chassis.** The servo cup, the servo-bracket bosses
  and the jaw pivot boss are all part of the face. The jaw hangs from the face
  assembly.
  - Jaw load path: jaw → horn and pivot bolt → servo bracket and pivot boss →
    the face's cranial base → the neck boss → the stand.
  - The face's cranial base is the skull's own base and sides, the stiffest
    part of the skull.
- An MG90S sits in a closed cup in the cranial floor on the +X side, its
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

### Face and cover
- **The cut is a coronal plane at Y = 108**, behind the foramen magnum and
  the neck boss.
  - The face (front of the cut) holds everything: eyes, radar, servo, jaw
    pivot, ESP32 tray, neck boss.
  - The back is only the occipital cap, a cover with no load and no
    electronics.
- **From behind, the face is open.** You see:
  - the socket bowl backs with their screen openings;
  - the two eye-bar posts;
  - the radar frame;
  - the servo cup and its bosses;
  - the jaw pivot boss;
  - the three tray posts and the neck boss;
  - four small joint bosses and two dowel bosses near the outer wall.

  Nothing bridges between the bowls.
- **Insertion paths** (checked by the build):
  - Eye bar with both modules and their plugged-in cables: straight back
    25 mm, lifted 20 mm over the servo bosses and tray posts, then out of the
    open back. It is clear of every fixed face feature and stays inside the
    skull.
  - Bar bolts: screwdriver access straight from behind.
  - Radar: slides straight back out of its frame to the choana wall. It then
    goes in or out on edge through an 8 mm slot between the bowls, which is
    clear all the way up past the eyes even with the bar fitted.
  - Cover: slides straight on along −Y with the jaw (closed), servo, tray,
    ESP32, eye bar, radar and joint brackets all in place. Checked over 60 mm
    of travel; nothing catches.
- There are 4 **bracket joints**, all with screws from the side. Two are high
  (z = +30) and two low (z = −5), 12 mm behind the cut.
  - The script picks each position from a short list. A position is accepted
    when:
    - the bracket, trimmed so the cover slides on without catching, still has
      solid material round its insert and its screw;
    - the face boss stays out of the insertion paths.
  - Each bracket is a separate L-part. Its flange sticks out sideways and
    bolts to a compact insert boss on the face with an M3×12 along Y.
  - An M3×12 goes from outside through a counterbored pad in the cover into
    an insert in the bracket. The counterbore leaves 3 mm under the head.
- **2 dowels** (printed, Ø4 in Ø5 holes) at the top of the seam help line it
  up.

### Electronics
- **ESP32-DevKitC-VIE** (no mounting holes) sits on a separate flat tray.
  - The tray bolts with 3× M3×8 onto three insert posts that rise from the
    cranial floor, over the foramen magnum, between the servo and the cut.
  - The board lies flat with its pins down, on two end ledges 16 mm up, so
    the DuPont housings fit underneath. A zip-tie slot pair holds it.
  - The USB end points to +X.
  - Everything is visible and reachable from the open back for bench testing.
- **Power:** from outside (a power bank or the laptop) through the USB cable.
  There is no internal battery.
  - The cover has an open **9 mm notch** in its front edge at floor level,
    x = +24, 14 mm deep. Lay the cable in it before sliding the cover on, so
    nothing needs threading.
  - A zip-tie arch on the face floor just in front of the cut (y = 100)
    gives strain relief.
- **HLK-LD2410C** (35 × 7 mm, no holes) lies horizontal and faces forward
  behind the **1.8 mm nasal window**: the flat bottom of the nose bowl, 6 mm
  behind the piriform rim.
  - It sits in a frame pocket (0.6 mm clearance), open at the back for the
    header and cable.
  - Fix it with a dab of hot glue or tape. Antenna side to the window.

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
| M3 heat-set insert (Ø4.1 × 5.7 hole) | 16 | 2 eye-bar posts, 4 face joint bosses, 4 joint brackets, 1 jaw pivot boss, 2 servo-bracket bosses, 3 tray posts |
| M5 heat-set insert | 1 | neck boss |
| M3×12 | 10 | 2 eye bar, 4 brackets to face, 4 cover to brackets |
| M3×20 | 1 | jaw pivot (+ M3 washer) |
| M3×8 | 5 | 2 servo bracket, 3 tray |
| M2×8 | 4 | modules to eye bar (existing stack) |
| M5×16 | 1 | stand to neck |
| servo tab screws (supplied) | 2 | servo to bracket (Ø1.8 pilots) |
| horn screws (supplied) | 1 + 2 | horn to spline; horn to jaw pad pilots |
| printed dowel | 2 | top of the seam |

## Assembly

Everything goes onto the face. The cover goes on last.

1. Heat-set all the inserts (the face's open back gives access to every
   boss).
2. **Face down on the bench, open back up:**
   - Fit the modules to the eye bar (M2×8, tips toward the nose) and plug in
     their cables.
   - Lower the bar in through the open back and bolt it to the two posts
     (M3×12 from behind). Centre the screens in the bezels.
   - Put the radar in its frame behind the nose window: on edge down the slot
     between the bowls, then turned flat and slid forward.
3. **Chassis:**
   - Screw the servo into its bracket. Lower it into the cup with the gear
     tower going down the slot in the cup wall. Bolt the flange (2× M3×8).
   - Bolt the tray with the ESP32 to its three posts (3× M3×8).
   - Wire everything and test on the bench with all of it visible.
4. **Jaw:**
   - Centre the servo at the closed angle and push the horn on, pointing down
     the ramus.
   - Offer up the jaw, screw the horn to the jaw pad, then put the M3×20 pivot
     bolt (with a washer) through the other condyle into the pivot boss.
5. Bolt the four joint brackets to the face bosses (M3×12 along Y).
6. **Cover:**
   - Put the dowels in.
   - Lay the USB cable through the tie arch.
   - Slide the cover on along −Y, with the cable dropping into its notch.
   - Fit the 4 M3×12 from the sides.
7. Bolt the skull onto the stand (M5×16 from inside the column).

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
| `Y_SPLIT`, `JOINTS`, `DOWELS` | 108 | cut plane (face = chassis / cover) and candidate joint positions |
| `RADAR`, `ESP32`, `TRAY`, `TRAY_POSTS`, `USB_NOTCH`, `TIE_BAR` | | electronics and power cable |
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
- **The face is a big print** (about 10 h, 134 × 162 × 136 mm) because it is
  also the chassis. The cover is small.
- **The jaw closes on the back teeth.** The model's incisors stay about 6 mm
  apart (an open bite in the source jaw); the molars are at 0.8 mm.
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
