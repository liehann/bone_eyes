"""Rough v2 mock-up: one approximate mesh per part from docs/skull-v2-architecture.md,
in the assembled eye frame (-Y = face direction, +X = skull left, +Z up).

Shells come from the v1 assembled meshes (hardware/skull/cache/render, symlinked
from the main checkout) cut at the seam plane y = 100. The mechanical parts are
boxes, cylinders and hulls: for reviewing layout, not printable.

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
    add('face_shell', fs, 'Face shell', 'shells', '#efe6cf', (0, -130, 0), 14, shell=True, flat=False)
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
    add('liners', cat(*ls), 'Liners (eyes, nose)', 'shells', '#1c1c1c', (0, -130, 0), 14, flat=False)
    add('radar', load('radar', 100), 'Radar module', 'hardware', '#e04a2a', (0, -130, 0), 13)


# ---------------------------------------------------------------- chassis
def chassis():
    plate = union(box((-30, 48, -44), (30, 80, -40)), box((-46, 80, -44), (46, 104, -40)))
    plate = trimesh.boolean.difference([plate, cyl((0, 90, -45), (0, 90, -39), 8)], engine='manifold')
    ftong = hull_yz([(48, -44), (48, -40), (42, -34), (38, -34), (38, -38), (42, -38)], -22, 22)
    rtong = hull_yz([(104, -44), (104, -40), (110, -34), (116, -34), (116, -38), (110, -38)], -30, 30)
    spine = cat(box((-30, 72, -40), (30, 76, -19)), box((-35, 72, -19), (35, 76, 27)))
    base = union(plate, ftong, rtong, spine)
    add('base', base, 'Chassis base', 'chassis', '#8d949c', (0, 0, 0), 1)

    inserts = []
    for x, y in [(6, 58), (22, 72), (-24, 58), (-24, 72), (12, 44), (-12, 44), (20, 110), (-20, 110), (24, 90), (-24, 90)]:
        z0 = -34 if abs(y - 44) < 1 or y == 110 else -40       # tongues are joggled up
        inserts.append(cyl((x, y, z0 - 6.7), (x, y, z0), 2.0, 12))
    for s in (-1, 1):
        inserts.append(cyl((s * 33, 72, 10), (s * 33, 72 + 6.7, 10), 2.0, 12))     # module -> spine, Y axis
    inserts.append(cyl((-27.5, 21.2 - 6.7, 16), (-27.5, 21.2, 16), 2.0, 12))       # bar bolt
    inserts.append(cyl((-31.5, 65.13, -29.43), (-24.8, 65.13, -29.43), 2.0, 12))   # pivot, X axis
    inserts.append(cyl((-31.5, 58, -22), (-24.8, 58, -22), 2.0, 12))               # stop block, X axis
    add('inserts', cat(*inserts), 'Heat-set inserts (15)', 'chassis', '#d8a31c', (0, 0, 0), 1)

    # front module
    arms = [box((31, 27, -4), (35, 72, 27)), box((-35, 27, -4), (-31, 72, 27))]
    posts = [cyl((s * 27.5, 12, 16), (s * 27.5, 21.2, 16), 4.5, 24) for s in (-1, 1)]
    ledges = [box((24, 36, 20), (31, 58, 22)), box((-31, 36, 20), (-24, 58, 22))]
    mod = cat(box((-35, 10, 23), (35, 30, 27)), box((-8, 10, 27), (8, 24, 32)), *arms, *posts, *ledges)
    add('front_module', mod, 'Front module (brow, arms, key)', 'chassis', '#4f8f6f', (0, -40, 60), 7)
    bar = load('bar', 8000)
    add('eye_bar', bar, 'Eye bar', 'hardware', '#7a8088', (0, -75, 60), 7)
    mods = cat(load('modules', 2000), load('screens', 1000))
    add('lcds', mods, 'LCD modules', 'hardware', '#e3b41f', (0, -105, 60), 7)

    esp = cat(box((-27.5, 33.4, 22), (27.5, 61.4, 23.6)),
              box((-25, 34.5, 5.5), (25, 37.5, 22)), box((-25, 57.3, 5.5), (25, 60.3, 22)),
              box((-27.5, 44, 23.6), (-12, 52, 27)))
    add('esp32', esp, 'ESP32 board + housings', 'hardware', '#1f9e94', (0, -40, 100), 7)
    add('usb_plug', box((-36, 42, 8), (-27.5, 53, 26)), '90 deg USB plug', 'hardware', '#c9c93a', (0, -40, 100), 7)

    # servo mechanism
    serv = cat(load('servo', 1000))
    add('servo', serv, 'Servo (MG90S)', 'hardware', '#3f6fd8', (15, 0, 70), 4)
    add('horn', load('horn', 500), 'Servo horn', 'hardware', '#d0303c', (15, 0, 70), 4)
    sb = cat(box((1, 55, -40), (27, 75, -38)), box((1, 59, -38), (3.6, 71.2, -8)), box((24, 59, -38), (27, 71.2, -8)))
    add('servo_bracket', sb, 'Servo bracket', 'chassis', '#2fb0c8', (15, 0, 70), 4)
    pb = cat(box((-31.5, 56, -40), (-16, 74, -38)), box((-31.5, 57, -38), (-28.5, 73, -18)))
    add('pivot_bracket', pb, 'Pivot bracket', 'chassis', '#2f8fc8', (-15, 0, 70), 6)
    add('stop_block', box((-43.5, 51, -29), (-31.5, 67, -15)), 'Stop block', 'chassis', '#c86a2f', (-60, 0, 0), 11)

    # jaw
    add('jaw', load('jaw', 60000), 'Jaw', 'jaw', '#d7b98c', (0, 0, -70), 10, flat=False)

    # stand with the new top flange
    st = load('stand', 5000)
    st = st.slice_plane([0, 0, -52], [0, 0, -1], cap=True)
    top = cat(cyl((0, 90, -52), (0, 90, -50), 19, 40), cyl((0, 90, -50), (0, 90, -44), 28, 48),
              cyl((0, 90, -44), (0, 90, -41), 15, 40))
    add('stand', cat(st, top), 'Stand (new top flange)', 'chassis', '#b79a78', (0, 0, -60), 2)


# ---------------------------------------------------------------- screws and wires
def screws_and_wires():
    s = 1
    for sx in (-1, 1):
        screw('stand_%d' % sx, (sx * 24, 90, -51.5), (sx * 24, 90, -40), explode=(0, 0, -95), step=2)
        screw('face_%d' % sx, (sx * 12, 44, -43), (sx * 12, 44, -29), explode=(0, 0, -75), step=14)
        screw('cranium_%d' % sx, (sx * 20, 110, -43), (sx * 20, 110, -29), explode=(0, 0, -75), step=15)
        screw('spine_%d' % sx, (sx * 33, 77.5, 10), (sx * 33, 66, 10), explode=(0, 50, 0), step=8)
    for i, (x, y) in enumerate([(6, 58), (22, 72)]):
        screw('servobkt_%d' % i, (x, y, -36), (x, y, -46), explode=(15, 0, 95), step=5)
    for i, (x, y) in enumerate([(-24, 58), (-24, 72)]):
        screw('pivotbkt_%d' % i, (x, y, -36), (x, y, -46), explode=(-15, 0, 95), step=6)
    screw('bar_bolt', (-27.5, 29.5, 16), (-27.5, 16.5, 16), r=1.5, headr=4.5, explode=(0, -35, 60), step=7)
    screw('pivot_pin', (-51, HINGE[0], HINGE[1]), (-28.5, HINGE[0], HINGE[1]), explode=(-80, 0, 0), step=10)
    screw('horn_a', (51, HINGE[0] - 3, -40), (35, HINGE[0] - 3, -40), r=1.0, headr=2.0, explode=(80, 0, 0), step=10)
    screw('horn_b', (51, HINGE[0] + 1, -32), (35, HINGE[0] + 1, -32), r=1.0, headr=2.0, explode=(80, 0, 0), step=10)
    screw('stop_screw', (-45.5, 58, -22), (-35.5, 58, -22), explode=(-100, 0, 0), step=11)

    # LCD leads (wiring.py datums): out of the bar, a straight run, then across under the J3 housings to the pin
    cols = ['#ff9f1c', '#2ec4b6', '#e71d36', '#9b5de5', '#f15bb5', '#00bbf9', '#8ac926', '#ffd166']
    for li, (name, (st, run, sig)) in enumerate(LEADS.items()):
        for k, (sname, (h, p)) in enumerate(sig.items()):
            pin = pin_xyz(h, p)
            a = st + np.array([0, 0, 0.0]); a = a + np.array([0, 0, 0.0])
            z = (k - 3.5) * 0.9
            p1 = np.array([st[0], st[1] + run, z]); p2 = np.array([pin[0], max(st[1] + run + 2, pin[1] - 3), z])
            p3 = np.array([pin[0], pin[1], z]); p4 = np.array([pin[0], pin[1], 5.5])
            line('lcd_%d_%s' % (li, sname), 'wires', [[st[0], st[1], z], p1, p2, p3, p4], 0.45, cols[k],
                 (0, -40, 60), 7, 'LCD %s %s' % ('L' if li == 0 else 'R', sname))
    # USB cable: plug, down the -X arm, back along the plate, through the spine notch, plate hole, stand
    line('usb_cable', 'wires', [(-31, 47.5, 8), (-33, 47.5, -10), (-32, 56, -34), (-12, 66, -37), (-12, 74, -37),
                                (0, 90, -40), (0, 90, -110)], 2.25, '#d9d9d9', (0, 0, 0), 8, 'USB cable')
    sv = np.array([15, 71.2, -30]); r = pin_xyz('J2', 11)
    line('servo_lead', 'wires', [sv, (15, 67, -30), (r[0], 64, -10), (r[0], r[1], 0), (r[0], r[1], 5.5)], 0.8, '#d49a3a',
         (15, 0, 70), 9, 'Servo lead')
    for p in (5, 7, 8):
        r = pin_xyz('J2', p)
        line('radar_%d' % p, 'wires', [(0, 6.4, -27.5), (0, 12, -27.5), (0, 40, -27.5), (r[0], 52, -12), (r[0], r[1], -4), (r[0], r[1], 5.5)],
             0.45, '#e04a2a', (0, -130, 0), 13, 'Radar lead')


# ---------------------------------------------------------------- checks
def checks():
    jaw = PARTS['jaw']['mesh']
    print('--- jaw vertices inside doc envelopes (should be 0 unless noted)')
    for n, (a, b) in {'plate': ((-30, 48, -44), (30, 80, -40)), 'plate_rear': ((-46, 80, -44), (46, 104, -40)),
                      'spine<-19': ((-30, 72, -40), (30, 76, -19)), 'face flange (J2)': ((-25, 38, -41), (25, 48, -38)),
                      'servo bracket': ((1, 55, -40), (27, 75, -38)), 'stop block': ((-43.5, 51, -29), (-31.5, 67, -15)),
                      'pivot bracket wall': ((-31.5, 57, -38), (-28.5, 73, -18))}.items():
        v = jaw.vertices
        k = ((v >= a) & (v <= b)).all(1).sum()
        print('  %-18s %d' % (n, k))
    print('knuckle |x| range near hinge:')
    v = jaw.vertices; m = (abs(v[:, 1] - HINGE[0]) < 12) & (abs(v[:, 2] - HINGE[1]) < 12)
    print('  x %.1f..%.1f / %.1f..%.1f' % (v[m & (v[:, 0] < 0)][:, 0].min(), v[m & (v[:, 0] < 0)][:, 0].max(),
                                           v[m & (v[:, 0] > 0)][:, 0].min(), v[m & (v[:, 0] > 0)][:, 0].max()))
    d = np.hypot(20, 20)
    print('cranium screw to stand axis %.1f mm, stand flange r 28, column r 19' % d)
    print('bore 6.7 mm vs plate 4 mm')


STEPS = [
    "Bench: press in the 15 inserts",
    "Bench: stand onto the base (2 screws from the flange)",
    "Set the base down on the stand",
    "Bench: servo into its bracket, horn on",
    "Servo bracket onto the base, from above",
    "Pivot bracket onto the base, from above",
    "Bench: front module (eye bar, LCDs, ESP32, wires, USB)",
    "Front module onto the spine: lower, then slide back",
    "Plug the servo lead into the ESP32",
    "Jaw up from below onto the horn and pivot",
    "Stop block onto the pivot bracket",
    "Bench test",
    "Radar into the face shell, plug in its lead",
    "Face shell: slide straight back 110 mm, 2 screws from below",
    "Cranium shell: slide forward 15 mm, 2 screws from below",
]


if __name__ == '__main__':
    shells(); liners(); chassis(); screws_and_wires(); checks()
    meta = dict(parts=[], lines=LINES, steps=STEPS)
    for name, p in PARTS.items():
        m = p.pop('mesh'); m.export(os.path.join(OUT, name + '.stl'))
        meta['parts'].append(dict(name=name, tris=len(m.faces), **p))
        print('%-16s %7d tris  bounds %s' % (name, len(m.faces), m.bounds.round(0).astype(int).tolist()))
    json.dump(meta, open(os.path.join(OUT, 'meta.json'), 'w'))
    print('wrote', OUT)
