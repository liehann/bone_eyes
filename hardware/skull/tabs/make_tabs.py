"""Retrofit locator tabs for the v1 skull covers.

Small printed strips super-glued to the INSIDE of one part along a seam. Half of
each tab (the glued half) follows that part's inner surface; the other half (the
tongue) sticks 7 mm past the seam edge and slips inside the mating part with
0.3 mm clearance. Glued to one part only, so the covers still come off.

    hardware/.venv/bin/python hardware/skull/tabs/make_tabs.py

Reads the printed meshes (out/face.stl, out/back.stl, out/cap.stl), moved into
the assembled frame the way assembly/scene.py does it (needs cache/render from
the main checkout for the frame). Writes tabs/out/*.stl, tabs/out/tabs_plate.stl,
tabs/placement.png and tabs/out/report.json.

Frame: -Y = face direction, +X = skull left, +Z up (mm).

Tongue shape: for every point of the tongue, the mating part's inner wall is
sampled along the whole fitting path still to come (cap: straight down the cut
normal; back cover: straight down onto the floor lip), and the tongue's outer
face is put 0.3 mm inside the nearest wall met on that path. So the tongue can't
catch the mating part on the way in, by construction. A separate sweep check of
the finished tab mesh confirms it.

Print pose: a tab whose outer face is gently curved gets a flat inner face (the
side that faces into the skull) and prints flat face down, curved glue face up.
A tab across a sharp bend (the temple tabs: about 45 deg through the seam) would
get too thick that way; it is a constant 1.6 mm strip printed on its long edge
instead. No support either way. The inner face carries the engraved tab number;
the notch in the outline marks the glued end.
"""
import os, sys, json, time
import numpy as np
import trimesh
import manifold3d as mf

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)
sys.path.insert(0, SK); sys.path.insert(0, os.path.join(SK, 'assembly'))
import build as B   # noqa: E402  (constants only; importing does not build)

OUTD = os.path.join(HERE, 'out'); os.makedirs(OUTD, exist_ok=True)
RENDER = os.path.join(SK, 'cache', 'render')

# ------------------------------------------------------------------ parameters
T_MIN = 1.6          # thinnest point of a tab (inner flat face to glue/outer face)
CLEAR = 0.3          # tongue outer face to mating wall, along the whole fitting path
W = 13.0             # tab width along the seam
L_GLUE = 8.0         # glued half, back from the seam edge
L_TONGUE = 7.0       # tongue, past the seam edge
R_CORNER = 3.0       # outline corner radius
FLAT_MAX_T = 3.2     # flat-backed tab thicker than this anywhere -> constant-thickness strip, printed on edge
TIP = 0.5            # tongue tip thickness after the 45 deg lead-in chamfer
STEP = 0.5           # heightfield sample step (mm)
NUM_DEPTH = 0.4      # engraved number depth (bed face)
STEP_SWEEP = 0.5     # fitting-path sample step

n_seam, p_seam = B.seam()                                    # unit normal into the cap
tb = np.array([0, 1.0, -B.SEAM['slope']]); tb /= np.linalg.norm(tb)   # along the cut, backward
xh = np.array([1.0, 0, 0])
C_SEAM = np.array([0, 65.0, B.seam_z(65.0)])                 # interior point on the cap cut


def unit(v):
    v = np.asarray(v, float); return v / np.linalg.norm(v)


# ------------------------------------------------------------------ meshes
def load_meshes():
    """Printed meshes (out/) moved into the assembled frame."""
    M = {}
    for n in ('face', 'back'):
        o = trimesh.load(os.path.join(SK, 'out', n + '.stl'))      # print pose = rx(0) + translation
        r = trimesh.load(os.path.join(RENDER, n + '.stl'))
        o.apply_translation(r.bounds.mean(0) - o.bounds.mean(0))
        M[n] = o
    c = trimesh.load(os.path.join(SK, 'out', 'cap.stl'))           # same recipe as assembly/scene.py
    a = np.degrees(np.arctan2(n_seam[1], n_seam[2]))
    c.apply_transform(trimesh.transformations.rotation_matrix(np.radians(-a), [1, 0, 0]))
    ref = trimesh.load(os.path.join(RENDER, 'cap.stl'))
    bc, br = c.bounds, ref.bounds
    c.apply_translation([(br[0, 0] + br[1, 0] - bc[0, 0] - bc[1, 0]) / 2, br[1, 1] - bc[1, 1], br[1, 2] - bc[1, 2]])
    M['cap'] = c
    # inside parts the tabs must keep clear of (static; nothing here moves past a tab)
    for n in ('bar', 'modules', 'screens', 'servo_tray', 'esp32'):
        M[n] = trimesh.load(os.path.join(RENDER, n + '.stl'))
    M['esp32_floor'] = trimesh.creation.box(bounds=[[-48, 34, -14.6], [-20, 89, -10.0]])   # scene.py's ESP32 spot
    return M


def crop(m, c, r):
    keep = np.all(np.abs(m.triangles_center - c) < r, axis=1)
    return m.submesh([np.nonzero(keep)[0]], append=True) if keep.any() else None


def first_hit(m, O, D):
    """Distance along D to the first hit on m for each ray (inf if none)."""
    out = np.full(len(O), np.inf)
    if m is None or len(O) == 0:
        return out
    loc, ir, _ = m.ray.intersects_location(O, D, multiple_hits=True)
    if len(ir):
        t = np.einsum('ij,ij->i', loc - O[ir], D[ir])
        ok = t > 1e-6
        np.minimum.at(out, ir[ok], t[ok])
    return out


# ------------------------------------------------------------------ tab specs
# glued: part the tab is glued to. mating: part the tongue goes into.
# approach: direction the mating part comes FROM, relative to the glued part
# (cap: from above along the cut normal; face relative to the falling back
# cover: from below). T: how far back along the path to look.
def cap_spec(name, az, glued):
    a = np.radians(az)
    N0 = unit(-np.cos(a) * tb + np.sin(a) * xh)
    return dict(name=name, glued=glued, mating='cap', O=C_SEAM, N0=N0, V0=n_seam, approach=n_seam, T=L_TONGUE + 1.0,
                seam='cap/' + glued, where='az %d' % az)


def temple_spec(name, side, z):
    O = np.array([0, B.Y_BACK, z])
    return dict(name=name, glued='back', mating='face', O=O, N0=np.array([side, 0, 0.]), V0=np.array([0, -1.0, 0]),
                approach=np.array([0, 0, -1.0]), T=40.0, seam='back/face', where='z %d' % z)


# +X is skull left (L), -X skull right (R)
SPECS = [
    cap_spec('cap_front_R', -28, 'face'), cap_spec('cap_front_L', 28, 'face'),
    cap_spec('cap_side_R', -75, 'back'), cap_spec('cap_side_L', 75, 'back'),
    cap_spec('cap_rear_R', -140, 'back'), cap_spec('cap_rear_L', 140, 'back'),
    temple_spec('back_temple_upper_R', -1, 21.0), temple_spec('back_temple_upper_L', 1, 21.0),
    temple_spec('back_temple_lower_R', -1, 7.0), temple_spec('back_temple_lower_L', 1, 7.0),
]
for i, s in enumerate(SPECS):
    s['num'] = i + 1


# ------------------------------------------------------------------ geometry
def seam_point(s, Mg, Mm):
    O, N0, V0 = s['O'], s['N0'], unit(s['V0'] - np.dot(s['V0'], s['N0']) * s['N0'])
    hg = first_hit(Mg, np.array([O - V0 * 1.5]), np.array([N0]))[0]
    hm = first_hit(Mm, np.array([O + V0 * 1.5]), np.array([N0]))[0]
    return O + N0 * (0.5 * (hg + hm))


def frame(N, V0):
    N = unit(N); V = unit(V0 - np.dot(V0, N) * N); U = np.cross(V, N)
    return U, V, N


def heightfield(s, s0, U, V, N, Mg, Mm):
    """Outer (glue / wall-side) surface as height along N above the plane through s0."""
    us = np.arange(-W / 2 - 1, W / 2 + 1 + 1e-6, STEP)
    vs = np.arange(-L_GLUE - 1, L_TONGUE + 1 + 1e-6, STEP)
    UU, VV = np.meshgrid(us, vs, indexing='ij')
    BASE = s0 + UU[..., None] * U + VV[..., None] * V - 12.0 * N
    H = np.full(UU.shape, np.nan)
    g = VV <= 0
    # glued half: the ray right at the cut edge grazes the cut face, so sample no
    # closer than 0.5 mm to the edge
    Bg = BASE + np.minimum(0.0, -0.5 - VV)[..., None] * V
    hg = first_hit(Mg, Bg[g], np.tile(N, (g.sum(), 1))) - 12.0
    H[g] = hg
    from scipy import ndimage
    Hg = np.where(g & np.isfinite(H), H, np.nan)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        med = ndimage.generic_filter(Hg, np.nanmedian, size=3, mode='nearest')
    H[g] = np.fmin(med[g], Hg[g])         # drop one-sample pits (scan noise); never pushes into the wall
    # tongue: nearest mating wall over the fitting path still to come
    t_ = np.arange(0, s['T'] + 1e-6, STEP_SWEEP)
    tg = VV > -1.25          # (the band just behind the cut edge too: the mating part's cut face can sit there)
    P = BASE[tg]
    O = (P[:, None, :] - s['approach'][None, None, :] * t_[None, :, None]).reshape(-1, 3)
    hm = first_hit(Mm, O, np.tile(N, (len(O), 1))).reshape(len(P), len(t_)) - 12.0
    # only path points where the ray starts in the cavity (behind the wall) count
    hm[hm < -10.0] = np.inf
    Ht = np.full(UU.shape, np.inf); Ht[tg] = hm.min(1) - CLEAR
    H[~g] = Ht[~g]
    H[g] = np.fmin(H[g], Ht[g])
    return us, vs, H


def outline_mask(us, vs, pad=0.0):
    UU, VV = np.meshgrid(us, vs, indexing='ij')
    vc = (L_TONGUE - L_GLUE) / 2; hl = (L_TONGUE + L_GLUE) / 2 + pad; hw = W / 2 + pad
    du = np.maximum(np.abs(UU) - (hw - R_CORNER), 0); dv = np.maximum(np.abs(VV - vc) - (hl - R_CORNER), 0)
    return (du ** 2 + dv ** 2) <= R_CORNER ** 2


def fill_nan(H, mask_needed, name):
    bad = ~np.isfinite(H)
    if (bad & mask_needed).any():
        print('  WARNING %s: %d samples without a wall hit inside the outline' % (name, (bad & mask_needed).sum()))
    if bad.any():
        from scipy import ndimage
        idx = ndimage.distance_transform_edt(bad, return_distances=False, return_indices=True)
        H = H[tuple(idx)]
    return H


def hf_manifold(us, vs, Z, zbot=-1.0):
    """Closed heightfield solid: top z = Z(u, v), bottom z = zbot (scalar or array)."""
    nu, nv = Z.shape
    UU, VV = np.meshgrid(us, vs, indexing='ij')
    top = np.c_[UU.ravel(), VV.ravel(), Z.ravel()]
    bot = np.c_[UU.ravel(), VV.ravel(), np.broadcast_to(zbot, Z.shape).ravel()]
    Vt = np.vstack([top, bot]); off = nu * nv
    idx = np.arange(nu * nv).reshape(nu, nv)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
    F = [np.c_[a, b, c], np.c_[a, c, d], np.c_[a + off, c + off, b + off], np.c_[a + off, d + off, c + off]]
    def side(ring):
        r0, r1 = ring[:-1], ring[1:]
        return [np.c_[r0, r0 + off, r1], np.c_[r1, r0 + off, r1 + off]]
    ring = np.r_[idx[:, 0], idx[-1, 1:], idx[::-1, -1][1:], idx[0, ::-1][1:]]    # CCW from below? fixed below
    F += side(ring)
    F = np.vstack(F)
    t = trimesh.Trimesh(Vt, F, process=False)
    if t.volume < 0:
        t.invert()
    trimesh.repair.fix_normals(t)
    m = mf.Manifold(mf.Mesh(vert_properties=np.asarray(t.vertices, np.float32), tri_verts=np.asarray(t.faces, np.uint32)))
    assert m.status() == mf.Error.NoError and m.volume() > 0, m.status()
    return m


def rounded_rect(square_low_u=False):
    """Tab outline in (u, v). square_low_u: keep the u = -W/2 edge's corners square
    (that edge is the bed face when the tab prints on its edge)."""
    vc = (L_TONGUE - L_GLUE) / 2; hl = (L_TONGUE + L_GLUE) / 2; hw = W / 2
    cs = mf.CrossSection.square([2 * (hw - R_CORNER), 2 * (hl - R_CORNER)], center=True).offset(
        R_CORNER, mf.JoinType.Round, 2.0, 64)
    if square_low_u:
        cs = cs + mf.CrossSection.square([hw, 2 * hl]).translate([-hw, -hl])
    return cs.translate([0, vc])


# 7-segment digits: segments a..g as (x0, y0, x1, y1) in a 1 x 2 box
SEG = dict(a=(0, 2, 1, 2), b=(1, 2, 1, 1), c=(1, 1, 1, 0), d=(0, 0, 1, 0), e=(0, 0, 0, 1), f=(0, 1, 0, 2), g=(0, 1, 1, 1))
DIG = {0: 'abcdef', 1: 'bc', 2: 'abged', 3: 'abgcd', 4: 'fgbc', 5: 'afgcd', 6: 'afgedc', 7: 'abc', 8: 'abcdefg', 9: 'abcdfg'}


def number_cut(num, vc, h=3.6, sw=0.7, z0=-1.0, z1=NUM_DEPTH):
    """Engraving for the flat (bed) face. Reads right way round when the flat face is
    viewed from inside the skull (looking along +N, V up): screen x = -u."""
    s = h / 2; dw = s * 1.0; gap = 0.9
    digits = [int(c) for c in str(num)]
    tot = len(digits) * dw + (len(digits) - 1) * gap
    out = None
    for k, dg in enumerate(digits):
        x0 = -tot / 2 + k * (dw + gap)
        for sg in DIG[dg]:
            a0, b0, a1, b1 = SEG[sg]
            xa, xb = sorted((x0 + a0 * dw, x0 + a1 * dw)); ya, yb = sorted((b0 * s, b1 * s))
            box = mf.Manifold.cube([xb - xa + sw, yb - ya + sw, z1 - z0]).translate(
                [xa - sw / 2, ya - sw / 2 + vc - s, z0])
            out = box if out is None else out + box
    return out.mirror([1, 0, 0])     # screen x = -u


def build_tab(s, M):
    t0 = time.time()
    Mg_full, Mm_full = M[s['glued']], M[s['mating']]
    s0 = seam_point(s, Mg_full, Mm_full)
    r = 30.0 + (s['T'] if s['T'] > 20 else 0)
    Mg, Mm = crop(Mg_full, s0, r), crop(Mm_full, s0, r)
    U, V, N = frame(s['N0'], s['V0'])
    for it in range(2):             # second pass: N = normal of the best-fit plane of the outer surface
        us, vs, H = heightfield(s, s0, U, V, N, Mg, Mm)
        mask = outline_mask(us, vs, pad=0.3)
        H = fill_nan(H, mask, s['name'])
        UU, VV = np.meshgrid(us, vs, indexing='ij')
        A = np.c_[np.ones(mask.sum()), UU[mask], VV[mask]]
        coef = np.linalg.lstsq(A, H[mask], rcond=None)[0]
        if it == 0:
            Nn = unit(-coef[1] * U - coef[2] * V + N)
            s0 = s0 + coef[0] * N
            U, V, N = frame(Nn, s['V0'])
    v_tip = L_TONGUE
    flat_max = float((H[mask] - H[mask].min()).max()) + T_MIN
    edge = flat_max > FLAT_MAX_T        # too curved for a flat back: constant 1.6 strip, printed on its edge
    if not edge:
        w0 = H[mask].min() - T_MIN
        Z = H - w0                                   # height above the flat inner face
        Zb = 0.0
    else:
        w0 = 0.0
        Z = H.copy(); Zb = H - T_MIN
    Z = np.minimum(Z, Zb + TIP + (v_tip - VV))       # 45 deg lead-in on the outer face at the tongue tip
    Z = np.maximum(Z, Zb + TIP)
    solid = hf_manifold(us, vs, Z, Zb if edge else 0.0)
    prism = mf.Manifold.extrude(rounded_rect(square_low_u=edge), 80.0).translate([0, 0, -40.0])
    tab = solid ^ prism
    notch = mf.Manifold.extrude(mf.CrossSection([[[-1.5, -L_GLUE - 0.5], [1.5, -L_GLUE - 0.5], [0, -L_GLUE + 2.0]]]),
                                80.0).translate([0, 0, -40])
    tab = tab - notch
    vc_num = -L_GLUE / 2 + 0.4
    zb = np.broadcast_to(np.asarray(Zb, float), Z.shape)
    skin = hf_manifold(us, vs, zb + NUM_DEPTH, zb - 1.0)          # follows the inner face
    tab = tab - (number_cut(s['num'], vc=vc_num, z0=-40.0, z1=40.0) ^ skin)
    thick = (Z - Zb)[outline_mask(us, vs)]
    local = B.to_tri(tab)
    T = np.eye(4); T[:3, 0], T[:3, 1], T[:3, 2] = U, V, N; T[:3, 3] = s0 + w0 * N
    world = local.copy(); world.apply_transform(T)
    info = dict(print_pose='on its edge (u = -W/2 side down)' if edge else 'flat face down', num=s['num'], name=s['name'], seam=s['seam'], glued=s['glued'], mating=s['mating'], where=s['where'],
                seam_point=np.round(s0, 1).tolist(), outward=np.round(N, 3).tolist(), toward_mating=np.round(V, 3).tolist(),
                thickness_min=round(float(thick.min()), 2), thickness_max=round(float(thick.max()), 2),
                volume_mm3=round(float(local.volume), 1))
    s['N_final'] = N; s['V_final'] = V; s['s0_final'] = s0; s['edge'] = edge
    local = print_pose(local, edge)
    print('  %-22s s0 %s  thick %.2f..%.2f  %.1fs' % (s['name'], np.round(s0, 1), thick.min(), thick.max(), time.time() - t0))
    return local, world, T, info


def print_pose(local, edge):
    """local frame (u, v, w): flat tabs already have their flat face on z = 0.
    Edge tabs: turn the u = -W/2 side onto the bed: (u, v, w) -> (-w, v, u)."""
    m = local.copy()
    if edge:
        R = np.eye(4); R[:3, :3] = [[0, 0, -1.0], [0, 1.0, 0], [1.0, 0, 0]]
        m.apply_transform(R)
    m.apply_translation([0, 0, -m.bounds[0, 2]])
    return m


# ------------------------------------------------------------------ checks
DIRS = np.array([[1.0, 0, 0], [-1.0, 0, 0], [0, 1.0, 0], [0, -1.0, 0], [0, 0, 1.0], [0, 0, -1.0]])


def penetration(m, pts, dirs=DIRS):
    """Depth of each point inside m (0 if outside). A point is inside when the first
    surface met along every one of the probe directions is left from the inside
    (hit normal along the ray). Works on crops (a ray that leaves the crop says
    'outside'). Depth = nearest of those hits."""
    if m is None or len(pts) == 0:
        return np.zeros(len(pts))
    inside = np.ones(len(pts), bool); depth = np.full(len(pts), np.inf)
    for d in dirs:
        idx = np.nonzero(inside)[0]
        if len(idx) == 0:
            break
        D = np.tile(d, (len(idx), 1))
        tri, ray, loc = m.ray.intersects_id(pts[idx], D, multiple_hits=True, return_locations=True)
        best = np.full(len(idx), np.inf); btri = np.full(len(idx), -1)
        if len(ray):
            t = (loc - pts[idx][ray]) @ d
            o = np.lexsort((t, ray)); ray, t, tri = ray[o], t[o], tri[o]
            first = np.r_[True, ray[1:] != ray[:-1]]
            best[ray[first]] = t[first]; btri[ray[first]] = tri[first]
        ok = btri >= 0
        ins = np.zeros(len(idx), bool)
        ins[ok] = (m.face_normals[btri[ok]] @ d) > 0
        inside[idx] = ins
        depth[idx] = np.minimum(depth[idx], best)
    return np.where(inside, depth, 0.0)


def check_tab(s, world, M, rng):
    pts = world.sample(500, seed=int(rng.integers(1 << 30)))
    pts = np.vstack([pts, world.vertices[rng.choice(len(world.vertices), min(200, len(world.vertices)), replace=False)]])
    c = world.bounds.mean(0)
    res = {}
    g = crop(M[s['glued']], c, 25.0)
    res['into_glued_part_mm'] = round(float(penetration(g, pts).max()), 2)
    # mating part along its fitting path (it ends in place: t = 0)
    path = s['approach']; T = 45.0 if s['mating'] == 'face' else 25.0
    mm = crop(M[s['mating']], c, 25.0 + T)
    worst = 0.0; worst_t = 0.0
    for t in np.arange(0.0, T + 1e-6, 1.0):
        p = penetration(mm, pts - path * t)
        if p.max() > worst:
            worst, worst_t = float(p.max()), float(t)
    res['mating_path_max_mm'] = round(worst, 2); res['mating_path_at_mm'] = worst_t
    # fitted clearance between the tongue's outer face and the mating wall (along the tab normal)
    N = s['N_final']; vv = (world.vertices - s['s0_final']) @ s['V_final']
    top = world.vertices[(world.vertex_normals @ N > 0.7) & (vv > 1.0) & (vv < L_TONGUE - 1.5)]
    if mm is not None and len(top):
        h = first_hit(mm, top, np.tile(N, (len(top), 1)))
        h = h[np.isfinite(h) & (h < 3.0)]
        res['tongue_gap_fitted_mm'] = [round(float(h.min()), 2), round(float(np.median(h)), 2)] if len(h) else None
    # tabs on the back cover travel down with it (from 60 mm up) past the face and the inside parts
    others = ['bar', 'modules', 'screens', 'servo_tray', 'esp32', 'esp32_floor']
    if s['glued'] == 'back':
        others = ['face'] + others
        travel = np.arange(0.0, 60.0 + 1e-6, 2.0)
    else:
        travel = [0.0]
    worst = {}
    for o in others:
        mo = crop(M[o], c, 25.0 + max(travel))
        if mo is None:
            continue
        w = 0.0
        for t in travel:
            w = max(w, float(penetration(mo, pts + np.array([0, 0, 1.0]) * t).max()))
        if o == 'face' and s['mating'] == 'face':
            continue   # covered above, with the tongue clearance
        worst[o] = round(w, 2)
    res['others_max_mm'] = worst
    # the cap comes down onto everything last: tabs on the back cover's front edge must stay clear of it
    if s['mating'] != 'cap':
        mc = crop(M['cap'], c, 50.0)
        w = 0.0
        for t in np.arange(0.0, 25.0 + 1e-6, 1.0):
            w = max(w, float(penetration(mc, pts - n_seam * t).max()))
        res['cap_path_max_mm'] = round(w, 2)
    ok = (res['mating_path_max_mm'] <= 0.05 and res['into_glued_part_mm'] <= 0.3 and
          all(v <= 0.05 for v in worst.values()) and res.get('cap_path_max_mm', 0) <= 0.05)
    res['ok'] = bool(ok)
    return res


# ------------------------------------------------------------------ plate + drawing
def plate(locals_):
    cols = 4; pitch_x, pitch_y = 22.0, 24.0
    ms = []
    for i, m in enumerate(locals_):
        m = m.copy()
        b = m.bounds
        m.apply_translation([-(b[0, 0] + b[1, 0]) / 2 + (i % cols) * pitch_x, -(b[0, 1] + b[1, 1]) / 2 - (i // cols) * pitch_y, -b[0, 2]])
        ms.append(m)
    P = trimesh.util.concatenate(ms)
    b = P.bounds
    P.apply_translation([-(b[0, 0] + b[1, 0]) / 2, -(b[0, 1] + b[1, 1]) / 2, 0])
    return P


def drawing(M, worlds, specs, fn):
    import lineart
    from PIL import Image, ImageDraw, ImageFont
    import scene
    dec = {k: scene._dec(M[k], 120000) for k in ('face', 'back', 'cap')}
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf', 30)
        fsm = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 24)
    except OSError:
        font = fsm = ImageFont.load_default()
    def nums(ks):
        return ', '.join(str(specs[k]['num']) for k in ks)
    on_face = [k for k, s_ in enumerate(specs) if s_['glued'] == 'face']
    back_top = [k for k, s_ in enumerate(specs) if s_['glued'] == 'back' and s_['mating'] == 'cap']
    back_front = [k for k, s_ in enumerate(specs) if s_['glued'] == 'back' and s_['mating'] == 'face']
    into_cap = [k for k, s_ in enumerate(specs) if s_['mating'] == 'cap']
    panels = [
        ('Face (chassis) from above-behind, cap and back cover off: glue tabs %s here, tongue pointing UP' % nums(on_face),
         'face', 200, 62, on_face),
        ('Back cover from above-front, cap off: glue tabs %s on its top edge, tongue pointing UP' % nums(back_top),
         'back', 0, 60, back_top),
        ('Back cover from the front: glue tabs %s on its front edge, tongue pointing FORWARD' % nums(back_front),
         'back', 0, 8, back_front),
        ('Cap from below (inside): where the tongues of %s go (nothing is glued to the cap)' % nums(into_cap),
         'cap', 180, -70, into_cap),
    ]
    imgs = []
    for title, part, az, el, ks in panels:
        parts = [(part, dec[part])] + [('t%d' % k, worlds[k]) for k in ks]
        styles = {('t%d' % k): 'hi' for k in ks}
        img, cam = lineart.render(parts, az, el, s=0.12, pad=14.0, styles=styles)
        im = Image.fromarray(img).convert('RGBA')
        bg = Image.new('RGBA', im.size, (255, 255, 255, 255)); bg.alpha_composite(im); im = bg.convert('RGB')
        d = ImageDraw.Draw(im)
        ctr = cam.project(dec[part].bounds.mean(0))[0]
        for k in ks:
            p = cam.project(worlds[k].vertices.mean(0))[0]
            v = p - ctr; v = v / (np.linalg.norm(v) + 1e-9)
            q = p + v * 70
            if part == 'back' and el < 20:      # front view: upper / lower pairs, push sideways
                q = p + np.array([np.sign(v[0]) * 80, 0])
            d.line([tuple(p), tuple(q)], fill=0, width=2)
            r = 20
            d.ellipse([q[0] - r, q[1] - r, q[0] + r, q[1] + r], fill='white', outline='black', width=3)
            tx = str(specs[k]['num'])
            bb = d.textbbox((0, 0), tx, font=font)
            d.text((q[0] - (bb[2] - bb[0]) / 2 - bb[0], q[1] - (bb[3] - bb[1]) / 2 - bb[1]), tx, fill='black', font=font)
        # pad and title
        W_, H_ = im.size
        out = Image.new('RGB', (W_ + 160, H_ + 220), 'white'); out.paste(im, (80, 130))
        d = ImageDraw.Draw(out)
        d.text((20, 20), title, fill='black', font=fsm)
        # skull left / right (L = +X)
        c3 = dec[part].bounds.mean(0)
        for lbl, sx in (("skull's L", 1), ("skull's R", -1)):
            q = cam.project(c3 + np.array([sx * 75.0, 0, 0]))[0] + [80, 130]
            q[0] = min(max(q[0], 10), out.size[0] - 120)
            d.text((q[0] - 40, q[1]), lbl, fill='black', font=fsm)
        imgs.append(out)
    Wt = max(i.size[0] for i in imgs)
    legend = ['%2d  %-20s  glued to %-5s  tongue into %s' % (s['num'], s['name'], s['glued'], s['mating']) for s in specs]
    legend_h = 40 + 30 * (len(legend) + 3)
    Ht = sum(i.size[1] for i in imgs) + legend_h
    sheet = Image.new('RGB', (Wt, Ht), 'white')
    y = 0
    for i in imgs:
        sheet.paste(i, ((Wt - i.size[0]) // 2, y)); y += i.size[1]
    d = ImageDraw.Draw(sheet)
    try:
        mono = ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', 22)
    except OSError:
        mono = fsm
    d.text((40, y + 10), 'Notched end + engraved number = glued half. Flat face (number) faces into the skull.', fill='black', font=fsm)
    for j, ln in enumerate(legend):
        d.text((40, y + 50 + 30 * j), ln, fill='black', font=mono)
    sheet = sheet.convert('L').point(lambda v: 0 if v < 128 else 255).convert('1')   # pure black and white
    sheet.save(fn)


def main():
    t0 = time.time()
    if '--draw-only' in sys.argv:          # redo placement.png from the tabs already in out/assembled
        M = load_meshes()
        worlds = [trimesh.load(os.path.join(OUTD, 'assembled', '%02d_%s.stl' % (s['num'], s['name']))) for s in SPECS]
        drawing(M, worlds, SPECS, os.path.join(HERE, 'placement.png'))
        return
    for d in (OUTD, os.path.join(OUTD, 'assembled')):
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            if f.endswith('.stl'):
                os.remove(os.path.join(d, f))
    M = load_meshes()
    print('meshes loaded %.1fs' % (time.time() - t0))
    rng = np.random.default_rng(1)
    locals_, worlds, infos = [], [], []
    for s in SPECS:
        loc, world, T, info = build_tab(s, M)
        info['check'] = check_tab(s, world, M, rng)
        print('   check', info['check'])
        locals_.append(loc); worlds.append(world); infos.append(info)
        loc.export(os.path.join(OUTD, '%02d_%s.stl' % (s['num'], s['name'])))
        world.export(os.path.join(OUTD, 'assembled', '%02d_%s.stl' % (s['num'], s['name'])))   # in the skull frame
    P = plate(locals_)
    P.export(os.path.join(OUTD, 'tabs_plate.stl'))
    print('plate bounds', np.round(P.bounds, 1).tolist())
    json.dump(dict(tabs=infos, plate_bounds=np.round(P.bounds, 1).tolist(),
                   all_ok=all(i['check']['ok'] for i in infos)), open(os.path.join(OUTD, 'report.json'), 'w'), indent=1)
    drawing(M, worlds, SPECS, os.path.join(HERE, 'placement.png'))
    print('done %.1fs, all ok: %s' % (time.time() - t0, all(i['check']['ok'] for i in infos)))


if __name__ == '__main__':
    main()
