# Handoff: fastener fixes, fastener check, jaw pads

## Done

- **Back cover -> chassis (M3x12, low at the back).** The post's insert bore
  was cut before the floor lip and post were added to the chassis, so the post
  came out solid. Now the post is added after the lip trim and its bore is cut
  last. The screw moved to z = -9 and stays horizontal (+Y). The back of the
  head overhangs there and the cover drops straight down, so the post face
  sits in front of all cover wall below it (y ~ 139.5). The cover has a Ø10 pad
  out to the post face, and a Ø6.5 spot face on its slanted outside so the head
  sits flat.
- **Cap -> back cover (M3x12, high at the back).** The boss was built as two
  blocks that only touched face to face. They came out as two bodies, and
  `clean()` dropped the upper one, which is the one on the screw axis. The
  blocks now overlap. The upper block is clipped 0.6 mm inside the cap wall
  and has a flat face square to the screw. The cap hole has a spot face too.
- **Every insert** uses `insert_bore()`: a Ø4.0 bore, INSERT_L + 1 = 6.7 mm
  deep, opening on the joint face, then a Ø3.2 relief. The neck has no relief,
  because the cable bore is behind it.
- **Stand screw** is now M3x8. An M3x12 reached into the cable bore.
- **Eye-bar bolt** needs a Ø9 M3 washer (DIN 9021). A bare head, or a Ø7
  washer, only bears on the sides of the 3.7 x 6.7 adjustment slot.
- **`hardware/eye_mount.scad`: `skull_plate_chamfer` 4 -> 1** (`BAR_PLATE`
  chamfer in build.py to match), and `eye_mount.stl` was re-exported. The 4 mm
  chamfer on the lower outer corners cut through the two lower M2 module-screw
  holes, so their heads bore on only about half of their ring. With 1 mm the
  seats are full. The pierce, collision and corridor checks still pass.
- **Jaw pads** (`jaw_pads()`): the servo-side pad is the hull of a Ø24 disc
  and an Ø11 lobe round the far horn screw. The pivot pad is Ø22, with a Ø15
  boss round the bolt head that is kept above the condyle trim. Both are grown
  out of the ramus with a 3 mm fillet. The horn screws are now at 10 and 14
  only, along an arm 20° forward of straight down, with Ø2.2 pilots and Ø6
  spot faces. See README, Mechanism > Jaw.
- **New check** `fastener_check()`, which runs in `verify()`, covers all 17
  screws. It checks the head seat, the clearance hole, the insert bore, the
  wall round the bore, the tip room and the engagement. Any failure fails the
  build.
- Close-ups are in `out/closeup_*.png`.

## Left / not fixed

- The ESP32/USB cable layout was handed to another agent. I didn't touch it.
  I did find that the tray plate covers the neck bore. Only about 2 mm
  separates the neck top (z = -12) and the tray underside (z = -10), so with
  the current layout the cable cannot reach the neck without a hole in the
  tray. Also, a U-turn of the plug and cable (30 mm + R15) has no room beyond
  the +X board end: the wall is about 3 mm past the plug.
- The horn screws reach 4–6 mm past the horn arm (the M2x16 is longer than the
  ramus there needs). The tips are clear of the servo case. M2x12 would
  only just get through the arm at r = 14.
- The servo tab screws' length is an assumption (8 mm, supplied screws).
  The horn screw is supplied and not modelled, so it only gets the tool-access
  check.
- The shell-stage cache I used for iterating was a scratch wrapper. It is not
  in the repo.
- The servo-side pad's Ø7 axis hole is for horn-screw access. The condyle
  trim at +3.5 mm opens it at the top edge. This was already the case before
  this change, and I left it.
- `verify()` now takes about 7 minutes (the whole build is about 9.5 min with
  renders). Most of that time goes to the volume booleans of the existing
  checks and the new fastener check on the full-size shells.
