"""Printed replacement for the MG90S single-arm horn that drives the jaw.

Run:     hardware/.venv/bin/python hardware/skull/horn/make_horn.py [--check]
Outputs: hardware/skull/horn/out/horn_b44.stl .. horn_b47.stl (one per bore),
         hardware/skull/horn/out/horn_plate.stl (all four, 10 mm apart)

The horn takes the stock horn's place exactly: its outer face (the bed face in
print) is the jaw pad face at |x| = HORN_FACE_X, its blind bore bottoms on the
spline top (1.0 mm under that face), and the arm points along horn_dir() with
the two M2x16 self-tapping pilots at HORN_JAW_HOLES from the axis.

Print frame: X along the arm (hub at the origin), Y across it, Z up from the bed
(Z = depth from the jaw pad face toward the servo). The STLs are in this frame.

--check also places the horn in the assembled pose and checks it against the
jaw (fixed to it), and over the jaw sweep against the servo, the servo bracket
and the chassis (face), using the cached render meshes (hardware/skull/cache).
"""
import os, sys
import numpy as np
import trimesh
import manifold3d as mf

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, SK)
import build as B            # noqa: E402  constants and helpers only (importing does not build)
import printability          # noqa: E402

OUT = os.path.join(HERE, 'out')

# ---- geometry (mm) ----------------------------------------------------------
BORES = (4.4, 4.5, 4.6, 4.7)     # press-fit bore variants (spline ~Ø4.8 in B.SERVO model: r 2.4)
FLOOR = 1.0                       # spline top to the pad face: (HORN_FACE_X) - (spline top) in build.servo_frame
HUB_T = 3.2                       # = B.HORN_T: hub bottom 0.2 above the modelled gear bump (u = spline_top - 2.4)
ARM_T = 3.2                       # arm thickness
SCREW_PAST_FACE = 3.2             # the M2x16 tips reach 3.2 past the pad face (out/build_report.json fastener_check: clamp 12.8)
HUB_R = 4.5                       # = the stock hub radius modelled in build.mechanism()
TIP_W = 7.0                       # arm width at the tip
TIP_C = 14.0                      # tip disc centre = outer pilot
PILOTS = B.HORN_JAW_HOLES         # (10, 14)
PILOT_D = 1.7                     # M2 self-tapping in PLA
SCREW_D = 2.5                     # horn-screw clearance (M2; drill 2.7 for an M2.5 screw)
CHAMFER = 0.3                     # bed-edge chamfer
BORE_LEAD = 0.3                   # lead-in chamfer at the bore mouth (top in print)
NOTCH_W, NOTCH_D, NOTCH_PITCH = 0.7, 0.7, 1.3   # bore markers on the tip end
PLATE_GAP = 10.0
SEG = 96


def _circle(r, c=(0.0, 0.0)):
    return mf.CrossSection.circle(r, SEG).translate(list(c))


def profile(off=0.0):
    return mf.CrossSection.batch_hull([_circle(HUB_R + off), _circle(TIP_W / 2 + off, (TIP_C, 0.0))])


def _cyl_z(r, z0, z1, c=(0.0, 0.0), r1=None):
    return mf.Manifold.cylinder(z1 - z0, r, r if r1 is None else r1, SEG).translate([c[0], c[1], z0])


def horn(bore, n_notch):
    T = max(HUB_T, ARM_T)
    body = mf.Manifold.extrude(profile(), T - CHAMFER).translate([0, 0, CHAMFER])
    cham = mf.Manifold.batch_hull([mf.Manifold.extrude(profile(-CHAMFER), 0.01),
                                   mf.Manifold.extrude(profile(), 0.01).translate([0, 0, CHAMFER])])
    H = body + cham
    cut = [_cyl_z(bore / 2, FLOOR, T + 1),                                     # blind press-fit bore
           _cyl_z(bore / 2, T - BORE_LEAD, T + 0.01, r1=bore / 2 + BORE_LEAD + 0.01),   # lead-in
           _cyl_z(SCREW_D / 2, -1, T + 1)]                                     # horn screw
    cut += [_cyl_z(PILOT_D / 2, -1, T + 1, (r, 0.0)) for r in PILOTS]
    # bore markers: n vertical slots in the round tip end, symmetric about the arm axis
    tip_x = TIP_C + TIP_W / 2
    for k in range(n_notch):
        y = (k - (n_notch - 1) / 2) * NOTCH_PITCH
        x_edge = TIP_C + np.sqrt((TIP_W / 2) ** 2 - y ** 2)
        cut.append(mf.Manifold.cube([tip_x + 1 - (x_edge - NOTCH_D), NOTCH_W, T + 2])
                   .translate([x_edge - NOTCH_D, y - NOTCH_W / 2, -1]))
    return H - B.union(cut)


def to_world(M, a=0.0):
    """Print frame -> assembled pose (jaw at sweep angle a)."""
    P = B.servo_frame(tuple(HINGE))
    u_face = B.SERVO['spline_top'] + FLOOR
    o = P(u_face, 0, 0)
    ex = P(u_face, -np.cos(np.radians(B.HORN_ARM_DEG)), -np.sin(np.radians(B.HORN_ARM_DEG))) - o
    ez = P(u_face - 1, 0, 0) - o
    ey = np.cross(ez, ex)                         # proper rotation (det +1); the part is symmetric in Y
    R = np.column_stack([ex, ey, ez])
    T = np.zeros((3, 4)); T[:, :3] = R; T[:, 3] = o
    W = M.transform(T)
    return W.transform(B.rot_x_about(*HINGE, a)) if a else W


HINGE = np.array([65.13116162694143, -29.42857706332635])   # = build_report info.hinge


def check_mesh(M, name):
    t = B.to_tri(M)
    pa = printability.analyse(M, name)
    bodies = len(t.split(only_watertight=False))
    ok = t.is_watertight and bodies == 1 and pa['support_mm2'] < 0.5
    print('%s: watertight=%s bodies=%d volume=%.0f mm3 bed=%.1f mm2 overhang=%.2f bridge=%.2f support=%.2f -> %s'
          % (name, t.is_watertight, bodies, t.volume, pa['bed_mm2'], pa['overhang_mm2'],
             pa.get('bridge_mm2', 0), pa['support_mm2'], 'OK' if ok else 'FAIL'))
    return ok


def assembly_check(M):
    R = os.path.join(SK, 'cache', 'render')
    jaw_t = trimesh.load(os.path.join(R, 'jaw.stl'))
    jaw = B.to_man(jaw_t)
    face = B.to_man(trimesh.load(os.path.join(R, 'face.stl')))
    mech = B.mechanism(tuple(HINGE))
    Ps = B.servo_frame(tuple(HINGE)); st = B.SERVO['spline_top']
    # the servo model minus the spline itself (the hub is pressed onto it by design);
    # the gear bump under the hub stays
    servo = mech['servo'] - B.m_cyl(Ps(st - 2.4 + 0.01, 0, 0), Ps(st + 1, 0, 0), 2.6)
    ok = True
    # jaw: fixed to the horn, so one pose; the horn face sits on the pad face (contact)
    W = to_world(M)
    v = (W.translate([-B.SERVO_SIDE * 0.02, 0, 0]) ^ jaw).volume()
    xs = np.array(B.to_tri(W).bounds)[:, 0]
    print('assembled: horn |x| %.2f .. %.2f (pad face %.1f); overlap with jaw (horn 0.02 in) = %.3f mm3'
          % (abs(xs[0]), abs(xs[1]), B.HORN_FACE_X, v))
    ok &= v < 0.01 and abs(abs(xs[1]) - B.HORN_FACE_X) < 0.01
    # pilots line up with the jaw's Ø2.2 pilots (the jaw is empty along each horn pilot axis)
    d = B.horn_dir()
    for r in PILOTS:
        c = HINGE + r * d
        inside = jaw_t.contains([[B.SERVO_SIDE * x, *c] for x in (33.5, 36.0, 40.0)])
        print('  jaw pilot r=%.0f open along the horn pilot axis: %s' % (r, not inside.any()))
        ok &= not inside.any()
    # statics over the sweep (beyond both stops)
    worst = {}
    for a in np.arange(B.JAW_CLOSE_STOP - B.JAW_STOP_MARGIN, B.JAW_OPEN_DEG + 2 * B.JAW_STOP_MARGIN + 0.01, 0.5):
        Wa = to_world(M, a)
        for nm, S in (('servo (case + gear bump)', servo), ('bracket', mech['bracket']), ('face', face)):
            g = Wa.min_gap(S, 3.0)
            worst[nm] = min(worst.get(nm, 9), g)
    for nm, g in worst.items():
        print('  sweep %.1f..%.1f deg: min gap to %s = %.2f mm' % (B.JAW_CLOSE_STOP - B.JAW_STOP_MARGIN,
                                                                    B.JAW_OPEN_DEG + 2 * B.JAW_STOP_MARGIN, nm, g))
        ok &= g >= 0.15
    # inside the HORN_R swept disc
    tw = B.to_tri(W); rr = np.hypot(tw.vertices[:, 1] - HINGE[0], tw.vertices[:, 2] - HINGE[1])
    print('  max radius %.2f (HORN_R %.1f)' % (rr.max(), B.HORN_R)); ok &= rr.max() <= B.HORN_R
    return ok


def main():
    os.makedirs(OUT, exist_ok=True)
    parts = []; ok = True
    for i, b in enumerate(BORES):
        M = horn(b, i + 1)
        name = 'horn_b%02d' % round(b * 10)
        ok &= check_mesh(M, name)
        B.to_tri(M).export(os.path.join(OUT, name + '.stl'))
        parts.append(M)
    w = HUB_R * 2
    plate = B.union([M.translate([0, i * (w + PLATE_GAP), 0]) for i, M in enumerate(parts)])
    bb = np.array(plate.bounding_box()); plate = plate.translate([-(bb[0] + bb[3]) / 2, -(bb[1] + bb[4]) / 2, 0])
    t = B.to_tri(plate); t.export(os.path.join(OUT, 'horn_plate.stl'))
    print('horn_plate: %d bodies, %.1f x %.1f x %.1f mm' % (len(t.split(only_watertight=False)), *t.extents))
    b1 = np.array(parts[0].bounding_box())
    print('one horn: %.1f x %.1f x %.1f mm' % tuple(b1[3:] - b1[:3]))
    eng = min(ARM_T, SCREW_PAST_FACE)
    print('pilot wall: side %.2f, tip %.2f mm; M2x16 engagement in the arm: %.1f mm (screw tip %.1f past the pad face)'
          % (TIP_W / 2 - PILOT_D / 2, TIP_W / 2 - PILOT_D / 2, eng, SCREW_PAST_FACE))
    if '--check' in sys.argv:
        ok &= assembly_check(parts[0])
    print('ALL OK' if ok else 'FAILED')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
