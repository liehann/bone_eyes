"""Assembled-frame meshes and fastener / insert positions for the assembly guide.
Frame: -Y = face direction, +X = skull left, +Z up (mm).

Printed parts come from cache/render (the assembled poses, identical geometry to
out/ for face, back, jaw, stand and liners); the cap comes from out/cap.stl (no
hook) rotated back from its print pose; the servo bracket from build.mechanism().
"""
import os, sys, pickle
import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, SK)
import build as B   # noqa: E402  (constants + mechanism(); importing does not build)

RENDER = os.path.join(SK, 'cache', 'render')
OUT = os.path.join(SK, 'out')
CACHE = os.path.join(SK, 'cache', 'guide'); os.makedirs(CACHE, exist_ok=True)
HINGE = np.array([65.13116162694143, -29.42857706332635])


def _dec(m, n):
    if len(m.faces) <= n:
        return m
    import fast_simplification
    v, f = fast_simplification.simplify(np.asarray(m.vertices, np.float32), np.asarray(m.faces, np.int64),
                                        target_reduction=1.0 - n / len(m.faces))
    return trimesh.Trimesh(v, f, process=True)


def _cap():
    c = trimesh.load(os.path.join(OUT, 'cap.stl'))
    n, _ = B.seam()
    a = np.degrees(np.arctan2(n[1], n[2]))
    c.apply_transform(trimesh.transformations.rotation_matrix(np.radians(-a), [1, 0, 0]))
    ref = trimesh.load(os.path.join(RENDER, 'cap.stl'))     # old cap (with hook): back, top and sides unchanged
    bc, br = c.bounds, ref.bounds
    c.apply_translation([(br[0, 0] + br[1, 0] - bc[0, 0] - bc[1, 0]) / 2, br[1, 1] - bc[1, 1], br[1, 2] - bc[1, 2]])
    return c


def _box(a, b):
    a, b = np.array(a, float), np.array(b, float)
    return trimesh.creation.box(extents=b - a, transform=trimesh.transformations.translation_matrix((a + b) / 2))


def load_parts():
    fn = os.path.join(CACHE, 'parts.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    P = {}
    lim = dict(face=160000, back=60000, jaw=60000, liner_eye_L=12000, liner_eye_R=12000, liner_nose=12000, bar=16000)
    for n in ['face', 'back', 'jaw', 'stand', 'bar', 'modules', 'screens', 'servo', 'horn', 'radar',
              'liner_eye_L', 'liner_eye_R', 'liner_nose']:
        m = trimesh.load(os.path.join(RENDER, n + '.stl'))
        P[n] = _dec(m, lim.get(n, 10 ** 9))
    P['cap'] = _dec(_cap(), 60000)
    mech = B.mechanism(tuple(HINGE))
    P['bracket'] = B.to_tri(mech['bracket'])
    # ESP32 (no tray): devkit board taped flat behind the eye bar (schematic position)
    P['esp32'] = trimesh.util.concatenate([_box([-48, 34, -14.6], [-20, 89, -13.0]),
                                           _box([-40, 34.5, -13.0], [-28, 52, -10.0]),     # WROVER can
                                           _box([-38, 84, -13.0], [-30, 89.5, -10.2])])    # micro-USB
    r = P['radar'].copy(); c = r.bounds.mean(0)        # radar on edge, as it goes down the slot
    r.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0], c))
    P['radar_edge'] = r
    pickle.dump(P, open(fn, 'wb'))
    return P


def fasteners():
    """name -> dict(head, axis (out of the hole, toward the head/tool), kind, L)."""
    F = {}
    y_back = B.EYE_DEPTH + B.MODULE_T + B.STANDOFF_H + B.BAR_T
    Tm = B.scad_to_skull(y_back)
    k = 0
    for xe in (-B.EYE_SPACING / 2, B.EYE_SPACING / 2):
        a_ = np.radians(B.eye_rot(xe))
        for sx in (-1, 1):
            lx, ly = sx * 7.875, -0.14
            px, py = xe + lx * np.cos(a_) - ly * np.sin(a_), lx * np.sin(a_) + ly * np.cos(a_)
            F['m2_%d' % k] = dict(head=Tm[:, :3] @ [px, py, 0.0] + Tm[:, 3], axis=np.array([0, 1.0, 0]), L=8, d=2); k += 1
    hx, hz = B.BAR_HOLES[B.BAR_BOLTS[0]]
    F['bar_bolt'] = dict(head=np.array([hx, y_back, hz]), axis=np.array([0, 1.0, 0]), L=12, d=3, washer=True)
    mech = B.mechanism(tuple(HINGE))
    for i, p in enumerate(mech['bracket_bolts']):
        F['bracket_%d' % i] = dict(head=p + [0, 0, B.BRACKET_T], axis=np.array([0, 0, 1.0]), L=8, d=3)
    Ps = B.servo_frame(tuple(HINGE)); S = B.SERVO
    vmid = (-S['shaft_off'] + S['L'] - S['shaft_off']) / 2
    for i, v in enumerate((vmid - S['hole_sp'] / 2, vmid + S['hole_sp'] / 2)):
        F['tab_%d' % i] = dict(head=Ps(S['tab_top'], v, 0), axis=np.array([1.0, 0, 0]), L=8, d=2)
    F['horn_screw'] = dict(head=Ps(S['spline_top'] + 1.0, 0, 0), axis=np.array([1.0, 0, 0]), L=4, d=2)
    hd = B.horn_dir()
    for i, r in enumerate(B.HORN_JAW_HOLES):
        c = HINGE + r * hd
        F['horn_jaw_%d' % i] = dict(head=np.array([B.HORN_SCREW_SEAT_MAX - 1.0, *c]), axis=np.array([1.0, 0, 0]), L=16, d=2)
    F['pivot'] = dict(head=np.array([-(B.PIVOT_FACE_X + 14.5), *HINGE]), axis=np.array([-1.0, 0, 0]), L=20, d=3, washer=True)
    N = B.NECK
    F['stand'] = dict(head=np.array([0.0, N['y'] + B.STAND['col_d'] / 2 - 1.5, N['z_bottom'] + N['screw_z']]),
                      axis=np.array([0, 1.0, 0]), L=8, d=3)
    return F


def probe(mesh, origin, direction, off=2.5):
    """First hit of a ray on mesh, offset off mm in x from the hole axis (lands on the
    counterbore floor / post face beside the bore); returned on the axis."""
    origin = np.asarray(origin, float)
    loc, ri, _ = mesh.ray.intersects_location([origin + [off, 0, 0]], [direction])
    if len(loc) == 0:
        return None
    t = (loc - origin) @ np.asarray(direction)
    return loc[np.argmin(t)] - [off, 0, 0]


def cover_fasteners(P):
    """Back-cover and cap screws: found on the meshes (their counterbores)."""
    F = {}
    zb = B.Z_FLOOR + 5.0
    # back screw: from far behind along -Y at x=0, z=zb: the counterbore floor is the
    # first face hit past the outer surface; use the outer hit + small inset
    o = np.array([0.0, 300.0, zb])
    hit = probe(P['back'], o, [0, -1.0, 0])
    F['back_screw'] = dict(head=hit, axis=np.array([0, 1.0, 0]), L=12, d=3)
    n, p0 = B.seam()
    tb = np.array([0.0, 1.0, -B.SEAM['slope']]); tb /= np.linalg.norm(tb)
    # the cap screw axis is ~6 mm above the seam at y ~ 120..; scan z for the counterbore
    best = None
    for dz in (6.0,):
        q = np.array([0.0, 120.0, B.seam_z(120.0)]) + n * dz
        h = probe(P['cap'], q + tb * 200, -tb)
        if h is not None and (best is None or h[1] < best[0][1]):
            best = (h, dz)
    F['cap_screw'] = dict(head=best[0], axis=tb, L=12, d=3)
    return F


def inserts(P):
    """7 inserts: number -> (point at the hole mouth, outward axis, part)."""
    mech = B.mechanism(tuple(HINGE))
    hx, hz = B.BAR_HOLES[B.BAR_BOLTS[0]]
    y_post = B.EYE_DEPTH + B.MODULE_T + B.STANDOFF_H     # bar front face = post face
    bb = mech['bracket_bolts']
    cf = cover_fasteners(P)
    zb = B.Z_FLOOR + 5.0
    yb = probe(P['face'], np.array([0.0, 300.0, zb]), [0, -1.0, 0])
    N = B.NECK
    ys = probe(P['face'], np.array([0.0, 300.0, N['z_bottom'] + N['screw_z']]), [0, -1.0, 0])
    tb = cf['cap_screw']['axis']
    cb = probe(P['back'], cf['cap_screw']['head'] - tb * 2.0, -tb)
    return {
        1: (np.array([hx, y_post, hz]), np.array([0, 1.0, 0]), 'face'),
        2: (bb[0], np.array([0, 0, 1.0]), 'face'),
        3: (bb[1], np.array([0, 0, 1.0]), 'face'),
        4: (np.array([-(B.PIVOT_FACE_X + 0.5), *HINGE]), np.array([-1.0, 0, 0]), 'face'),
        5: (yb, np.array([0, 1.0, 0]), 'face'),
        6: (ys, np.array([0, 1.0, 0]), 'face'),
        7: (cb, tb, 'back'),
    }


if __name__ == '__main__':
    P = load_parts()
    for k, m in P.items():
        print(k, len(m.faces), np.round(m.bounds, 1).tolist())
    for k, v in {**fasteners(), **cover_fasteners(P)}.items():
        print(k, np.round(v['head'], 2), v['axis'])
    for k, v in inserts(P).items():
        print('insert', k, np.round(v[0], 2), v[1], v[2])
