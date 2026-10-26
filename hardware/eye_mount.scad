// eye_mount.scad -- flat bar holding two Waveshare 0.71" round LCD modules
// (GC9D01, 160x160) for the bone_eyes animatronic skull.
//
// Print orientation = as modelled: BACK face on the bed (z = 0), module side
// up. Everything rises from the bed or is a vertical through-cut, so no
// supports are needed.
//
// Coordinates: X along the bar (eye to eye), Y up in the skull, Z out of the
// skull's face. Each eye's screen centre is at (+/-eye_spacing/2, 0).
//
// mount_style = "skull" (default) is the version the printed skull uses
// (hardware/skull): a flat plate, modules turned 90 deg so the pointed tip / FPC
// faces the nose (module_rot), three oversized M3 slots that bolt from behind
// onto heat-set inserts in posts on the skull face. "inserts" is the original
// stand-alone bar (tip down, three M3 insert bosses).
//
// See README.md for where each number came from.

/* [Layout] */
eye_spacing      = 55.0;   // screen centre to screen centre (user)
mount_style      = "skull"; // "skull" or "inserts"
// module rotation about its screen centre, deg: 0 = pointed tip down (-Y).
// In "skull" style the tip points to the nose (+X eye turned -90, -X eye +90),
// so the picture must be rotated 90 deg in firmware (MADCTL).
module_rot       = (mount_style == "skull") ? 90 : 0;

/* [Module: Waveshare 0.71inch LCD Module dimension drawing] */
pcb_w            = 20.12;  // round PCB/glass diameter (drawing: 20.12 +/-0.15)
pcb_h            = 22.30;  // overall height incl. pointed tip (drawing: 22.30 +/-0.15)
tip_flat_w       = 7.34;   // flat at the tip, where the display FPC wraps (drawing: 7.34)
standoff_spacing = 15.75;  // M2 standoff centres (drawing: 15.75; user measured 15.45)
hole_to_tip      = 12.10;  // standoff axis to tip edge (drawing: 12.10)
standoff_od      = 3.82;   // brass standoff OD (drawing: 3.82)
conn_w           = 9.20;   // 8-pin SH1.0 vertical connector housing width (drawing: 9.20)
// Connector housing Y span below the standoff axis. Scaled from the drawing
// photo (not dimensioned), so the window below is generous.
conn_y_top       = 2.6;
conn_y_bot       = 7.7;
standoff_h       = 3.0;    // standoff height above PCB back. NOT on the drawing:
                           // estimated from photos -- measure yours and set it.

/* [Screw stack] */
screw_len        = 8.0;    // M2 x 8
screw_exposed    = 5.65;   // screw left outside the standoff (user) ...
screw_t          = screw_exposed; // ... so material under the head = 5.65
plate_t          = 5.65;   // bar thickness elsewhere; if > screw_t a counterbore
                           // from the back brings the screw seats back to screw_t
m2_clear_d       = 2.2;    // nominal M2 clearance (spec 2.2-2.4)
hole_comp        = 0.1;    // added to printed hole diameters (shrinkage)
m2_head_d        = 4.2;    // counterbore diameter (M2 socket head 3.8)

/* [Locating rim] */
// The rim proved too tight in practice; the two M2 screws locate the module.
rim_enable       = false;
fit_clear        = 0.5;    // PCB outline clearance (only used if rim_enable)
rim_wall         = 1.6;    // >= 1.2 min wall
rim_engage       = 0.8;    // how far the rim rises past the PCB back face
rim_h            = standoff_h + rim_engage; // rim height above bar front face
fpc_notch_w      = 9.0;    // gap in rim at the tip for the folded display FPC
relief_d         = 0.6;    // shallow relief under PCB back-side parts
seat_d           = 5.2;    // un-relieved seat around each standoff (> standoff_od)

/* [Cable window] */
win_margin       = 1.2;    // around the connector housing (plug is ~10 wide)
win_r            = 1.0;    // corner radius

/* [Bar + attachment] */
bar_h            = 14.0;   // height of the bar between/beyond the eyes
end_boss_x       = 44.0;   // X of the end insert bosses (+/-)
insert_bosses    = [[-44, 0], [0, 0], [44, 0]]; // M3 heat-set boss centres
insert_d         = 4.1;    // M3 heat-set insert hole (4.0-4.2)
insert_depth     = 5.7;    // 5-6
insert_boss_od   = 9.0;
insert_boss_h    = 9.0;    // total height from bed; floor = h - depth
m3_clear_d       = 3.2;    // bolt from the back into the insert (+ hole_comp)
adjust_slots     = [[-9, 0], [9, 0]]; // M3 through-slots, long axis along Y
slot_len         = 6.0;    // travel (centre-to-centre of slot ends)
slot_w           = 3.2;    // + hole_comp

/* [Skull plate (mount_style = "skull")] */
skull_plate_half_h = 10.4; // plate half height round the eyes (M2 heads at +-7.9)
skull_plate_lat    = 4.0;  // plate edge outside the standoff line
skull_plate_r      = 4.0;  // corner radius
skull_plate_chamfer = 1.0; // extra chamfer on the lower outer corners
// M3 mounting slots: bolt from the back face into inserts on the skull posts
skull_mount_holes  = [[-27.5, 16], [27.5, 16]]; // no centre hole: keeps the space behind the nose free
skull_mount_boss_d = 9.0;
skull_slot_w       = 3.6;  // oversized for M3 (loose fit)
skull_slot_len     = 3.0;  // vertical travel

/* [Print] */
chamfer          = 0.5;    // bottom-edge chamfer (elephant foot)
chamfer_steps    = 5;
$fn              = 96;

// ---------------------------------------------------------------- derived
pcb_r      = pcb_w / 2;
tip_y      = -(pcb_h - pcb_r);          // tip edge relative to screen centre (-12.24)
hole_dy    = tip_y + hole_to_tip;       // standoff axis relative to screen centre (-0.14)
eye_xs     = [-eye_spacing/2, eye_spacing/2];
// rotation of each eye's module frame; tips point at the nose when module_rot = 90
function eye_rot(x) = (x > 0) ? -module_rot : module_rot;
cb_depth   = max(0, plate_t - screw_t);

if (rim_enable) assert(rim_wall >= 1.2, "rim_wall below 1.2 mm minimum wall");
assert(insert_boss_h - insert_depth >= 1.2, "insert floor too thin");
// wall between an M2 hole and the nearest cable-window corner
win_dx = standoff_spacing/2 - (conn_w/2 + win_margin);
win_dy = conn_y_top - win_margin;
win_wall = (win_dy <= 0 ? win_dx : sqrt(pow(max(win_dx,0),2) + pow(win_dy,2)))
           - (m2_clear_d + hole_comp)/2;
assert(win_wall >= 1.2, str("cable window too close to M2 hole: ", win_wall));

// polygon hole with its flats on the nominal diameter + shrink comp
module hole2d(d) { circle(d = (d + hole_comp) / cos(180 / $fn)); }

module pcb2d() {
    hull() {
        circle(r = pcb_r);
        translate([-tip_flat_w/2, tip_y]) square([tip_flat_w, 0.01]);
    }
}

module eye_outer2d() { offset(r = fit_clear + rim_wall) pcb2d(); }

module window2d() {
    w = conn_w + 2*win_margin;
    y0 = hole_dy - conn_y_bot - win_margin;
    y1 = hole_dy - conn_y_top + win_margin;
    translate([0, (y0+y1)/2])
        offset(r = win_r) square([w - 2*win_r, (y1-y0) - 2*win_r], center = true);
}

module slot2d() {
    hull() for (s = [-1, 1]) translate([0, s*slot_len/2]) hole2d(slot_w);
}

module outline2d() {
    if (mount_style == "skull") {
        xo = eye_spacing/2 + abs(hole_dy) + skull_plate_lat;
        union() {
            // rounded rectangle with the two lower outer corners chamfered (the skull is tight there)
            hull() for (sx = [-1, 1]) {
                cx = xo - skull_plate_r; cy = skull_plate_half_h - skull_plate_r;
                translate([sx*cx, cy]) circle(r = skull_plate_r);
                translate([sx*(cx - skull_plate_chamfer), -cy]) circle(r = skull_plate_r);
                translate([sx*cx, -cy + skull_plate_chamfer]) circle(r = skull_plate_r);
            }
            for (p = skull_mount_holes) hull() {
                translate(p) circle(d = skull_mount_boss_d + skull_slot_len);
                translate([p[0], 0]) circle(d = skull_mount_boss_d);
            }
        }
    } else union() {
        hull() for (s = [-1, 1]) translate([s*end_boss_x, 0]) circle(d = bar_h);
        for (x = eye_xs) translate([x, 0]) eye_outer2d();
        for (p = insert_bosses) translate(p) circle(d = insert_boss_od);
    }
}

// M2 screw holes (cut after the chamfer so the head seat stays a full flat annulus)
module m2_holes2d() {
    for (x = eye_xs) translate([x, 0]) rotate(eye_rot(x))
        for (s = [-1, 1]) translate([s*standoff_spacing/2, hole_dy]) hole2d(m2_clear_d);
}

// vertical through-cuts that get the bed-side chamfer
module cuts2d() {
    for (x = eye_xs) translate([x, 0]) rotate(eye_rot(x)) window2d();
    if (mount_style == "skull") {
        for (p = skull_mount_holes) hull() for (s = [-1, 1])
            translate([p[0], p[1] + s*skull_slot_len/2]) hole2d(skull_slot_w);
    } else {
        for (p = insert_bosses) translate(p) hole2d(m3_clear_d);
        for (p = adjust_slots) translate(p) slot2d();
    }
}

module plate2d() { difference() { outline2d(); cuts2d(); } }

// extrude with a stepped 45-degree chamfer on the bed-side edges (outer and holes)
module chamfered_extrude(h) {
    dz = chamfer / chamfer_steps;
    for (i = [0 : chamfer_steps - 1])
        translate([0, 0, i*dz])
            linear_extrude(dz + 0.001) offset(delta = -(chamfer - i*dz)) children();
    translate([0, 0, chamfer]) linear_extrude(h - chamfer) children();
}

module eye_mount() {
    difference() {
        union() {
            chamfered_extrude(plate_t) plate2d();
            // locating rims (off by default)
            if (rim_enable) for (x = eye_xs) translate([x, 0, plate_t - 0.01]) rotate(eye_rot(x))
                linear_extrude(rim_h + 0.01) difference() {
                    eye_outer2d();
                    offset(r = fit_clear) pcb2d();
                    translate([-fpc_notch_w/2, tip_y - 5]) square([fpc_notch_w, 5 + 2]);
                }
            // heat-set insert bosses
            if (mount_style != "skull") for (p = insert_bosses) translate([p[0], p[1], plate_t - 0.01])
                cylinder(d = insert_boss_od, h = insert_boss_h - plate_t + 0.01);
        }
        // insert holes from the top, with a small lead-in
        if (mount_style != "skull") for (p = insert_bosses) translate([p[0], p[1], insert_boss_h - insert_depth]) {
            cylinder(d = insert_d, h = insert_depth + 1);
            translate([0, 0, insert_depth - 0.5]) cylinder(d1 = insert_d, d2 = insert_d + 1.0, h = 0.501);
        }
        // M2 screw holes
        translate([0, 0, -1]) linear_extrude(plate_t + 2) m2_holes2d();
        // M3 clearance continues through the boss
        if (mount_style != "skull") for (p = insert_bosses) translate([p[0], p[1], -1])
            linear_extrude(insert_boss_h + 2) hole2d(m3_clear_d);
        // relief pocket under the PCB, leaving full-height seats at the standoffs
        if (relief_d > 0) for (x = eye_xs) translate([x, 0, plate_t - relief_d]) rotate(eye_rot(x))
            linear_extrude(relief_d + 0.01) difference() {
                offset(delta = -0.5) pcb2d();
                for (s = [-1, 1]) translate([s*standoff_spacing/2, hole_dy]) circle(d = seat_d);
            }
        // optional counterbores (only when plate_t > screw_t)
        if (cb_depth > 0) for (x = eye_xs, s = [-1, 1])
            translate([x, 0, -1]) rotate(eye_rot(x)) translate([s*standoff_spacing/2, hole_dy, 0])
                linear_extrude(cb_depth + 1) hole2d(m2_head_d);
    }
}

eye_mount();

echo(str("hole axis rel. screen centre = ", hole_dy, " mm; tip at ", tip_y));
echo(str("screw seat thickness = ", plate_t - cb_depth, " mm; counterbore depth = ", cb_depth));
echo(str("thread engagement = ", screw_len - (plate_t - cb_depth), " mm"));
echo(str("min wall M2 hole to cable window = ", win_wall, " mm"));
echo(str("insert floor = ", insert_boss_h - insert_depth, " mm"));
