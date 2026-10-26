# Printable skull

An animatronic skull built from Peter from Belgium's CC0 anatomical skull
(Printables 2770). It prints in three skull parts, plus the jaw, the stand
and two small brackets:

- **chassis**: face, orbits, cranial floor, hinge and neck;
- **back cover**: behind the eyes, above the floor;
- **cap**: the calvaria.

Every electronic part and the jaw mount on the chassis.
- **Taking the back cover off** opens the space right behind the eye bar
  horizontally.
- **Taking the cap off** opens the whole top.
- The covers hook or sit on lips and take **one screw each**.

Everything comes from `build.py` and is reproducible.

![front](skull_front.png)

| Preview | |
|---|---|
| `skull_front.png`, `skull_iso.png`, `skull_side.png` | assembled, on the stand; sockets/nose drawn painted black, screens gold |
| `skull_jaw_open.png` | jaw at the full 18° opening |
| `skull_exploded.png` | parts pulled apart in assembly order |
| `skull_bottom.png` | underside (servo cup, pivot boss, neck boss) |
| `skull_chassis_from_behind.png`, `skull_chassis_from_behind_34.png` | the chassis with both covers off, from behind: eye bar fitted, the eye screws' tool paths (blue) and the hand space round the screwdriver handle (orange) |
| `skull_chassis_from_above.png` | the same from above with the electronics fitted, and the tool paths for the screws driven from the top |
| `skull_chassis_34_hw.png` | the chassis with everything fitted, covers off |
| `skull_covers.png` | the back cover and the cap (cap lifted 60 mm) |
| `skull_cover_joints.png` | sections through the cover joints: cap hook under the forehead ledge; the back cover screw and the cap screw; the floor lip |
| `out/closeup_back_cover_screw.png`, `out/closeup_cap_screw.png` | sections through the two cover screws: screw (red), head, insert (gold) in its bore |
| `out/closeup_jaw_horn_pad.png`, `out/closeup_jaw_pivot.png` | sections through the jaw attachments: servo-side pad and horn screws, pivot pad and bolt |
| `skull_stand_cable.png` | USB cable path: neck bore, then the stand column and its open slot |
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
   - **Assembly paths, tool access and cover fitting** are checked too (see
     *Tool access* below).
   - **Fasteners** (every screw, assembled): the head seat is found where
     the head first touches the clamped part and must bear on a flat ring;
     the clearance hole is empty from the seat to the joint face; an insert
     has an empty Ø4.0 × 6.7 bore from the joint face with at least 1.6 mm
     of wall round it; the tip has room past the bore; and the screw
     engages at least 4 mm of insert (self-tapping screws must pass right
     through a thin part). See *Fasteners*.
   - The current build reports no collisions, a clear jaw sweep, and stops
     that engage 1.5° past each end.

## Size

Assembled skull: **134 W × 184 L × 162 H mm** (cranium), about 205 mm tall
with the jaw. The stand adds 78 mm.

## Parts

| STL (`out/`) | Size (mm, x × y × z) | Volume | Print orientation | Supports | Time (rough) |
|---|---|---|---|---|---|
| `face.stl` (chassis) | 115 × 171 × 95 | 134 cm³ | upright, as in the skull | yes: under the cranial floor, inside the socket bowls (their tops), under the posts, tray hooks and pivot boss | ~7 h |
| `back.stl` (back cover) | 134 × 124 × 50 | 40 cm³ | lower cut (z = −14) on the bed | none to little | ~2 h |
| `cap.stl` | 134 × 172 × 74 | 95 cm³ | cut face on the bed, crown up | under the front hook only | ~4 h |
| `jaw.stl` | 99 × 97 × 72 | 51 cm³ | upright | tree under the lower border and the two hinge pads | ~2 h |
| `stand.stl` | Ø110 × 88 | 114 cm³ | base on the bed | none (the cable slot is open) | ~3 h |
| `tray.stl` | 86 × 35 × 24 | 13 cm³ | plate on the bed, cradle up | none | 30 min |
| `servo_bracket.stl` | 40 × 18 × 27 | 2.4 cm³ | mounting plate on the bed | none | 15 min |

Times are estimates for a Bambu H2D with PLA at 0.2 mm (about 10 mm³/s
average plus support overhead). Check them in Bambu Studio. Everything fits
the H2D bed.

- The chassis has two cut faces at right angles (behind the eyes, and the
  floor), so it can't lie on a cut. Upright needs supports under the base
  and inside the upper half of each socket bowl.
- The back cover and the cap print on their flat cuts.

**Settings:** PLA (PETG if it will sit in sun or heat). 0.2 mm layers;
0.16 mm on the face for the teeth if you like. 4 walls, 25 % gyroid. Tree
supports (auto), threshold 30°. The chassis needs supports *everywhere*,
because the bowls are inside. Brim on the jaw.
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
  - The bar plate is ±10.4 mm tall with its lower outer corners chamfered
    by 1 mm. That corner of the skull is the tightest spot. (A 4 mm chamfer
    cut through the lower M2 holes; the heads only bore on about half their
    ring.)
- Behind the bowls, everything is cleared with 0.75 mm round it: the
  modules, the bar, the M2 heads, the connectors and their cables (a 16 mm
  channel behind each window), and screwdriver access to the bar bolts.
- The bar back face is at Y = 26.85, 5 mm in front of the back cut.
  - The bar bolt and the four M2 module screws are driven straight from
    behind, through the back opening.
  - There is a 60 × 40 mm hand space round the screwdriver handle, from 60 mm
    behind the screw.
- **Fitting the bar:** with both LCDs and their cables attached, it comes in
  through the back opening. It moves 12 mm forward onto the posts
  (`EYE_BAR_BACKOFF`), and before that can come straight down from the top.
  The path is checked clear of the chassis.
- **One bolt.** The left post has an M3 insert. The right post has a printed
  Ø3 key peg that sits in the bar's other slot, so the bar can't rotate.
  - The slots are Ø3.6 with 3 mm vertical travel, so you can still centre the
    screens in the bezels.
  - There is no centre post. That keeps the slot between the bowls free for
    the radar to go in.

### Jaw: direct drive
- The hinge axis is the condyle axis (Y = 65.1, Z = −29.4 in the eye frame), parallel to X.
- **The face part is the chassis.** The servo cup, the servo-bracket bosses
  and the jaw pivot boss are all part of the face. The jaw hangs from the
  chassis.
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
- The horn (single or double arm, pointing down the ramus) is screwed to the
  spline on the bench.
  - The jaw then fixes to the horn with two M2×16 self-tapping screws from
    **outside** the ramus. They go through Ø2.2 pilots at 10 and 14 mm from
    the axis along the horn arm, which points 20° forward of straight down,
    along the condyle neck (`HORN_ARM_DEG`). The heads sit on a shallow Ø6
    spot face on the ramus; each screw reaches 4–6 mm past the horn arm.
  - Screwing from outside is the only straight tool path once the jaw is
    on.
- **Pads.** Each condyle neck carries a pad on its inside, grown out of the
  bone: inside the pad outline the ramus is filled solid from the pad face to
  0.8 mm under the outer surface, with a 3 mm fillet where the pad meets the
  ramus (`jaw_pads()`).
  - Servo side: the hull of a Ø24 disc on the axis and an Ø11 lobe round the
    far horn screw, 8 mm thick from the horn face (was a Ø24 × 8 disc that
    the r = 14 screw sat outside of).
  - Pivot side: a Ø22 disc, 8 mm thick (was Ø16 × 8), plus a Ø15 boss on the
    axis out to |x| = 48.5 that is kept above the condyle trim. It leaves
    4.2 mm of wall round the Ø6.6 head counterbore and 5.7 mm of material
    over the bolt (the trim used to leave a 1.7 mm bridge there).
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

### Chassis, back cover and cap
- **Cap cut:** the plane z = 32 − 0.04·(y + 5) (`SEAM`). That is just above
  the brow at the front and about 26 mm up at the back of the head.
- **Back cut:** y = 32 (`Y_BACK`, 5 mm behind the eye bar) from the cap cut
  down to z = −14 (`Z_FLOOR`). From there the cut runs horizontally back to
  the back of the head.
- **Chassis** (below the cap cut, and in front of y = 32 or below z = −14):
  - the face, socket bowls, nose and radar;
  - the cranial floor with the hinge, servo cup and jaw pivot;
  - the ESP32 tray posts and the hollow neck.
- **Back cover:** the band of skull wall behind the eyes, from the floor cut
  up to the cap. It carries nothing.
- **Cap:** the calvaria. It carries nothing.
- With both covers off, nothing stands between the eye bar and the back of
  the head, and the top is open.

**Cover joints (no brackets):**
- **Back cover:**
  - It drops straight down onto the chassis floor.
  - Its lower edge goes outside a 5 mm lip on the chassis (0.5 mm
    clearance, 1.5 mm lead-in step). The lip is trimmed wherever the cover
    would brush it on the way down.
  - One M3×12 from behind, low at the back of the head (z = −9), goes
    through the cover into an insert post on the chassis.
  - The back of the head overhangs there, and the cover drops straight
    down, so the post face (y ≈ 139.5) must stay in front of all cover wall
    below it. The cover therefore has a Ø10 pad out to the post face (0.5 mm
    gap), and the slanted outside gets a Ø6.5 spot face so the head sits
    flat.
- **Cap:**
  - A hook on its front edge (bridge, stem and foot, 20 mm wide, 0.5 mm
    clearances) goes under a ledge on the chassis forehead.
  - Fitting: lower the cap 6.5 mm behind its place, then slide it forward
    along the cut; the foot slides under the ledge.
  - One M3×12 from behind, high at the back of the head, goes through the
    cap into an insert boss on the back cover. The boss reaches up across the
    cap cut to the screw axis (6 mm above it), with a flat face square to the
    screw about 1 mm inside the cap wall. The back cover is then trapped
    under the cap, and screwed to the chassis at its bottom.
- **Checked:**
  - The back cover drops in with everything fitted.
  - The cap's lower-back-then-slide-forward path is clear.
  - Nothing collides when fitted.

### Tool access (checked by the build; it fails on any problem)
- **Tool path.** For every screw, the build sweeps a straight tool along the
  screw axis outward from the head:
  - Ø8 × 100 mm, which is a driver shaft plus a hand;
  - Ø5.5 for the first 8 mm past any counterbore, which is the bit.

  The tool must not touch any part fitted at that point in the assembly
  order. Parts fitted later don't count.
- **Opening.** The tool must also leave through the opening that is meant to
  be open at that step:
  - `back` for the eye screws;
  - `top` for the tray and servo-bracket bolts;
  - `outside` for the jaw, cover and stand screws.

  The opening is where the tool path leaves the skull, or the last part
  region it is in.
- **Hand space.** The eye-bar bolt also needs a 60 × 40 × 50 mm empty hand
  space round the handle, from 60 mm behind the screw.
- **Result in this build:** all 17 screws OK (tool access and the fastener check), and the hand space is clear.
  The eye-bar insertion path and the radar path (on edge up the slot between
  the bowls) are clear too.

### Electronics
- **ESP32-DevKitC-VIE** (no mounting holes) sits on a separate flat tray.
  - The tray slides forward under two hook posts and is held by one M3×8
    from above at the back right.
  - The board lies flat with its pins down, on two end ledges 16 mm up, so
    the DuPont housings fit underneath. A zip-tie slot pair holds it. The USB
    end points to +X.
- **Power:** by USB cable from outside (a power bank or the laptop). There is
  no internal battery.
  - The cable goes down the hollow neck (Ø14 bore, passes a USB-A plug), into
    the stand column, and out at the base.
  - A zip-tie arch on the chassis floor behind the neck (y = 114) gives
    strain relief.
- **HLK-LD2410C** (35 × 7 mm, no screws) lies horizontal and faces forward
  behind the **1.8 mm nasal window**: the flat bottom of the nose bowl, 6 mm
  behind the piriform rim.
  - It sits in a frame pocket (0.6 mm clearance), open at the back for the
    header and cable.
  - It goes in on edge down the slot between the bowls, then turns flat and
    slides forward.
  - Fix it with a dab of hot glue or tape. Antenna side to the window.

### Stand
- The neck boss is a Ø30 tube under the foramen magnum (Y = 90) with a Ø14
  bore into the skull.
  - It drops into a 10 mm socket on top of the stand column (0.4 mm
    clearance).
  - One M3×8 from behind (+Y) goes through the socket wall into an insert
    in the neck.
- The column is Ø38 with an Ø18 bore. An **open 8 mm slot** runs down its
  whole length (toward −X) and across the base, so the USB cable drops in
  sideways; no threading past the neck.

## Fasteners

**17 screws** in total, down from 27 in the previous (bracketed) layout, and
**8 M3 inserts**, down from 17 plus one M5.

| Item | Qty | Where |
|---|---|---|
| M3 heat-set insert (5.7 long; Ø4.0 × 6.7 pilot bore, Ø3.2 relief past it) | 8 | eye-bar post, 2 servo-bracket bosses, tray post, jaw pivot boss, back-cover post (chassis), cap boss (back cover), neck |
| M3×12 | 3 | eye bar (+ Ø9 M3 washer, DIN 9021, over the slot), back cover, cap |
| M3×20 | 1 | jaw pivot (+ M3 washer) |
| M3×8 | 4 | 2 servo bracket, 1 tray, stand (an M3×12 there would reach into the cable bore) |
| M2×8 | 4 | LCD modules to the eye bar |
| M2×16 self-tapping | 2 | jaw to horn arm, from outside the ramus |
| servo tab screws (supplied) | 2 | servo to bracket |
| horn screw (supplied) | 1 | horn to spline |

What changed:

| Joint | Before | Now |
|---|---|---|
| Joint brackets | 8 screws | gone; replaced by hooks/lips + 2 screws |
| Eye bar | 2 bolts | 1 bolt + a key peg |
| Tray | 4 bolts | 2 hooks + 1 bolt |
| Stand | M5 bolt | M3 radial screw |

The jaw and servo load path keeps its screws.

## Assembly

Everything goes onto the chassis. The back cover and then the cap go on last.

1. **Bench:**
   - Heat-set the inserts.
   - Screw the servo into its bracket (tab screws). Centre it and screw the
     horn on, pointing down the ramus.
2. **Eyes** (both covers off, chassis on the bench):
   - Plug the cables into the LCDs.
   - Bring the eye bar in from behind and push it onto the left post and the
     right key peg.
   - Screw the M2×8s and the M3×12 bar bolt (with a Ø9 washer) straight from
     behind. Centre the screens.
3. **Radar:** on edge down the slot between the bowls, then flat and forward
   into its frame.
4. **ESP32** (from above): slide the tray forward under the two hooks, fit
   one M3×8, then clip the board in.
5. **Servo and jaw:**
   - Lower the servo and bracket into the cup, with the gear tower down the
     slot in the cup wall. Bolt the flange (2× M3×8 from above).
   - Fix the jaw to the horn with 2× M2×16 from outside the ramus.
   - Put the M3×20 pivot bolt (with a washer) through the other condyle.
   - Wire everything and test on the bench.
6. **Back cover:** drop it onto the floor lip, then fit 1× M3×12 from behind,
   low.
7. **Cap:**
   - Lower it 6 mm behind its place and slide it forward under the forehead
     ledge.
   - Fit 1× M3×12 from behind, high.
8. **Stand:**
   - Feed the cable down the neck bore and lay it in the column slot.
   - Push the stand's socket onto the neck.
   - Fit 1× M3×8 from behind.

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
| `SEAM`, `Y_BACK`, `Z_FLOOR` | z = 32 − 0.04(y + 5), 32, −14 | the cuts |
| `LIP`, `CAP_HOOK` | 5 mm / 0.5 gap; 20 mm, 6 mm slide | cover joints |
| `BAR_BOLTS` | [0] | which eye-bar hole gets the bolt (the other gets a key peg) |
| `EYE_BAR_BACKOFF`, `TOOL_D`, `TOOL_TIP_D`, `TOOL_TIP_L`, `TOOL_LEN` | 12, 8, 5.5, 8, 100 | insertion and tool-access checks |
| `RADAR`, `ESP32`, `TRAY`, `TRAY_POSTS`, `TRAY_HOOKS`, `TIE_BAR` | | electronics |
| `BEHIND_EYES`, `CHOANA` | | interior sealing (keeps the face open from behind) |
| `NECK`, `STAND` | | hollow neck, socket, column bore and cable slot |
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
- **The cuts show** as a line across the forehead and round the head just
  above the brows (cap), and a ring behind the temples and round the back of
  the head (back cover). Paint or fill them.
- **The chassis needs supports**, including inside the socket bowls, because
  it has two cut faces at right angles and can't lie on a cut.
- **The back cover's lower edge is located by the floor lip only on the
  inside.** It is held down by the cap and screwed at the back. Its front
  edges against the temples are not interlocked.
- **The tool check relaxes Ø8 to Ø5.5 for the first 8 mm past the head**
  (the bit). Without that, the servo tab screw next to the gear tower fails
  on the servo's own body.
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
