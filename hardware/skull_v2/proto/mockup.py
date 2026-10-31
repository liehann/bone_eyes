"""Rough v2 mock-up: one approximate mesh per part from docs/skull-v2-architecture.md,
in the assembled eye frame (-Y = face direction, +X = skull left, +Z up).

Shells come from the v1 assembled meshes (hardware/skull/cache/render, symlinked
from the main checkout) cut at the seam plane y = 100. The mechanical parts are
boxes, cylinders and hulls in the designed shapes (rev 2): for reviewing
layout, not printable. fit_check() prints the clearances for the rev-2 findings.

Writes proto/out/<part>.stl and proto/out/meta.json (parts, explode vectors,
assembly steps, wires, screws, seam band). viewer/make_viewer.py packs them.

    hardware/.venv/bin/python hardware/skull_v2/proto/mockup.py
"""
import os, sys, json
import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from wiring import pin_xyz, LEADS, J2, J3, ESP   # reuse the wire-route datums
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
RENDER = os.path.join(REPO, 'hardware', 'skull', 'cache', 'render')
OUT = os.path.join(HERE, 'out'); os.makedirs(OUT, exist_ok=True)

Y_SEAM = 100.0
HINGE = (65.13, -29.43)          # y, z of the jaw axis (doc section 4)
BAY = dict(x=50.0, y0=48.0, z=-19.0)

PARTS = {}      # name -> dict(mesh, label, group, color, explode, step, shell)
LINES = []      # tubes: wires, screws, seam


# ---------------------------------------------------------------- helpers
def box(a, b):
    a, b = np.array(a, float), np.array(b, float)
    return trimesh.creation.box(extents=b - a, transform=trimesh.transformations.translation_matrix((a + b) / 2))


def cyl(p0, p1, r, sections=24):
    return trimesh.creation.cylinder(radius=r, segment=[np.array(p0, float), np.array(p1, float)], sections=sections)


def hull_yz(pts_yz, x0, x1):
    pts = [(x, y, z) for (y, z) in pts_yz for x in (x0, x1)]
    return trimesh.convex.convex_hull(np.array(pts, float))


def cat(*ms):
    return trimesh.util.concatenate(ms)


def union(*ms):
    return trimesh.boolean.union(list(ms), engine='manifold')


def decimate(m, n):
    if len(m.faces) <= n:
        return m
    import fast_simplification
    v, f = fast_simplification.simplify(np.asarray(m.vertices, np.float32), np.asarray(m.faces, np.int64),
                                        target_reduction=1.0 - n / len(m.faces))
    return trimesh.Trimesh(v, f, process=True)


def load(name, n):
    m = trimesh.load(os.path.join(RENDER, name + '.stl'), force='mesh')
    return decimate(m, n)


def add(name, mesh, label, group, color, explode=(0, 0, 0), step=1, shell=False, flat=True):
    PARTS[name] = dict(mesh=mesh, label=label, group=group, color=color, explode=list(explode),
                       step=step, shell=shell, flat=flat)


def line(id, group, pts, r, color, explode=(0, 0, 0), step=1, label=None):
    LINES.append(dict(id=id, group=group, pts=np.round(np.array(pts, float), 2).tolist(), r=r, color=color,
                      explode=list(explode), step=step, label=label or id))


def screw(id, head, tip, r=1.5, headr=2.8, explode=(0, 0, 0), step=1, color='#ff2fb4'):
    head, tip = np.array(head, float), np.array(tip, float)
    d = (head - tip) / np.linalg.norm(head - tip)
    line(id, 'screws', [tip, head], r, color, explode, step)
    line(id + '_head', 'screws', [head, head + d * 2.2], headr, color, explode, step)


def keep_faces(m, mask):
    m = m.copy(); m.update_faces(mask); m.remove_unreferenced_vertices(); return m


# ---------------------------------------------------------------- shells (v1 outer skin)
def shells():
    face, back, cap = load('face', 110000), load('back', 40000), load('cap', 60000)
    allsk = cat(face, back, cap)
    pieces_f, pieces_c = [], []
    for m in (face, back, cap):
        f = m.slice_plane([0, Y_SEAM, 0], [0, -1, 0], cap=False)   # keeps y < seam
        c = m.slice_plane([0, Y_SEAM, 0], [0, 1, 0], cap=False)    # keeps y > seam
        if len(f.faces): pieces_f.append(f)
        if len(c.faces): pieces_c.append(c)
    fs = cat(*pieces_f); cs = cat(*pieces_c)
    cen = fs.triangles_center            # hinge bay: no face-shell material (doc section 4)
    inbay = (abs(cen[:, 0]) < BAY['x']) & (cen[:, 1] > BAY['y0']) & (cen[:, 2] < BAY['z'])
    fs = keep_faces(fs, ~inbay)
    fs.merge_vertices(); cs.merge_vertices()
    add('face_shell', fs, 'Face shell', 'shells', '#efe6cf', (0, -130, 0), 13, shell=True, flat=False)
    add('cranium_shell', cs, 'Cranium shell', 'shells', '#bcd2ee', (0, 60, 0), 15, shell=True, flat=False)
    # seam band: section of the v1 skin at y = 100
    sec = allsk.section(plane_origin=[0, Y_SEAM, 0], plane_normal=[0, 1, 0])
    n = 0
    for e in sec.discrete:
        if len(e) < 30: continue
        e = e[::max(1, len(e) // 260)]
        e = np.vstack([e, e[:1]])
        line('seam_%d' % n, 'seam', e, 1.0, '#ff2020', (0, 0, 0), 15, 'Seam band'); n += 1
    print('seam loops', n)
    return allsk


def liners():
    ls = [load('liner_eye_L', 9000), load('liner_eye_R', 9000), load('liner_nose', 9000)]
    add('liners', cat(*ls), 'Liners (eyes, nose)', 'shells', '#1c1c1c', (0, -130, 0), 13, flat=False)
    add('radar', load('radar', 100), 'Radar module', 'hardware', '#e04a2a', (0, -130, 0), 12)


# ---------------------------------------------------------------- datums (doc section 4, revision 2)
AY, AZ = HINGE                      # jaw axis (y, z), along X
STOP_CLOSE, STOP_OPEN = -0.5, 20.0  # jaw hard stops (deg, + = open)
SWEEP = (-1.5, 21.5)                # jaw sweep the shells and chassis must clear
FINGER = dict(x=(-32.0, -27.5), dy=(5.5, 13.5), dz=2.5)   # v1 stop finger on the -X knuckle
STAND_AX = (0.0, 90.0)
COLUMN_R, FLANGE_R = 19.0, 28.0
GRIP_R = 12.5                       # pinch grip, Ø25
# every heat-set insert: (part, axis, mouth point, direction into the part)
INSERTS = [
    ('base', 'Z', (7.0, 52.3, -36.0), (0, 0, -1)), ('base', 'Z', (13.0, 52.3, -36.0), (0, 0, -1)),      # servo bracket
    ('base', 'Z', (-22.25, 52.0, -36.0), (0, 0, -1)), ('base', 'Z', (-22.25, 59.5, -36.0), (0, 0, -1)),  # pivot bracket
    ('base', 'Z', (12.0, 44.0, -30.0), (0, 0, -1)), ('base', 'Z', (-12.0, 44.0, -30.0), (0, 0, -1)),    # face shell
    ('base', 'Z', (24.0, 113.0, -30.0), (0, 0, -1)), ('base', 'Z', (-24.0, 113.0, -30.0), (0, 0, -1)),  # cranium shell
    ('pivot_bracket', 'X', (-31.5, AY, AZ), (1, 0, 0)),                                                  # jaw pivot
    ('pivot_bracket', 'X', (-26.5, 83.0, -30.0), (1, 0, 0)),                                             # stop block
    ('front_module', 'Y', (-27.5, 21.2, 16.0), (0, -1, 0)),                                              # eye-bar bolt
    ('front_module', 'Y', (33.0, 76.0, 10.0), (0, -1, 0)), ('front_module', 'Y', (-33.0, 76.0, 10.0), (0, -1, 0)),
    ('stand', 'Z', (22.0, 97.0, -44.0), (0, 0, -1)), ('stand', 'Z', (-22.0, 97.0, -44.0), (0, 0, -1)),  # base -> stand
]
# material under each insert mouth along its axis (designed thickness), for the bore check
INSERT_STOCK = {'base': 8.0, 'pivot_bracket': 8.5, 'front_module': 9.2, 'stand': 8.0}
BORE = 6.7


def rot_jaw(m, deg):
    T = trimesh.transformations
    M = T.translation_matrix([0, AY, AZ]) @ T.rotation_matrix(np.radians(deg), [1, 0, 0]) @ T.translation_matrix([0, -AY, -AZ])
    m = m.copy(); m.apply_transform(M); return m


def rot_yz(dy, dz, deg):
    a = np.radians(deg)
    return dy * np.cos(a) - dz * np.sin(a), dy * np.sin(a) + dz * np.cos(a)


def diff(a, *b):
    return trimesh.boolean.difference([a] + list(b), engine='manifold')


def inter(a, b):
    return trimesh.boolean.intersection([a, b], engine='manifold')


# ---------------------------------------------------------------- chassis
def chassis():
    # base: plate (wings to |x| 49.5 behind the knuckles), pads, pocket, tongues, bosses, spine
    plate = union(box((-30, 48, -44), (30, 81, -40)), box((-49.5, 81, -44), (49.5, 104, -40)),
                  box((3.0, 48, -40), (16.1, 57, -36)),                 # servo-bracket pad
                  box((-27.5, 48.0, -40), (-17.0, 87.5, -36)))          # pivot-bracket pad
    ftong = hull_yz([(48, -44), (48, -40), (42, -34), (38, -34), (38, -38), (42, -38)], -22, 22)
    rtong = hull_yz([(104, -44), (104, -40), (110, -34), (118, -34), (118, -38), (110, -38)], -30, 30)
    bosses = [cyl((s * 12, 44, -34), (s * 12, 44, -30), 4.5) for s in (-1, 1)] + \
             [cyl((s * 24, 113, -34), (s * 24, 113, -30), 4.5) for s in (-1, 1)]
    spine = union(box((-16, 76, -40), (16, 80, -20)),
                  trimesh.convex.convex_hull(np.vstack([box((-16, 76, -20.01), (16, 80, -20)).vertices,
                                                        box((-35, 76, -1.01), (35, 80, -1)).vertices])),
                  box((-35, 76, -1.01), (35, 80, 27)))
    base = union(plate, ftong, rtong, spine, *bosses)
    base = diff(base, cyl((0, 90, -45), (0, 90, -39), 8),                                   # USB hole
                box((16.35, 55.85, -41.0), (22.85, 74.35, -39.9)),                          # servo-wall pocket
                box((-14, 75, -41), (-8, 81, -36)))                                          # USB notch
    add('base', base, 'Chassis base', 'chassis', '#8d949c', (0, 0, 0), 2)

    ins = [cyl(p, np.array(p) + np.array(d) * BORE, 2.0, 12) for _, _, p, d in INSERTS]
    add('inserts', cat(*ins), 'Heat-set inserts (15)', 'chassis', '#d8a31c', (0, 0, 0), 1)

    # front module: brow plate, posts, key, arms to the spine, ESP32 ledges, USB window in the -X arm
    arm_r = diff(box((-35, 27, -4), (-31, 76, 27)),
                 hull_yz([(41.25, 7.25), (53.75, 7.25), (74.25, 27.75), (74.25, 28.5), (41.25, 28.5)], -36, -30))
    arms = [box((31, 27, -4), (35, 76, 27)), arm_r]
    posts = [cyl((s * 27.5, 12, 16), (s * 27.5, 21.2, 16), 4.5, 24) for s in (-1, 1)]
    ledges = [box((25, 33.4, 19), (31, 61.4, 22)), box((-31, 33.4, 19), (-25, 41.25, 22)), box((-31, 53.75, 19), (-25, 61.4, 22))]
    mod = cat(box((-35, 10, 23), (35, 30, 27)), box((-8, 10, 27), (8, 24, 32)), *arms, *posts, *ledges)
    add('front_module', mod, 'Front module (brow, arms, key, ledges)', 'chassis', '#4f8f6f', (0, -40, 60), 7)
    add('eye_bar', load('bar', 8000), 'Eye bar', 'hardware', '#7a8088', (0, -75, 60), 6)
    add('lcds', cat(load('modules', 2000), load('screens', 1000)), 'LCD modules', 'hardware', '#e3b41f', (0, -105, 60), 6)
    esp = cat(box((-27.5, 33.4, 22), (27.5, 61.4, 23.6)),
              box((-25, 34.5, 5.5), (25, 37.5, 22)), box((-25, 57.3, 5.5), (25, 60.3, 22)),
              box((-27.5, 44, 23.6), (-12, 52, 27)))
    add('esp32', esp, 'ESP32 board + housings', 'hardware', '#1f9e94', (0, -40, 100), 6)
    add('usb_plug', box((-36, 42, 8), (-27.5, 53, 26)), '90 deg USB plug', 'hardware', '#c9c93a', (0, -40, 100), 6)

    # servo mechanism: servo + horn (v1 meshes, on the hinge axis), bracket re-stacked onto the base
    add('servo', load('servo', 1000), 'Servo (MG90S)', 'hardware', '#3f6fd8', (15, 0, 70), 3)
    add('horn', load('horn', 500), 'Servo horn', 'hardware', '#d0303c', (15, 0, 70), 3)
    wall = diff(box((16.6, 56.13, -41.0), (19.6, 74.13, -5.0)), box((16.0, 58.28, -36.18), (20.0, 71.98, -11.88)))
    foot = box((4.0, 48.5, -36.0), (19.6, 56.13, -33.0))
    gus = hull_yz([(48.5, -33.0), (56.13, -33.0), (56.13, -20.0)], 16.6, 19.6)
    sb = diff(union(wall, foot, gus), *[cyl((x, 52.3, -37), (x, 52.3, -32), 1.7) for x in (7.0, 13.0)])
    add('servo_bracket', sb, 'Servo bracket (stands on the base)', 'chassis', '#2fb0c8', (15, 0, 70), 4)

    # pivot bracket: body inboard of the finger, nose r 4 out to the pivot face
    body = box((-26.5, 48.5, -36.0), (-18.0, 87.0, -23.0))
    nose = cyl((-31.5, AY, AZ), (-26.4, AY, AZ), 4.0, 32)
    pb = diff(union(body, nose), *[cyl((-22.25, y, -37), (-22.25, y, -22), 1.7) for y in (52.0, 59.5)],
              *[cyl((-22.25, y, -33), (-22.25, y, -22), 3.25) for y in (52.0, 59.5)])
    add('pivot_bracket', pb, 'Pivot bracket', 'chassis', '#2f8fc8', (-15, 0, 70), 5)
    add('stop_block', stop_block(), 'Stop block (bolt-on)', 'chassis', '#c86a2f', (-10, 40, 0), 10)

    # mastoid fillers: skin behind the knuckles, y 81-100, |x| 36 to the skin (rough hull)
    fl = []
    for s in (-1, 1):
        pts = [(s * x, y, z) for y in (81.0, 100.0) for x, z in ((36, -34), (36, -19), (52, -19), (46, -27), (40, -33))]
        fl.append(trimesh.convex.convex_hull(np.array(pts)))
    add('fillers', cat(*fl), 'Mastoid fillers (L, R)', 'shells', '#e8d9b5', (0, 40, -30), 14)

    add('jaw', load('jaw', 60000), 'Jaw', 'jaw', '#d7b98c', (0, 0, -70), 9, flat=False)

    # stand: v1 column and base, new top (45 deg chamfer, Ø56 x 8 flange, spigot); 92 tall
    st = load('stand', 5000).slice_plane([0, 0, -61], [0, 0, -1], cap=True)
    ring = lambda r, z: [(r * np.cos(a), 90 + r * np.sin(a), z) for a in np.linspace(0, 2 * np.pi, 40, endpoint=False)]
    cham = trimesh.convex.convex_hull(np.array(ring(COLUMN_R, -61.5) + ring(FLANGE_R, -52)))
    top = cat(cham, cyl((0, 90, -52), (0, 90, -44), FLANGE_R, 48), cyl((0, 90, -44), (0, 90, -41), 15, 40))
    add('stand', cat(st, top), 'Stand (new top, 92 tall)', 'chassis', '#b79a78', (0, 0, -60), 2)


def stop_block():
    """C-shaped stop round the finger. Lower jaw face = finger underside at the closed stop,
    upper jaw face = finger top at the open stop, back wall past the finger tip.
    Slides forward (-Y) onto the finger, screw along +X through the ear at y 83."""
    blk = union(box((-31.0, AY + 5.0, -37.0), (-26.75, AY + 18.5, -18.0)), box((-34.0, 80.0, -34.0), (-26.75, 86.5, -26.0)))
    pts = []
    for d in (0.0, 20.0):
        for deg, dz in ((STOP_CLOSE, -FINGER['dz']), (STOP_OPEN, FINGER['dz'])):
            ry, rz = rot_yz(d, dz, deg)
            pts += [(x, AY + ry, AZ + rz) for x in (-35, -26)]
    wedge = trimesh.convex.convex_hull(np.array(pts))
    slot = inter(wedge, cyl((-35, AY, AZ), (-26, AY, AZ), 14.7, 64))
    return diff(blk, slot, cyl((-35, 83, -30), (-26, 83, -30), 1.7))


# ---------------------------------------------------------------- screws and wires
def screws_and_wires():
    for sx in (-1, 1):
        screw('stand_%d' % sx, (sx * 22, 97, -40), (sx * 22, 97, -50), explode=(0, 0, 40), step=2)
        screw('face_%d' % sx, (sx * 12, 44, -41), (sx * 12, 44, -29), explode=(0, 0, -75), step=13)
        screw('cranium_%d' % sx, (sx * 24, 113, -41), (sx * 24, 113, -29), explode=(0, 0, -75), step=15)
        screw('spine_%d' % sx, (sx * 33, 81.5, 10), (sx * 33, 70, 10), explode=(0, 50, 0), step=7)
        screw('filler_%d' % sx, (sx * 40, 90, -44), (sx * 40, 90, -32), r=1.4, explode=(0, 0, -75), step=14)
    for i, x in enumerate((7.0, 13.0)):
        screw('servobkt_%d' % i, (x, 52.3, -33), (x, 52.3, -43), explode=(15, 0, 95), step=4)
    for i, y in enumerate((52.0, 59.5)):
        screw('pivotbkt_%d' % i, (-22.25, y, -33), (-22.25, y, -43), explode=(-15, 0, 95), step=5)
    screw('bar_bolt', (-27.5, 29.5, 16), (-27.5, 16.5, 16), r=1.5, headr=4.5, explode=(0, -35, 60), step=6)
    screw('pivot_pin', (-51, AY, AZ), (-28.5, AY, AZ), explode=(-80, 0, 0), step=9)
    screw('horn_a', (51, AY - 3, -40), (35, AY - 3, -40), r=1.0, headr=2.0, explode=(80, 0, 0), step=9)
    screw('horn_b', (51, AY + 1, -32), (35, AY + 1, -32), r=1.0, headr=2.0, explode=(80, 0, 0), step=9)
    screw('stop_screw', (-34, 83, -30), (-22, 83, -30), explode=(-60, 0, 0), step=10)

    cols = ['#ff9f1c', '#2ec4b6', '#e71d36', '#9b5de5', '#f15bb5', '#00bbf9', '#8ac926', '#ffd166']
    for li, (name, (st, run, sig)) in enumerate(LEADS.items()):
        for k, (sname, (h, p)) in enumerate(sig.items()):
            pin = pin_xyz(h, p); z = (k - 3.5) * 0.9
            p1 = np.array([st[0], st[1] + run, z]); p2 = np.array([pin[0], max(st[1] + run + 2, pin[1] - 3), z])
            line('lcd_%d_%s' % (li, sname), 'wires', [[st[0], st[1], z], p1, p2, [pin[0], pin[1], z], [pin[0], pin[1], 5.5]],
                 0.45, cols[k], (0, -40, 60), 6, 'LCD %s %s' % ('L' if li == 0 else 'R', sname))
    # USB: plug, down the -X arm, in front of the pivot bracket, back along x -12, spine notch, plate hole, stand
    line('usb_cable', 'wires', USB_ROUTE, 2.25, '#d9d9d9', (0, 0, 0), 7, 'USB cable')
    sv = np.array([15, 71.2, -30]); r = pin_xyz('J2', 11)
    line('servo_lead', 'wires', [sv, (15, 74, -30), (r[0], 70, -10), (r[0], r[1], 0), (r[0], r[1], 5.5)], 0.8, '#d49a3a',
         (15, 0, 70), 8, 'Servo lead')
    for p in (5, 7, 8):
        r = pin_xyz('J2', p)
        line('radar_%d' % p, 'wires', [(0, 6.4, -27.5), (0, 12, -27.5), (0, 40, -27.5), (r[0], 52, -12), (r[0], r[1], -4), (r[0], r[1], 5.5)],
             0.45, '#e04a2a', (0, -130, 0), 12, 'Radar lead')
    # J1 lap at the seam, simplified: lip (face side) and tongue (cranium side) as bands round the y 100 section
    lap()


USB_ROUTE = [(-31, 47.5, 8), (-32, 47.5, -10), (-14, 52, -18), (-12, 60, -30), (-12, 66, -37), (-12, 80, -37), (0, 90, -40), (0, 90, -110)]


def lap():
    """S1 lap as a simplified extrusion: the y 100 section of the skin, offset inward for the
    face lip (0-2.0) and the cranium tongue (2.25-4.25), tongue y 92-100."""
    sk = cat(load('face', 60000), load('back', 20000), load('cap', 30000))
    sec = sk.section(plane_origin=[0, Y_SEAM, 0], plane_normal=[0, 1, 0])
    loops = sorted(sec.discrete, key=len)[-1:]
    for e in loops:
        e = e[::max(1, len(e) // 200)]
        c = e[:, [0, 2]].mean(0)
        for nm, off, y0, col, stp in (('lap_lip', 1.0, 92.0, '#efe6cf', 13), ('lap_tongue', 3.25, 92.0, '#7da3d8', 15)):
            d = e[:, [0, 2]] - c; d /= np.linalg.norm(d, axis=1)[:, None]
            q = e.copy(); q[:, 0] -= d[:, 0] * off; q[:, 2] -= d[:, 1] * off
            keep = ~((abs(q[:, 0]) < 50) & (q[:, 2] < -19) & (abs(q[:, 0]) < 36)) if nm == 'lap_lip' else np.ones(len(q), bool)
            for yy in (y0 + 0.5, 99.5):
                pts = q.copy(); pts[:, 1] = yy
                line('%s_%d' % (nm, int(yy)), 'seam', np.vstack([pts[keep], pts[keep][:1]]), 1.0, col, (0, 0, 0), stp, nm)


# ---------------------------------------------------------------- fit check (findings 1-10 of the mock-up review)
def as_mf(m):
    import manifold3d as mf
    return mf.Manifold(mf.Mesh(vert_properties=np.asarray(m.vertices, np.float32), tri_verts=np.asarray(m.faces, np.uint32)))


def vol(a, b):
    m = as_mf(a) ^ as_mf(b)
    return float(m.volume() if hasattr(m, 'volume') else m.get_volume())


def gap(a, b, n=20000):
    """approximate surface clearance (mm) between two meshes, by sampling."""
    from scipy.spatial import cKDTree
    return float(cKDTree(b.sample(n)).query(a.sample(n))[0].min())


def hand_poses(head, axis, reach, held):
    """L-key + Ø25 grip + 45 x 60 x 30 hand block, at 24 angles round the screw axis."""
    axis = np.array(axis, float); axis /= np.linalg.norm(axis)
    e1 = np.cross(axis, [0, 0, 1] if abs(axis[2]) < 0.9 else [1, 0, 0]); e1 /= np.linalg.norm(e1); e2 = np.cross(axis, e1)
    elbow = np.array(head, float) + axis * reach
    out = []
    for a in np.radians(np.arange(0, 360, 15)):
        u = np.cos(a) * e1 + np.sin(a) * e2; t = np.cross(axis, u)
        key = cyl(np.array(head) + axis * 6.0, elbow, 1.5, 8)
        grip = cyl(elbow, elbow + u * (held + 15), GRIP_R, 16)
        c = elbow + u * (held + 15 + 15)
        R = np.eye(4); R[:3, 0], R[:3, 1], R[:3, 2], R[:3, 3] = u, t, axis, c
        blk = trimesh.creation.box(extents=(30, 45, 60), transform=R)
        out.append((key, grip, blk))
    return out


def hand_check(name, head, axis, obstacles):
    """best 60 deg sector, both ways round the key; returns (way, start deg, min clearance)."""
    from scipy.spatial import cKDTree
    obs = cat(*obstacles); tree = cKDTree(obs.sample(60000))
    best = None
    for way, reach, held in (('long in', 50.0, 25.0), ('short in', 25.0, 50.0)):
        cl = []
        for key, grip, blk in hand_poses(head, axis, reach, held):
            hit = sum(vol(p, o) for p in (key, grip, blk) for o in obstacles if o.is_watertight)
            d = min(tree.query(p.sample(1500))[0].min() for p in (key, grip, blk))
            cl.append(-1.0 if hit > 0.5 else d)
        cl = np.array(cl)
        for s in range(24):
            m = min(cl[(s + k) % 24] for k in range(5))          # 5 poses = 60 deg
            if best is None or m > best[2]:
                best = (way, s * 15, m)
    print('  %-26s %-8s from %3d deg   min clearance %5.1f mm  %s' % (name, best[0], best[1], best[2], 'OK' if best[2] >= 0 else 'FAIL'))
    return best


def fit_check():
    P = {k: v['mesh'] for k, v in PARTS.items()}
    jaw = P['jaw']
    print('\n=========== FIT CHECK (rev 2) ===========')
    print('F1 cranium screws vs stand')
    for x, y in ((24, 113), (-24, 113)):
        d = np.hypot(x - STAND_AX[0], y - STAND_AX[1])
        print('  screw (%g, %g): %.1f from the stand axis; flange edge %.1f, column + grip %.1f' %
              (x, y, d, d - FLANGE_R - 2.75, d - COLUMN_R - GRIP_R))
    obs15 = [P['stand'], jaw, P['base']]
    hand_check('cranium screw (24, 113)', (24, 113, -41), (0, 0, -1), obs15)
    for a in (0.0, 10.0, 20.0):
        hand_check('face screw (12, 44), jaw %g' % a, (12, 44, -41), (0, 0, -1), [P['stand'], rot_jaw(jaw, a), P['base']])
    hand_check('filler screw (40, 90)', (40, 90, -44), (0, 0, -1), obs15)
    hand_check('stand screw (22, 97), above', (22, 97, -40), (0, 0, 1), [P['base']])
    hand_check('servo bracket screw (13, 52)', (13, 52.3, -33), (0, 0, 1), [P['base'], P['servo_bracket'], P['servo']])
    hand_check('pivot bracket screw (-22, 59.5)', (-22.25, 59.5, -33), (0, 0, 1), [P['base'], P['pivot_bracket']])
    hand_check('stop screw, from -X', (-34, 83, -30), (-1, 0, 0), [P['base'], P['pivot_bracket'], jaw, P['front_module']])
    print('F2 inserts: bore %.1f mm vs designed stock' % BORE)
    for part, ax, p, d in INSERTS:
        s = INSERT_STOCK[part]
        print('  %-14s %s at (%6.1f %6.1f %6.1f): stock %.1f, floor under bore %.1f %s' % (part, ax, *p, s, s - BORE, 'OK' if s - BORE >= 1.0 else 'FAIL'))
    print('F3 servo stack')
    sv = P['servo']
    print('  tab bottom %.2f, pocket floor -41.00: %.2f clear' % (sv.bounds[0, 2], sv.bounds[0, 2] + 41.0))
    print('  lower tab hole z -37.93 to wall bottom -41.0: %.2f of wall under the Ø2 hole (min 1.6)' % (-37.93 - 1.0 + 41.0))
    print('  servo vs base %.2f mm3, bracket vs base %.2f mm3, servo vs bracket %.2f mm3' %
          (vol(sv, P['base']), vol(P['servo_bracket'], P['base']), vol(sv, P['servo_bracket'])))
    print('  servo case bottom -35.43 vs foot top -33 (foot is in front of the case, y < 56.1): case y min %.2f' % sv.bounds[0, 1])
    print('F4 stop block and pivot bracket vs jaw')
    worst = {}
    for a in np.arange(STOP_CLOSE, STOP_OPEN + 0.01, 1.5):
        J = rot_jaw(jaw, a)
        for k in ('stop_block', 'pivot_bracket', 'base', 'servo_bracket', 'front_module', 'fillers'):
            worst[k] = max(worst.get(k, 0), vol(J, P[k]))
    for k, v in worst.items():
        print('  jaw sweep %.1f..%.1f deg vs %-14s overlap %.2f mm3 %s' % (STOP_CLOSE, STOP_OPEN, k, v, 'OK' if v < 0.05 else 'FAIL'))
    sb = P['stop_block']
    for a in (STOP_CLOSE + 0.6, STOP_OPEN - 0.6):
        print('  gap at %.1f deg (just inside the stop): %.2f mm' % (a, gap(rot_jaw(jaw, a), sb)))
    for a in (STOP_CLOSE - 1.0, STOP_OPEN + 1.0):
        print('  overlap at %.1f deg (past the stop, should be > 0): %.2f mm3' % (a, vol(rot_jaw(jaw, a), sb)))
    ins = max(vol(jaw, sb.copy().apply_translation([0, dy, 0])) for dy in np.arange(0, 25.1, 1.0))
    print('  stop slid in from +Y 25 mm (jaw closed): max overlap %.2f mm3 %s' % (ins, 'OK' if ins < 0.05 else 'FAIL'))
    print('  stop vs pivot bracket overlap %.2f mm3; gap jaw(closed)-pivot bracket %.2f mm' % (vol(sb, P['pivot_bracket']), gap(jaw, P['pivot_bracket'])))
    print('F5 pivot bracket on the plate: body x min -26.5 vs plate edge -30 (y < 81): 3.5 inside; nose r 4 above the plate')
    print('F6 inserts: %d total = %s' % (len(INSERTS), ', '.join('%s %d' % (k, sum(1 for i in INSERTS if i[0] == k)) for k in INSERT_STOCK)))
    print('F7 stand z -136..-44: %.0f tall, Ø110 base, Ø56 x 8 flange' % (-44 + 136))
    print('F8 S1 lower arc: fillers cover |x| 36..50 below z -19, y 81..100; jaw sweep to filler gap %.1f mm' %
          min(gap(rot_jaw(jaw, a), P['fillers']) for a in SWEEP))
    print('F9 plate wing |x| 49.5 vs bay edge 50: 0.5 slit; jaw sweep to plate gap %.1f mm' %
          min(gap(rot_jaw(jaw, a), P['base']) for a in SWEEP))
    print('F10 front module')
    print('  USB plug vs front module overlap %.2f mm3' % vol(P['usb_plug'], P['front_module']))
    print('  ledges |x| 25..31: reach 6.0 from the arm, 2.5 under each board end; housings |x| <= 25')
    free = 100.0 - 14.0 - 4.0; worst = 0
    for name, (s, run, sig) in LEADS.items():
        a = s + np.array([0, run, 0])
        worst = max([worst] + [run + 5.0 + 1.15 * np.linalg.norm(pin_xyz(h, p) - a) for h, p in sig.values()])
    print('  LCD leads: longest route %.0f of %.0f free -> min slack %.0f mm (target 15-20)' % (worst, free, free - worst))
    print('  USB cable vs pivot bracket %.2f mm3, vs servo bracket %.2f mm3' %
          (vol(cyl_path(USB_ROUTE, 2.25), P['pivot_bracket']), vol(cyl_path(USB_ROUTE, 2.25), P['servo_bracket'])))
    print('Spine vs finger: jaw sweep vs base above (in F4 "base")')


def cyl_path(pts, r):
    return union(*[cyl(a, b, r, 12) for a, b in zip(pts[:-1], pts[1:])])


STEPS = [
    "Bench: press in the 15 inserts (8 base, 2 pivot bracket, 3 front module, 2 stand)",
    "Base onto the stand: spigot into the counterbore, 2 screws from above",
    "Bench: servo into its bracket, horn on",
    "Servo bracket onto the base: wall into the plate pocket, 2 screws from above",
    "Pivot bracket onto the base, 2 screws from above",
    "Bench: front module (eye bar, LCDs, ESP32, wires, USB)",
    "Front module onto the spine: lower, slide back, 2 screws from behind",
    "Plug the servo lead into the ESP32",
    "Jaw up from below onto the horn and pivot",
    "Stop block: slide forward onto the finger, 1 screw from outside -X",
    "Bench test",
    "Radar into the face shell, plug in its lead",
    "Face shell: slide straight back 110 mm, 2 screws from below",
    "Mastoid fillers: in from behind onto the plate wings, 1 screw each from below",
    "Cranium shell: slide forward 15 mm, 2 screws from below",
]


if __name__ == '__main__':
    shells(); liners(); chassis(); screws_and_wires()
    fit_check()
    meta = dict(parts=[], lines=LINES, steps=STEPS)
    for name, p in PARTS.items():
        m = p.pop('mesh'); m.export(os.path.join(OUT, name + '.stl'))
        meta['parts'].append(dict(name=name, tris=len(m.faces), **p))
    json.dump(meta, open(os.path.join(OUT, 'meta.json'), 'w'))
    print('wrote', OUT)
