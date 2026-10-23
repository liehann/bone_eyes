#!/usr/bin/env python3
"""bone_eyes skull: build the printable parts from Peter from Belgium's CC0 skull.

Run from anywhere:   hardware/.venv/bin/python hardware/skull/build.py
Outputs:             hardware/skull/out/*.stl, hardware/skull/*.png

Pipeline (each stage is a function below):
  1. load + union the source shells (cached in cache/), put the jaw in its
     articulated position (ICP fit of Peter's printable jaw onto the jaw
     inside skull_w_jaw.stl);
  2. measure the orbit centres at the rim and scale uniformly so they are
     EYE_SPACING apart; move the origin to the midpoint between the orbits;
  3. voxelise, add the closing walls (eye plates, nasal wall, choanae,
     foramen magnum ...), fill narrow gaps with recessed webs, flood-fill the
     outside air and keep a uniform shell under the visible surface;
  4. mesh the shell (original bone surface kept outside, marching cubes inside);
  5. split face / back, add joints, eye-bar posts, servo, jaw pivot, chassis,
     radar pocket, neck boss; make the jaw and the stand;
  6. verify (manifold, single body, collisions, jaw sweep, see-through) and
     render previews.

Coordinates of the outputs (before print orientation): mm, +Z up, the face
looks toward -Y, X = 0 on the midline, Y = 0 on the orbit rim plane, Z = 0 at
the orbit centre height.
"""
import os, sys, json, time, hashlib
import numpy as np
import trimesh
import manifold3d as mf
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from vox import voxelize  # noqa: E402

# =============================================================== PARAMETERS
SRC = os.path.join(HERE, '..', 'skull_src')
CRANIUM_SRC = 'peter_belgium_2770/skull_mesh.stl'
JAW_REF_SRC = 'peter_belgium_2770/skull_w_jaw.stl'          # articulated jaw (pose only)
JAW_SRC = ['gage_recut_293680/jaw_top.stl', 'gage_recut_293680/jaw_lower.stl']  # Peter's jaw

EYE_SPACING = 55.0      # screen centre to screen centre; sets the overall scale
ORBIT_RIM_MARGIN = 1.0  # orbit opening = contour this far behind the lateral rim crest (source mm)
VOX = 0.5               # voxel size for the shell processing (mm, after scaling)

# --- shell -----------------------------------------------------------------
SHELL_T = 2.6           # shell thickness under the visible surface
SMALL_CLOSE_R = 1.5     # closes sutures / pinholes before the shell is taken
WEB_CLOSE_R = 7.0       # gaps narrower than ~2x this get a recessed web
WEB_RECESS = 3.5        # web front face this far behind the bridged surface
WEB_T = 2.0             # web thickness
INNER_SKIN = 0.7        # marching-cubes inner layer starts this far below the voxel surface

# --- eyes ------------------------------------------------------------------
EYE_PLATE_DEPTH = 2.8   # front face of the eye plate behind the orbit rim plane
EYE_PLATE_T = 2.0       # eye plate thickness (bezel)
SCREEN_GAP = 0.6        # plate back face to glass
BEZEL_D = 19.2          # aperture in the eye plate (active circle 18.0, glass 20.12)
EYE_DZ = 0.0            # move both eyes up/down from the measured orbit centre

BASE_CLOSE_R = 15.0     # larger closing radius on the skull base (hidden on the stand)
BASE_ROI = dict(y_min=22.0, z_max=-8.0)   # base region: behind the palate, below the orbits
TEMPLE_CLOSE_R = 22.0   # closes the gap behind/under each zygomatic arch
TEMPLE_ROI = dict(abs_x_min=34.0, y_min=8.0, y_max=72.0, z_min=-50.0, z_max=2.0)
CAVITY_PROBE = (0.0, 75.0, 40.0)          # a point inside the brain cavity (leak check)

# --- nose / radar ------------------------------------------------------------
NASAL_RIM_Y = -6.0      # piriform aperture rim depth (eye frame)
NASAL_RECESS = 5.0      # nasal wall front face behind the aperture rim
NASAL_T = 1.8           # = radar window thickness
NASAL_SEEDS = [(-5.0, -28.0), (5.0, -28.0), (0.0, -22.0)]
NASAL_ROI = (-18.0, 18.0, -42.0, -10.0)   # x0, x1, z0, z1
EYE_PLUG_GROW = 5.0     # plug column = orbit opening grown by this (covers the brow overhang)
EYE_PLUG_DEPTH = 22.0
NASAL_PLUG_GROW = 2.0
NASAL_PLUG_DEPTH = 20.0

# --- jaw / servo -------------------------------------------------------------
JAW_OPEN_DEG = 18.0     # nominal opening (firmware range); stops at -STOP_MARGIN .. OPEN+STOP_MARGIN
JAW_STOP_MARGIN = 2.0   # open stop this far past JAW_OPEN_DEG
JAW_CLOSE_STOP = -0.5   # closed stop (teeth still TEETH_GAP - ~0.5 mm apart)
TEETH_GAP = 0.8         # closed-jaw clearance to the upper teeth
JAW_SWEEP_CLEAR = 1.2   # clearance of the cranium round the swept jaw
SERVO_SIDE = +1         # servo on +X (your right as you face the skull = the skull's left); pivot bolt on -X
# MG90S (TowerPro drawing): body 22.8 x 12.2, case height 22.7, tabs 32.5 long x 2.5 thick
# with their top 18.5 above the case bottom, holes 2.0 at 27.8 centres, output
# spline top 28.4 above the case bottom, shaft 6.0 from one end of the case.
SERVO = dict(L=22.8, W=12.2, H=22.7, tab_len=32.5, tab_top=18.5, tab_t=2.5, hole_sp=27.8,
             spline_top=28.4, shaft_off=6.0, bump_d=11.8)
HORN_R = 19.0           # swept radius of the horn arm (single or double arm horn)
HORN_T = 3.2            # spline top region to horn arm face (horn hub + arm)
SERVO_CLEAR = 0.75
PIVOT_BOLT = 'M3'

# --- eye bar (hardware/eye_mount.scad, mount_style = "skull") -------------
EYE_BAR_STL = os.path.join(HERE, '..', 'eye_mount.stl')
BAR_T = 5.65            # bar thickness = M2x8 screw stack
STANDOFF_H = 3.0        # module standoff height (estimate, see hardware/README.md)
MODULE_T = 3.2          # PCB back to glass front (estimate)
BAR_HOLES = [(0.0, 0.0), (-27.5, 16.0), (27.5, 16.0)]   # = skull_mount_holes in the scad
BAR_PLATE = dict(half_w=27.5 + 0.14 + 4.0, half_h=11.6, boss_d=9.0, slot=3.0)
MODULE_ROT = 90         # tip toward the nose (scad module_rot)
FIT = 0.75              # general clearance round parts that drop in

# --- split + joints -------------------------------------------------------------
Y_SPLIT = 24.0          # face / back cut plane
JOINTS = [  # (name, seam point hint (x, z), radial direction) ; bracket joints
    ('temple_L', (-1, 28.0), (-1, 0, 0)),
    ('temple_R', (1, 28.0), (1, 0, 0)),
    ('base_L', (-17.0, -1), (0, 0, -1)),
    ('base_R', (17.0, -1), (0, 0, -1)),
]
JOINT_Y = 12.0          # radial screw this far behind the seam
DOWELS = [(-22.0, 1), (22.0, 1)]   # (x, top) dowel bosses at the top of the seam
DOWEL_D = 4.0
DOWEL_HOLE_D = 5.0      # loose
INSERT_D = 4.1          # M3 heat-set insert hole
INSERT_L = 5.7

# --- electronics / base --------------------------------------------------------------
RADAR = dict(L=35.0, W=7.0, T=1.2, comp=3.0, z=-27.5)    # HLK-LD2410C 35 x 7 mm
Y_TRAY = 125.0          # front face of the electronics tray posts
TRAY_POSTS = [(-25.0, 0.0), (25.0, 0.0), (0.0, 45.0)]
TRAY = dict(w=72.0, h=74.0, t=3.0, zc=15.0)
ESP32 = dict(L=55.0, W=28.0, T=1.6, standoff=16.0)       # ESP32-DevKitC V4 (no mounting holes)
USB_EXIT = (0.0, 112.0, 13.0)        # x, y, hole diameter (through the floor)
NECK = dict(y=90.0, r=14.0, z_bottom=-42.0, insert_d=6.4, insert_l=10.0)   # M5 heat-set insert
STAND = dict(base_d=110.0, base_t=6.0, col_d=28.0, col_id=16.0, h=78.0, top_t=6.0)

# =============================================================== utilities
CACHE = os.path.join(HERE, 'cache'); os.makedirs(CACHE, exist_ok=True)
OUT = os.path.join(HERE, 'out'); os.makedirs(OUT, exist_ok=True)
T0 = time.time()


def log(*a):
    print('[%6.1fs]' % (time.time() - T0), *a, flush=True)


def to_man(m):
    m = m.copy(); m.merge_vertices()
    return mf.Manifold(mf.Mesh(vert_properties=np.asarray(m.vertices, np.float32),
                               tri_verts=np.asarray(m.faces, np.uint32)))


def to_tri(M):
    o = M.to_mesh()
    t = trimesh.Trimesh(np.asarray(o.vert_properties[:, :3], np.float64), np.asarray(o.tri_verts), process=False)
    t.merge_vertices()
    return t


def union_shells(paths, min_vol=1.0):
    acc = []
    for p in paths:
        for b in trimesh.load(os.path.join(SRC, p), force='mesh').split(only_watertight=False):
            if not b.is_watertight:
                continue
            if b.volume < 0:
                b.invert()
            acc.append(to_man(b))
    U = mf.Manifold.batch_boolean(acc, mf.OpType.Add)
    parts = [x for x in U.decompose() if x.volume() > min_vol]   # drop zero-volume slivers
    return mf.Manifold.batch_boolean(parts, mf.OpType.Add) if len(parts) > 1 else parts[0]


# =============================================================== stage 1: sources
def load_sources():
    """Cranium and jaw as manifolds in source coordinates, jaw articulated."""
    cp, jp = os.path.join(CACHE, 'cranium_src.stl'), os.path.join(CACHE, 'jaw_src.stl')
    if os.path.exists(cp) and os.path.exists(jp):
        return to_man(trimesh.load(cp)), to_man(trimesh.load(jp))
    log('union cranium shells')
    cr = union_shells([CRANIUM_SRC])
    log('union jaw shells')
    jaw = union_shells(JAW_SRC)
    # Peter's printable jaw is posed rotated about X. Fit it onto the jaw that sits
    # in skull_w_jaw.stl (the largest watertight body that is not in skull_mesh).
    ref = max(trimesh.load(os.path.join(SRC, JAW_REF_SRC), force='mesh').split(only_watertight=True),
              key=lambda b: abs(b.volume) if b.bounds[0, 2] < 1430 else 0)
    jt = to_tri(jaw)
    P = jt.sample(20000, seed=1) if 'seed' in trimesh.sample.sample_surface.__code__.co_varnames else jt.sample(20000)
    Q = ref.sample(40000)
    best = None
    for a in np.radians(np.arange(-90, 91, 10)):
        c, s = np.cos(a), np.sin(a)
        M = np.eye(4); M[:3, :3] = [[1, 0, 0], [0, c, -s], [0, s, c]]
        Pc = P @ M[:3, :3].T
        M[:3, 3] = Q.mean(0) - Pc.mean(0)
        T, _, cost = trimesh.registration.icp(P, Q, initial=M, max_iterations=60, reflection=False, scale=False)
        if best is None or cost < best[1]:
            best = (T, cost)
    log('jaw ICP cost %.2f' % best[1])
    jaw = jaw.transform(best[0][:3, :])
    to_tri(cr).export(cp); to_tri(jaw).export(jp)
    return to_man(trimesh.load(cp)), to_man(trimesh.load(jp))   # same result cached or not


# =============================================================== stage 2: scale + frame
def front_depth(G, origin, h):
    """y of the first solid voxel looking from the front (-Y) along +Y; nan = miss."""
    hit = G.any(axis=1)
    first = np.argmax(G, axis=1).astype(float)
    D = origin[1] + first * h
    D[~hit] = np.nan
    return D                                            # [ix, iz]


def measure_orbits(D, origin, h, seeds=((-30, 1530), (30, 1530)), margin=None):
    """Orbit openings from a front depth map D[ix, iz] (source frame).

    The lateral orbital margin is the most anterior point walking laterally from
    the orbit at mid-height. The opening is the region (containing the seed) that
    lies behind that depth, i.e. the iso-depth contour through the lateral rim
    crest: it follows the medial, superior and inferior margins where they come
    forward of the lateral crest. Centre = midpoint of the opening's breadth and
    height. Rim depth = median depth of the ring just outside the opening.
    """
    Dc = np.nan_to_num(D, nan=1e3)
    xs = origin[0] + np.arange(D.shape[0]) * h
    zs = origin[2] + np.arange(D.shape[1]) * h
    res = []
    for sx, sz in seeds:
        i = int(np.argmin(abs(xs - sx))); k = int(np.argmin(abs(zs - sz)))
        s = int(np.sign(sx))
        prof = np.array([Dc[i + s * j, k] for j in range(int(40 / h))])
        n = int(np.argmax(prof > 500)) if (prof > 500).any() else len(prof)
        crest = prof[:n].min()
        mg = ORBIT_RIM_MARGIN if margin is None else margin
        while True:                                   # smallest closed contour from the margin up
            lab, _ = ndimage.label(Dc > crest + mg)
            comp = lab == lab[i, k]
            if comp.sum() * h * h < 3000:
                break
            mg += 0.25
            assert mg < 6, 'orbit contour leaks'
        ii, kk = np.where(comp)
        ring = ndimage.binary_dilation(comp, iterations=int(2 / h)) & ~comp
        res.append(dict(x=(xs[ii].min() + xs[ii].max()) / 2, z=(zs[kk].min() + zs[kk].max()) / 2,
                        breadth=float(np.ptp(xs[ii])), height=float(np.ptp(zs[kk])),
                        rim_y=float(np.median(Dc[ring])), lateral_crest_y=float(crest),
                        mask=comp))
    return res


def frame(cr, jaw):
    """Uniform scale (orbit centres EYE_SPACING apart) and move to the eye frame."""
    lo, hi = np.array(cr.bounding_box()[:3]), np.array(cr.bounding_box()[3:])
    h = 0.5
    origin = np.floor(lo) - 2
    shape = tuple(np.ceil((hi + 2 - origin) / h).astype(int) + 1)
    G = voxelize(cr, origin, h, shape)
    D = front_depth(G, origin, h)
    orbs = measure_orbits(D, origin, h)
    sp = orbs[1]['x'] - orbs[0]['x']
    s = EYE_SPACING / sp
    c = np.array([(orbs[0]['x'] + orbs[1]['x']) / 2, np.mean([o['rim_y'] for o in orbs]),
                  (orbs[0]['z'] + orbs[1]['z']) / 2 + EYE_DZ / s])
    info = dict(scale=s, src_orbit_spacing=sp, origin_src=c.tolist(),
                orbits_src=[{k: float(v) for k, v in o.items() if k != 'mask'} for o in orbs])
    log('orbits (source): L x=%.2f z=%.2f  R x=%.2f z=%.2f  spacing %.2f -> scale %.4f'
        % (orbs[0]['x'], orbs[0]['z'], orbs[1]['x'], orbs[1]['z'], sp, s))
    A = np.eye(4); A[:3, :3] *= s; A[:3, 3] = -c * s
    cr2, jaw2 = cr.transform(A[:3, :]), jaw.transform(A[:3, :])
    b = np.array(cr2.bounding_box()); info['cranium_size'] = (b[3:] - b[:3]).tolist()
    log('cranium size after scaling L(Y) %.1f  W(X) %.1f  H(Z) %.1f' % (b[4] - b[1], b[3] - b[0], b[5] - b[2]))
    return cr2, jaw2, info


# =============================================================== stage 3: voxel shell
class Grid:
    """Axis-aligned voxel grid (index i,j,k -> origin + (i,j,k)*h)."""

    def __init__(self, lo, hi, h, pad=6.0):
        self.h = h
        self.o = np.floor(np.asarray(lo) - pad)
        self.shape = tuple(int(v) for v in np.ceil((np.asarray(hi) + pad - self.o) / h).astype(int) + 1)
        self.x, self.y, self.z = (self.o[a] + np.arange(self.shape[a]) * h for a in range(3))

    def idx(self, p):
        return tuple(int(round((p[a] - self.o[a]) / self.h)) for a in range(3))

    def coords(self):
        return np.meshgrid(self.x, self.y, self.z, indexing='ij', sparse=True)

    def vox(self, man):
        return voxelize(man, self.o, self.h, self.shape)


def edt(mask, h):
    """Distance (mm) from each voxel to the nearest True voxel of `mask`."""
    return ndimage.distance_transform_edt(~mask) * h


def outside(solid):
    """Air voxels connected to the grid boundary (6-connectivity)."""
    air = ~solid
    lab, _ = ndimage.label(air)
    edge = np.unique(np.concatenate([lab[0].ravel(), lab[-1].ravel(), lab[:, 0].ravel(), lab[:, -1].ravel(),
                                     lab[:, :, 0].ravel(), lab[:, :, -1].ravel()]))
    edge = edge[edge > 0]
    return np.isin(lab, edge)


def fill_slab_holes(G, solid, axis, c0, c1, seeds, roi, close_r=0.0, fuse=1.5):
    """Plug: in every slice of the slab c0..c1 along `axis`, the air region of `solid`
    that contains one of `seeds` (2D, in the two other axes, in mm) and stays
    inside the 2D box roi=(u0,u1,v0,v1). The slice is closed by close_r first.
    Returns a bool volume. Raises if a seed region leaks out of the roi."""
    h = G.h
    ax = [G.x, G.y, G.z]
    other = [a for a in range(3) if a != axis]
    U, V = ax[other[0]], ax[other[1]]
    plug = np.zeros(G.shape, bool)
    ks = np.where((ax[axis] >= c0 - 1e-6) & (ax[axis] <= c1 + 1e-6))[0]
    roimask = ((U[:, None] >= roi[0]) & (U[:, None] <= roi[1]) & (V[None, :] >= roi[2]) & (V[None, :] <= roi[3]))
    border = roimask & ~ndimage.binary_erosion(roimask)
    for k in ks:
        sl = [slice(None)] * 3; sl[axis] = k; sl = tuple(sl)
        for r in [close_r, close_r + 1.0, close_r + 2.0, close_r + 3.0, close_r + 4.0]:
            s2 = solid[sl] & roimask
            if r > 0:
                st = ndimage.iterate_structure(ndimage.generate_binary_structure(2, 1), max(1, int(round(r / h))))
                s2 = ndimage.binary_closing(s2, structure=st) | s2
            lab, _ = ndimage.label(~s2)
            hole = np.zeros_like(s2); ok = True
            for su, sv in seeds:
                iu = int(round((su - U[0]) / h)); iv = int(round((sv - V[0]) / h))
                l = lab[iu, iv]
                if l == 0:
                    continue
                comp = lab == l
                if (comp & border).any():
                    ok = False; break
                hole |= comp
            if ok:
                break
        else:
            raise RuntimeError('plug leaks out of its roi at slice %d (axis %d)' % (k, axis))
        if fuse > 0 and hole.any():
            hole = ndimage.binary_dilation(hole, iterations=int(round(fuse / h))) & roimask
        plug[sl] |= hole
    return plug


def column_to_bone(B, col, y0, y1, Yg):
    """In every (x,z) column of `col`, the voxels from y0 back to the first bone
    voxel behind y0 (and never past y1)."""
    behind = Yg >= y0[:, None, :]
    hit = B & behind
    first = np.where(hit.any(1), np.argmax(hit, axis=1), B.shape[1])   # [ix, iz] index
    jj = np.arange(B.shape[1])[None, :, None]
    return col[:, None, :] & behind & (jj < first[:, None, :]) & (Yg <= y1[:, None, :])


def make_plugs(G, B, scale):
    """Closing plugs for the big openings (eyes, nose).

    Each plug fills a column (x,z inside the opening seen from the front, grown a
    little) from its closing surface S(x,z) back EYE/NASAL_PLUG_DEPTH mm, and never
    in front of the visible face surface. Everything behind S becomes "inside",
    so after shelling S is the front face of a SHELL_T thick wall.
    Eye: S is coronal at EYE_PLATE_DEPTH round the screen and bends back to the
    lateral orbital rim (the orbit opening faces forward-laterally).
    """
    h = G.h
    Df = front_depth(B, G.o, h)                       # [ix, iz]
    orbs = measure_orbits(Df, G.o, h, seeds=((-EYE_SPACING / 2, 0.0), (EYE_SPACING / 2, 0.0)),
                          margin=ORBIT_RIM_MARGIN * scale)
    Xg, Zg = np.meshgrid(G.x, G.z, indexing='ij')
    Yg = G.y[None, :, None]
    plugs, info = {}, {}
    for side, o, xc in (('eyeL', orbs[0], -EYE_SPACING / 2), ('eyeR', orbs[1], EYE_SPACING / 2)):
        m = o['mask']
        ii = np.where(m.any(1))[0]
        x_lat = G.x[ii.min()] if xc < 0 else G.x[ii.max()]
        r0 = BEZEL_D / 2 + 2.5
        run = abs(x_lat - xc) - r0
        tan = max(0.0, (o['lateral_crest_y'] - 1.0 - EYE_PLATE_DEPTH) / max(run, 1.0))
        S = EYE_PLATE_DEPTH + tan * np.clip(np.sign(xc) * (Xg - xc) - r0, 0, None)
        grow = ndimage.binary_dilation(m, iterations=int(round(EYE_PLUG_GROW / h)))
        lat = np.sign(xc) * (Xg - x_lat) > 1.0         # do not grow past the lateral rim
        col = grow & ~lat
        y0 = np.where(m, S, np.maximum(S, np.nan_to_num(Df, nan=1e3)))   # ring: not in front of the face
        plugs[side] = column_to_bone(B, col, y0, S + EYE_PLUG_DEPTH, Yg)
        info[side] = dict(x=o['x'], z=o['z'], rim_y=o['rim_y'], lateral_crest_y=o['lateral_crest_y'],
                          breadth=o['breadth'], height=o['height'], x_lat=float(x_lat), tilt_deg=float(np.degrees(np.arctan(tan))))
        log('%s: measured centre x=%.2f z=%.2f (frame), opening %.1f x %.1f, rim y %.2f, lateral crest y %.2f, plate bends back %.0f deg'
            % (side, o['x'], o['z'], o['breadth'], o['height'], o['rim_y'], o['lateral_crest_y'], info[side]['tilt_deg']))
    # nose
    y0n = NASAL_RIM_Y + NASAL_RECESS
    Dn = np.nan_to_num(Df, nan=1e3)
    lab, _ = ndimage.label(Dn > NASAL_RIM_Y + 4.0)
    nm = np.zeros_like(Dn, bool)
    for sx, sz in NASAL_SEEDS:
        l = lab[G.idx((sx, 0, sz))[0], G.idx((sx, 0, sz))[2]]
        if l:
            nm |= lab == l
    assert nm.sum() * h * h < 1500, 'nasal opening leaks'
    ring = ndimage.binary_dilation(nm, iterations=int(round(NASAL_PLUG_GROW / h))) & ~nm
    y0 = np.where(nm, y0n, np.maximum(y0n, Dn))
    nm |= ring
    plugs['nasal'] = column_to_bone(B, nm, y0, np.full_like(y0, y0n + NASAL_PLUG_DEPTH), Yg)
    for k, v in plugs.items():
        log('plug %-6s %6.2f cm3' % (k, v.sum() * h ** 3 / 1000))
    return plugs, info, Df


def shell(G, B, plugs, extra_in=None, extra_out=None):
    """Recessed webs + uniform shell. extra_in is forced inside (servo cup),
    extra_out is forced to outside air (swept jaw). Returns dict of volumes."""
    h = G.h
    S0 = B.copy()
    for v in plugs.values():
        S0 |= v
    if extra_in is not None:
        S0 |= extra_in
    X, Y, Z = G.coords()
    t = TEMPLE_ROI
    rois = [(WEB_CLOSE_R, None),
            (BASE_CLOSE_R, (Y >= BASE_ROI['y_min']) & (Z <= BASE_ROI['z_max'])),
            (TEMPLE_CLOSE_R, (abs(X) >= t['abs_x_min']) & (Y >= t['y_min']) & (Y <= t['y_max'])
             & (Z >= t['z_min']) & (Z <= t['z_max']))]
    env = S0.copy()
    d0 = edt(S0, h)
    for R, roi in rois:
        log('closing r=%g' % R)
        aout = outside(d0 <= R)
        e = edt(aout, h) > R
        env |= e if roi is None else (e & roi)
    denv = edt(~env, h)
    core = env & (denv >= WEB_RECESS) & (denv <= WEB_RECESS + WEB_T)
    small = ndimage.binary_closing(S0, iterations=int(round(SMALL_CLOSE_R / h)), border_value=0) | S0
    M = small | core
    if extra_in is not None:
        M |= extra_in
    log('outside air')
    A = outside(M)
    leak = A[G.idx(CAVITY_PROBE)]
    if extra_out is not None:      # carved regions count as outside air; the shell wraps them
        A |= extra_out
        M &= ~extra_out
    dA = edt(A, h)
    F = ~A & (dA <= SHELL_T)
    log('shell %.0f cm3, core %.0f cm3, cavity reachable from outside: %s'
        % (F.sum() * h ** 3 / 1000, core.sum() * h ** 3 / 1000, leak))
    dO = edt(~A, h)                                   # distance of outside air to the solid
    sd = np.where(A, -dO, dA).astype(np.float32)      # signed: + inside
    return dict(S0=S0, env=env, core=core, M=M, A=A, sd=sd, F=F, leak=leak)


def shell_mesh(G, cr, sh):
    """Cranium shell as a manifold: original bone surface outside, marching cubes inside."""
    sd = sh['sd']
    t = SHELL_T
    log('mesh: band + inner layer')
    band = mc_mesh(np.minimum(sd + 0.6, t + 0.25 - sd), G, 0.0, step=2, sigma=0.6)
    inner = mc_mesh(np.minimum(sd - INNER_SKIN, t - sd), G, 0.0, step=2, sigma=0.6)
    log('mesh: booleans (band %d tris, inner %d tris)' % (band.num_tri(), inner.num_tri()))
    outer = cr ^ band
    M = outer + inner
    log('cranium shell %d tris, %.0f cm3, genus %d' % (M.num_tri(), vol(M), M.genus()))
    return M


# =============================================================== mesh helpers
def m_box(lo, hi):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    return mf.Manifold.cube(list(hi - lo)).translate(list(lo))


def m_cyl(p0, p1, r, r1=None, seg=48):
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    d = p1 - p0; L = float(np.linalg.norm(d)); d /= L
    c = mf.Manifold.cylinder(L, r, r if r1 is None else r1, seg)
    # rotate +Z onto d
    z = np.array([0, 0, 1.0]); v = np.cross(z, d); sn = np.linalg.norm(v); cs = float(np.dot(z, d))
    if sn < 1e-9:
        R = np.eye(3) if cs > 0 else np.diag([1, -1, -1.0])
    else:
        k = v / sn; K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        R = np.eye(3) + sn * K + (1 - cs) * K @ K
    M = np.zeros((3, 4)); M[:, :3] = R; M[:, 3] = p0
    return c.transform(M)


def rot_x_about(y0, z0, deg):
    a = np.radians(deg); c, s = np.cos(a), np.sin(a)
    M = np.zeros((3, 4)); M[0, 0] = 1
    M[1, 1:3] = [c, -s]; M[2, 1:3] = [s, c]
    M[1, 3] = y0 - (c * y0 - s * z0); M[2, 3] = z0 - (s * y0 + c * z0)
    return M


def union(ms):
    ms = [m for m in ms if m is not None and not m.is_empty()]
    return mf.Manifold.batch_boolean(ms, mf.OpType.Add) if len(ms) > 1 else ms[0]


def mc_mesh(field, G, level=0.0, step=1, sigma=0.0):
    """Marching cubes of field > level on grid G -> manifold (outward normals)."""
    from skimage.measure import marching_cubes
    f = np.pad(field.astype(np.float32), 2, constant_values=float(field.min()) - 1.0)
    if sigma > 0:
        f = ndimage.gaussian_filter(f, sigma)
    v, fc, _, _ = marching_cubes(f, level, step_size=step)
    v = (v - 2) * G.h + G.o
    t = trimesh.Trimesh(v, fc, process=True)
    if t.volume < 0:
        t.invert()
    return to_man(t)


def vol(M):
    return M.volume() / 1000.0   # cm3


# =============================================================== jaw articulation
def jaw_hinge(jaw):
    """Hinge axis (parallel to X) through the condyle heads: (y, z)."""
    t = to_tri(jaw); v = t.vertices
    zt = v[:, 2].max()
    top = v[v[:, 2] > zt - 8.0]
    return float(top[:, 1].mean()), float(top[:, 2].mean() - 1.0)


def jaw_closed_angle(jaw, cr, hinge):
    """Most-closed angle (deg about +X, +ve opens) that leaves TEETH_GAP between
    the lower and the upper teeth (cranium in front of / below the hinge only)."""
    front = cr ^ m_box([-90, -80, -90], [90, hinge[0] - 25, hinge[1] + 5])
    for a in np.arange(-25.0, 15.01, 0.25):
        if jaw.transform(rot_x_about(*hinge, a)).min_gap(front, TEETH_GAP + 0.5) >= TEETH_GAP:
            return float(a)
    raise RuntimeError('no closed angle found')


# =============================================================== jaw mechanism
HORN_FACE_X = 33.0      # |x| of the horn arm face = jaw pad face (servo side)
PIVOT_FACE_X = 32.0     # |x| of the jaw pivot pad face (other side); skull boss 0.5 further in
BRACKET_T = 3.0


def servo_frame(hinge):
    """Map servo-local (u along the shaft from the case bottom, v along the case
    length from the shaft axis (up), w across) to world points."""
    side = SERVO_SIDE
    xb = side * (HORN_FACE_X - (SERVO['spline_top'] + 1.0))

    def P(u, v, w):
        return np.array([xb + side * u, hinge[0] + w, hinge[1] + v])
    return P


def sbox(P, u0, u1, v0, v1, w0, w1):
    a, b = P(u0, v0, w0), P(u1, v1, w1)
    return m_box(np.minimum(a, b), np.maximum(a, b))


def mechanism(hinge):
    S = SERVO; c = SERVO_CLEAR; P = servo_frame(hinge)
    vb0, vb1 = -S['shaft_off'], S['L'] - S['shaft_off']          # case ends along v
    vt0 = (vb0 + vb1) / 2 - S['tab_len'] / 2; vt1 = vt0 + S['tab_len']
    vh = [(vb0 + vb1) / 2 - S['hole_sp'] / 2, (vb0 + vb1) / 2 + S['hole_sp'] / 2]
    tab_u0 = S['tab_top'] - S['tab_t']
    out = {}
    # servo model (for collision checks): case + tabs + gear bump + spline
    out['servo'] = union([sbox(P, 0, S['H'], vb0, vb1, -S['W'] / 2, S['W'] / 2),
                          sbox(P, tab_u0, S['tab_top'], vt0, vt1, -S['W'] / 2, S['W'] / 2),
                          m_cyl(P(S['H'] - 0.1, 0, 0), P(S['spline_top'] - 2.4, 0, 0), S['bump_d'] / 2),
                          m_cyl(P(S['spline_top'] - 2.5, 0, 0), P(S['spline_top'], 0, 0), 2.4)])
    # horn: modelled as the disc it sweeps
    out['horn'] = m_cyl(P(S['spline_top'] - 1.0, 0, 0), P(S['spline_top'] + 1.0, 0, 0), HORN_R) + \
        m_cyl(P(S['spline_top'] - 2.4, 0, 0), P(S['spline_top'] - 0.9, 0, 0), 4.5)     # arm disc + hub
    # bracket (separate part): plate under the tabs + top flange
    fl_v0 = vt1 + 2.0; fl_v1 = fl_v0 + BRACKET_T
    pl = sbox(P, tab_u0 - BRACKET_T, tab_u0, vt0 - 2.0, fl_v1, -9.0, 9.0)
    fl = sbox(P, -11.0, tab_u0, fl_v0, fl_v1, -9.0, 9.0)
    cut = sbox(P, tab_u0 - BRACKET_T - 1, tab_u0 + 1, vb0 - 0.5, vb1 + 0.5, -S['W'] / 2 - 0.5, S['W'] / 2 + 0.5)
    holes = [m_cyl(P(tab_u0 - BRACKET_T - 1, v, 0), P(tab_u0 + 1, v, 0), 0.9) for v in vh]
    fl_holes = [m_cyl(P(-6.0, fl_v0 - 1, w), P(-6.0, fl_v1 + 1, w), 1.9) for w in (-5.0, 5.0)]
    out['bracket'] = (pl + fl) - union([cut] + holes + fl_holes)
    out['bracket_bolts'] = [P(-6.0, fl_v0, w) for w in (-5.0, 5.0)]    # boss tops (M3 inserts, vertical)
    # interior marker for the shell stage: servo + bracket + clearance, and a chimney
    # straight up (the servo + bracket drop in from above)
    env = union([sbox(P, -c, S['H'] + c, vb0 - c, vb1 + c, -S['W'] / 2 - c, S['W'] / 2 + c),
                 sbox(P, tab_u0 - BRACKET_T - c, S['tab_top'] + c, vt0 - 2.0 - c, fl_v1 + c, -9 - c, 9 + c),
                 sbox(P, -c, tab_u0 + c, vt0 - 2 - c, 60, -9 - c, 9 + c),
                 sbox(P, -c, S['H'] + c, vb0 - c, 60, -S['W'] / 2 - c, S['W'] / 2 + c)])
    out['cup_env'] = env
    # slot in the cup wall for the gear bump (open upward), cut after shelling
    out['cup_slot'] = sbox(P, S['H'] - 1.0, S['spline_top'] + 0.5, -S['bump_d'] / 2 - c, 60,
                           -S['bump_d'] / 2 - c, S['bump_d'] / 2 + c)
    # jaw pad on the servo side (jaw part): disc from the horn face into the ramus
    side = SERVO_SIDE
    out['jaw_pad'] = m_cyl([side * HORN_FACE_X, *hinge], [side * (HORN_FACE_X + 8), *hinge], 12.0)
    pad_holes = [m_cyl([side * (HORN_FACE_X - 1), hinge[0], hinge[1]], [side * (HORN_FACE_X + 20), hinge[0], hinge[1]], 3.5)]
    for r in (8.0, 10.0, 12.0, 14.0):
        for sg in (-1, 1):          # pilot holes for the horn screws, along the ramus (down)
            q = np.array([0, sg * 0.0, -r]) if sg > 0 else np.array([0, 0, r])
            pad_holes.append(m_cyl([side * (HORN_FACE_X - 1), hinge[0] + q[1], hinge[1] + q[2]],
                                   [side * (HORN_FACE_X + 6), hinge[0] + q[1], hinge[1] + q[2]], 0.75))
    out['jaw_pad_holes'] = union(pad_holes)
    # pivot side
    o = -side
    out['jaw_pivot_pad'] = m_cyl([o * PIVOT_FACE_X, *hinge], [o * (PIVOT_FACE_X + 8), *hinge], 8.0)
    x_head = o * (PIVOT_FACE_X + 14.5)               # bolt head seat (M3x20: 14.5 jaw + 0.5 gap + 5 insert)
    out['jaw_pivot_holes'] = union([m_cyl([o * (PIVOT_FACE_X - 1), *hinge], [o * 60, *hinge], 1.75),
                                    m_cyl([x_head, *hinge], [o * 60, *hinge], 3.3)])
    xs0 = o * (PIVOT_FACE_X - 0.5)
    out['skull_pivot'] = union([m_cyl([xs0, *hinge], [o * 22.0, *hinge], 15.0),
                                m_box([min(xs0, o * 22.0), hinge[0] - 9, hinge[1]],
                                      [max(xs0, o * 22.0), hinge[0] + 9, hinge[1] + 22])])
    out['skull_pivot_holes'] = union([m_cyl([xs0 + o * 0.01, *hinge], [xs0 - o * 5.7, *hinge], 2.05),
                                      m_cyl([xs0, *hinge], [xs0 - o * 9.5, *hinge], 1.75)])
    # hard-stop finger on the jaw pivot pad, running in a slot in the skull boss
    fy = hinge[0] + np.array([5.5, 13.5]); fz = hinge[1] + np.array([-2.5, 2.5])
    out['finger_clear'] = m_box([min(o * (PIVOT_FACE_X + 0.5), o * (PIVOT_FACE_X - 5.0)), fy[0] - 0.6, fz[0]],
                                [max(o * (PIVOT_FACE_X + 0.5), o * (PIVOT_FACE_X - 5.0)), fy[1] + 0.6, fz[1]])
    out['finger'] = m_box([min(o * PIVOT_FACE_X, o * (PIVOT_FACE_X - 4.5)), fy[0], fz[0]],
                          [max(o * PIVOT_FACE_X, o * (PIVOT_FACE_X - 4.5)), fy[1], fz[1]]) \
        + m_box([min(o * PIVOT_FACE_X, o * (PIVOT_FACE_X + 2)), hinge[0], fz[0]],
                [max(o * PIVOT_FACE_X, o * (PIVOT_FACE_X + 2)), fy[1], fz[1]])
    return out


# =============================================================== features
def scad_to_skull(y_back):
    """eye_mount.scad (X, Y, Z) -> skull (X, y_back - Z, Y); bar back face at y_back."""
    return np.array([[1, 0, 0, 0], [0, 0, -1, y_back], [0, 1, 0, 0]], float)


def eye_rot(x):
    return -MODULE_ROT if x > 0 else MODULE_ROT


def module_local(c=0.0, with_cable=False):
    """One Waveshare 0.71in module in scad coords (screen centre at origin, tip -Y)."""
    pcb_r, tip, hdy = 10.06, -12.24, -0.14
    z0 = BAR_T + STANDOFF_H
    parts = [mf.Manifold.batch_hull([m_cyl([0, 0, z0 - c], [0, 0, z0 + MODULE_T + c], pcb_r + c),
                                     m_box([-3.67 - c, tip - c, z0 - c], [3.67 + c, tip + 0.1, z0 + MODULE_T + c])])]
    for sx in (-1, 1):
        parts.append(m_cyl([sx * 7.875, hdy, BAR_T - 0.01], [sx * 7.875, hdy, z0], 1.91 + c))
    parts.append(m_box([-4.6 - c, hdy - 7.7 - c, z0 - 4.5], [4.6 + c, hdy - 2.6 + c, z0]))
    if with_cable:
        parts.append(m_box([-5.6, hdy - 8.8, -16.0], [5.6, hdy - 1.5, z0 - 4.5]))
        for sx in (-1, 1):   # M2 heads behind the bar
            parts.append(m_cyl([sx * 7.875, hdy, -2.4], [sx * 7.875, hdy, 0.01], 2.3))
    return union(parts)


def place_modules(local):
    out = []
    for xe in (-EYE_SPACING / 2, EYE_SPACING / 2):
        out.append(local.rotate([0, 0, eye_rot(xe)]).translate([xe, 0, 0]))
    return union(out)


def bar_clearance_local():
    b = BAR_PLATE; c = 0.6
    parts = [m_box([-b['half_w'] - c, -b['half_h'] - c, -0.5], [b['half_w'] + c, b['half_h'] + c, BAR_T])]
    for hx, hz in BAR_HOLES:
        parts.append(m_cyl([hx, hz, -0.5], [hx, hz, BAR_T], b['boss_d'] / 2 + b['slot'] / 2 + c))
        parts.append(m_cyl([hx, hz, -3.6], [hx, hz, 0.01], 3.3))            # M3 head
        parts.append(m_cyl([hx, hz, -40.0], [hx, hz, -3.5], 3.6))           # driver access from behind
    return union(parts)


def inner_point(G, sd, start, d, level):
    """Walk from `start` along unit `d` until the signed distance drops to `level`."""
    p = np.asarray(start, float); d = np.asarray(d, float)
    for _ in range(2000):
        i = G.idx(p)
        if sd[i] <= level:
            return p
        p = p + d * 0.2
    raise RuntimeError('no surface from %s' % (start,))


def frame3(d):
    er = np.asarray(d, float); ey = np.array([0, 1.0, 0]); et = np.cross(er, ey)
    return er, ey, et


def obox(o, er, ey, et, r, y, t):
    """Box in a local frame (er, ey, et) at origin o; r/y/t are (lo, hi) ranges."""
    M = np.zeros((3, 4)); M[:, 0] = er; M[:, 1] = ey; M[:, 2] = et; M[:, 3] = o
    lo = np.array([r[0], y[0], t[0]]); hi = np.array([r[1], y[1], t[1]])
    return mf.Manifold.cube(list(hi - lo)).translate(list(lo)).transform(M)


def joints(G, sd, inside, cavity):
    """Bracket joints: face boss (insert along -Y at the seam), separate bracket,
    back pad (radial screw from outside into the bracket insert)."""
    res = dict(face_add=[], face_cut=[], back_add=[], back_cut=[], brackets=[], info=[])
    yj = Y_SPLIT + JOINT_Y
    PAD_IN = 3.0
    for name, hint, d in JOINTS:
        d = np.asarray(d, float)
        if d[0] != 0:
            start = np.array([0.0, yj, hint[1]])
        else:
            start = np.array([hint[0], yj, 0.0])
        p_in = inner_point(G, sd, start, d, SHELL_T)
        p_out = inner_point(G, sd, p_in, d, 0.0)
        er, ey, et = frame3(d)
        q0 = p_in - er * (PAD_IN + 0.4)                     # bracket arm outer face
        o = np.array([q0[0], 0.0, q0[2]])                   # local origin (y absolute)
        if d[0] == 0:
            o = np.array([q0[0], 0.0, q0[2]])
        # back part: pad + screw
        res['back_add'].append(m_cyl(p_out + er * 1.0, p_in - er * PAD_IN, 6.5) ^ inside)
        res['back_cut'] += [m_cyl(p_out + er * 12, p_out - er * 3.0, 3.25),
                            m_cyl(p_out + er * 2, p_in - er * (PAD_IN + 1.0), 1.7)]
        # bracket
        arm = obox(o, er, ey, et, (-8.0, 0.0), (Y_SPLIT + 0.3, yj + 7.0), (-6.0, 6.0))
        fl = obox(o, er, ey, et, (-20.0, 0.0), (Y_SPLIT + 0.3, Y_SPLIT + 6.3), (-6.0, 6.0))
        qi = o + er * 0 + ey * yj
        qi[1] = yj
        hole_r = [m_cyl(np.array([q0[0], yj, q0[2]]) + er * 0.01, np.array([q0[0], yj, q0[2]]) - er * INSERT_L, INSERT_D / 2),
                  m_cyl(np.array([q0[0], yj, q0[2]]), np.array([q0[0], yj, q0[2]]) - er * (INSERT_L + 3.5), 1.6)]
        ys = np.array([q0[0], 0, q0[2]]) - er * 15.0
        hole_y = m_cyl([ys[0], Y_SPLIT, ys[2]], [ys[0], Y_SPLIT + 8, ys[2]], 1.75)
        br = (arm + fl) ^ cavity
        bb = np.array(br.bounding_box())
        local = cavity ^ m_box(bb[:3] - [1, JOINT_Y + 10, 1], bb[3:] + 1)
        for dd in np.arange(0.5, JOINT_Y + 8.01, 0.5):     # must slide in along Y without catching
            br = br ^ local.translate([0, dd, 0])
        res['brackets'].append((name, br - union(hole_r + [hole_y])))
        # face boss with insert at the seam
        boss = obox(o, er, ey, et, (-20.0, 12.0), (Y_SPLIT - 10.0, Y_SPLIT), (-7.0, 7.0)) ^ inside
        res['face_add'].append(boss)
        res['face_cut'] += [m_cyl([ys[0], Y_SPLIT + 0.01, ys[2]], [ys[0], Y_SPLIT - INSERT_L, ys[2]], INSERT_D / 2),
                            m_cyl([ys[0], Y_SPLIT, ys[2]], [ys[0], Y_SPLIT - INSERT_L - 3.5, ys[2]], 1.6)]
        res['info'].append(dict(name=name, screw_point=p_out.round(1).tolist(), dir=d.tolist()))
    for x, _ in DOWELS:
        p_in = inner_point(G, sd, [x, Y_SPLIT, 40.0], [0, 0, 1.0], SHELL_T)
        cz = p_in[2] - 5.0
        res['face_add'].append(m_cyl([x, Y_SPLIT - 10, cz], [x, Y_SPLIT, cz], 5.5) ^ inside)
        res['back_add'].append(m_cyl([x, Y_SPLIT, cz], [x, Y_SPLIT + 10, cz], 5.5) ^ inside)
        h = m_cyl([x, Y_SPLIT - 7, cz], [x, Y_SPLIT + 7, cz], DOWEL_HOLE_D / 2)
        res['face_cut'].append(h); res['back_cut'].append(h)
    return res


def dowel():
    return m_cyl([0, 0, 0], [0, 0, 0.6], DOWEL_D / 2 - 0.4, DOWEL_D / 2) + \
        m_cyl([0, 0, 0.59], [0, 0, 12.41], DOWEL_D / 2) + m_cyl([0, 0, 12.4], [0, 0, 13.0], DOWEL_D / 2, DOWEL_D / 2 - 0.4)


def radar_parts(y_wall_back):
    R = RADAR; c = 0.6; w = 1.6
    y0 = y_wall_back
    box = m_box([-R['L'] / 2, y0 + 0.4, R['z'] - R['W'] / 2], [R['L'] / 2, y0 + 0.4 + R['T'] + R['comp'], R['z'] + R['W'] / 2])
    clear = m_box([-R['L'] / 2 - c, y0 - 0.01, R['z'] - R['W'] / 2 - c], [R['L'] / 2 + c, y0 + 25, R['z'] + R['W'] / 2 + c])
    frame = m_box([-R['L'] / 2 - c - w, y0 - 1.5, R['z'] - R['W'] / 2 - c - w],
                  [R['L'] / 2 + c + w, y0 + 5.0, R['z'] + R['W'] / 2 + c + w])
    return box, clear, frame


def tray_parts():
    """Electronics tray (separate part) + ESP32 cradle; skull coordinates."""
    T = TRAY; E = ESP32; c = FIT
    y1 = Y_TRAY; y0 = y1 - T['t']
    zc = T['zc']
    plate = m_box([-T['w'] / 2, y0, zc - T['h'] / 2], [T['w'] / 2, y1, zc + T['h'] / 2])
    yb = y0 - E['standoff']                      # board back face
    yf = yb - E['T']
    zb0 = zc - E['L'] / 2; zb1 = zc + E['L'] / 2
    parts = [plate]
    for sg, zend in ((-1, zb0), (1, zb1)):
        wall = m_box([-E['W'] / 2 - c - 2.5, yf - 3.0, min(zend + sg * c, zend + sg * (c + 2.5))],
                     [E['W'] / 2 + c + 2.5, y0 + 0.01, max(zend + sg * c, zend + sg * (c + 2.5))])
        ledge = m_box([-9.0, yb, min(zend, zend - sg * 5.0)], [9.0, y0 + 0.01, max(zend, zend - sg * 5.0)])
        parts += [wall, ledge]
    tray = union(parts)
    cuts = [m_box([-6.5, yf - 10, zb0 - 6], [6.5, yb + 2.0, zb0 + 0.1])]          # USB plug
    for hx, hz in TRAY_POSTS:
        cuts.append(m_cyl([hx, y0 - 1, hz], [hx, y1 + 1, hz], 1.9))
    for sx in (-1, 1):
        cuts.append(m_box([sx * 18 - 1.0, y0 - 1, zc + 8], [sx * 18 + 1.0, y1 + 1, zc + 12]))  # zip tie
    tray = tray - union(cuts)
    board = union([m_box([-E['W'] / 2, yf, zb0], [E['W'] / 2, yb, zb1])] +
                  [m_box([sx * 11.4 - 1.3 if sx > 0 else -14.0, yb, zb0 + 3], [14.0 if sx > 0 else -11.4 + 1.3, yb + 14.0, zb1 - 3])
                   for sx in (-1, 1)])      # header rows + dupont housings
    return tray, board


def stand():
    S = STAND; N = NECK
    zt = N['z_bottom']; zb = zt - S['h']
    col = m_cyl([0, N['y'], zb], [0, N['y'], zt], S['col_d'] / 2)
    base = m_cyl([0, N['y'], zb], [0, N['y'], zb + S['base_t']], S['base_d'] / 2, seg=96)
    bore = m_cyl([0, N['y'], zb - 1], [0, N['y'], zt - S['top_t']], S['col_id'] / 2)
    bolt = m_cyl([0, N['y'], zt - S['top_t'] - 1], [0, N['y'], zt + 1], 2.8)
    return (col + base) - bore - bolt


# =============================================================== assembly
def clean(M, name):
    """Keep the largest body; report dropped fragments; fill pinch edges (edges
    shared by 4 faces once coincident vertices are merged, as an STL reader does)."""
    parts = sorted(M.decompose(), key=lambda m: -m.volume())
    dropped = [p.volume() for p in parts[1:]]
    if dropped:
        log('%s: dropped %d loose fragments (%.3f cm3 total)' % (name, len(dropped), sum(dropped) / 1000))
    M = parts[0]
    rng = np.random.default_rng(0)
    for it in range(6):
        t = to_tri(M)
        u, c = np.unique(t.edges_sorted, axis=0, return_counts=True)
        bad = u[c != 2]
        if len(bad) == 0:
            break
        pts = t.vertices[bad].mean(axis=1)
        log('%s: filling %d pinch edges' % (name, len(bad)))
        blobs = [mf.Manifold.cube([1.0, 1.0, 1.0], True).rotate(list(rng.uniform(0, 90, 3))).translate(list(p))
                 for p in pts]
        M = union([M] + blobs) if it % 2 == 0 else M - union(blobs)
    return M


def build():
    cr, jaw = load_sources()
    cr, jaw, info = frame(cr, jaw)
    hinge = jaw_hinge(jaw)
    a0 = jaw_closed_angle(jaw, cr, hinge)
    log('hinge y=%.2f z=%.2f; source jaw pose closes at %.2f deg' % (hinge[0], hinge[1], a0))
    jaw = jaw.transform(rot_x_about(*hinge, a0))
    info.update(hinge=list(hinge), jaw_closed_from_source_deg=a0)
    mech = mechanism(hinge)
    jaw_moving = union([jaw, mech['jaw_pad'], mech['jaw_pivot_pad'], mech['finger']])
    # trim the condyle heads just above the axis (they only rotate in place)
    jaw_moving = jaw_moving - m_box([-80, hinge[0] - 15, hinge[1] + 3.5], [80, hinge[0] + 15, hinge[1] + 30])
    angles = np.arange(JAW_CLOSE_STOP - 1.0, JAW_OPEN_DEG + JAW_STOP_MARGIN + 1.01, 1.5)
    sweep = union([jaw_moving.transform(rot_x_about(*hinge, a)) for a in angles] + [mech['horn']])
    b = np.array(cr.bounding_box())
    G = Grid(b[:3] - [0, 0, 20], b[3:], VOX)
    log('grid', G.shape)
    Bv = G.vox(cr)
    plugs, einfo, Df = make_plugs(G, Bv, info['scale'])
    info['eyes'] = einfo
    sweep_v = ndimage.binary_dilation(G.vox(sweep), iterations=int(round(JAW_SWEEP_CLEAR / G.h)))
    # the shell is taken from the outside of the marked volume, so grow the cup by the wall
    cup_v = ndimage.binary_dilation(G.vox(mech['cup_env']), iterations=int(np.ceil((SHELL_T + 0.4) / G.h)))
    sh = shell(G, Bv, plugs, extra_in=cup_v, extra_out=sweep_v)
    assert not sh['leak'], 'the cavity is visible from outside'
    crm = shell_mesh(G, cr, sh)
    sd = sh['sd']
    inside = mc_mesh(sd - 0.4, G, 0.0, step=2)
    cavity = mc_mesh(sd - (SHELL_T + 0.6), G, 0.0, step=2)      # free space inside the shell

    # ---- eyes
    y_glass = EYE_PLATE_DEPTH + SHELL_T + SCREEN_GAP
    y_back = y_glass + MODULE_T + STANDOFF_H + BAR_T
    y_front = y_back - BAR_T
    T = scad_to_skull(y_back)
    bar = to_man(trimesh.load(EYE_BAR_STL)).transform(T)
    modules = place_modules(module_local()).transform(T)
    eye_clear = (place_modules(module_local(FIT, True)) + bar_clearance_local()).transform(T)
    posts = union([m_cyl([hx, y_front, hz], [hx, y_front - 45, hz], 4.5) for hx, hz in BAR_HOLES]) ^ inside
    post_holes = union([m_cyl([hx, y_front + 0.01, hz], [hx, y_front - INSERT_L, hz], INSERT_D / 2) for hx, hz in BAR_HOLES]
                       + [m_cyl([hx, y_front, hz], [hx, y_front - INSERT_L - 3.5, hz], 1.6) for hx, hz in BAR_HOLES])
    apert = union([m_cyl([xe, EYE_PLATE_DEPTH - 10, 0], [xe, y_glass - 0.2, 0], BEZEL_D / 2)
                   for xe in (-EYE_SPACING / 2, EYE_SPACING / 2)])
    info.update(y_glass=y_glass, y_bar_back=y_back)
    log('eyes: glass %.2f mm behind the rim plane, bar back face at y=%.2f' % (y_glass, y_back))

    # ---- radar
    y_wall_back = NASAL_RIM_Y + NASAL_RECESS + SHELL_T
    radar, radar_clear, radar_frame = radar_parts(y_wall_back)
    radar_frame = (radar_frame ^ inside) - radar_clear

    # ---- joints
    J = joints(G, sd, inside, cavity)
    info['joints'] = J['info']

    # ---- split
    big = 400.0
    face = crm ^ m_box([-big, -big, -big], [big, Y_SPLIT, big])
    back = crm ^ m_box([-big, Y_SPLIT, -big], [big, big, big])

    # face part
    face = face - eye_clear - radar_clear - apert
    face = union([face, posts, radar_frame] + J['face_add']) ^ m_box([-big, -big, -big], [big, Y_SPLIT, big])
    face = face - union([post_holes, apert, radar_clear] + J['face_cut'])
    face = face - eye_clear
    face = clean(face, 'face')

    # back part
    slot = union([mech['finger_clear'].transform(rot_x_about(*hinge, a))
                  for a in np.arange(JAW_CLOSE_STOP, JAW_OPEN_DEG + JAW_STOP_MARGIN + 0.01, 0.5)])
    pivot = mech['skull_pivot'] - slot - mech['skull_pivot_holes']
    sboss = union([m_cyl(p, p - np.array([0, 0, 40.0]), 4.5) for p in mech['bracket_bolts']]) ^ inside
    sboss_h = union([m_cyl(p + [0, 0, 0.01], p - [0, 0, INSERT_L], INSERT_D / 2) for p in mech['bracket_bolts']]
                    + [m_cyl(p, p - [0, 0, INSERT_L + 3.5], 1.6) for p in mech['bracket_bolts']])
    tposts = union([m_cyl([x, Y_TRAY, z], [x, Y_TRAY + 60, z], 4.5) for x, z in TRAY_POSTS]) ^ inside
    tposts_h = union([m_cyl([x, Y_TRAY - 0.01, z], [x, Y_TRAY + INSERT_L, z], INSERT_D / 2) for x, z in TRAY_POSTS]
                     + [m_cyl([x, Y_TRAY, z], [x, Y_TRAY + INSERT_L + 3.5, z], 1.6) for x, z in TRAY_POSTS])
    N = NECK
    neck = m_cyl([0, N['y'], N['z_bottom']], [0, N['y'], -12.0], N['r'])
    neck_h = m_cyl([0, N['y'], N['z_bottom'] - 0.01], [0, N['y'], N['z_bottom'] + N['insert_l']], N['insert_d'] / 2) + \
        m_cyl([0, N['y'], N['z_bottom']], [0, N['y'], N['z_bottom'] + N['insert_l'] + 4], 2.75)
    usb = m_cyl([USB_EXIT[0], USB_EXIT[1], -70], [USB_EXIT[0], USB_EXIT[1], -10], USB_EXIT[2] / 2)
    back = union([back, pivot, sboss, tposts, neck] + J['back_add']) ^ m_box([-big, Y_SPLIT, -big], [big, big, big])
    back = back - union([mech['cup_env'], mech['cup_slot'], mech['skull_pivot_holes'], slot, sboss_h, tposts_h, neck_h, usb]
                        + J['back_cut'])
    back = clean(back, 'back')

    # jaw
    jaw_part = clean(jaw_moving - mech['jaw_pad_holes'] - mech['jaw_pivot_holes'], 'jaw')

    tray, board = tray_parts()
    tray = clean(tray ^ cavity, 'tray')
    parts = dict(face=face, back=back, jaw=jaw_part, servo_bracket=mech['bracket'], tray=tray,
                 stand=stand(), dowel=dowel())
    for name, br in J['brackets']:
        parts['joint_bracket_' + name] = br
    P = servo_frame(hinge); St = SERVO
    horn_show = m_cyl(P(St['spline_top'] - 2.4, 0, 0), P(St['spline_top'] + 1.0, 0, 0), 3.6) + \
        mf.Manifold.batch_hull([m_cyl(P(St['spline_top'] - 0.8, 0, 0), P(St['spline_top'] + 1.0, 0, 0), 3.2),
                                m_cyl(P(St['spline_top'] - 0.8, -15, 0), P(St['spline_top'] + 1.0, -15, 0), 2.0)])
    hardware = dict(bar=bar, modules=modules, servo=mech['servo'], horn=horn_show, radar=radar, esp32=board)
    return dict(parts=parts, hardware=hardware, info=info, hinge=hinge, mech=mech, jaw_moving=jaw_moving,
                G=G, sh=sh, inside=inside, crm=crm)


# =============================================================== verification
def verify(R):
    P, H, hinge = R['parts'], R['hardware'], R['hinge']
    rep = dict(parts={}, collisions=[], jaw_sweep=[])
    for k, m in P.items():
        t = to_tri(m)
        rep['parts'][k] = dict(watertight=bool(t.is_watertight), bodies=len(m.decompose()),
                               volume_cm3=round(vol(m), 2), tris=m.num_tri(),
                               size=np.round(t.extents, 1).tolist())
    placed = {k: v for k, v in P.items() if k not in ('dowel',)}
    placed.update({k: v for k, v in H.items() if k not in ('horn',)})
    names = sorted(placed)
    ok_pairs = {('modules', 'bar')}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            A, B_ = placed[a], placed[b]
            ba, bb = np.array(A.bounding_box()), np.array(B_.bounding_box())
            if np.any(ba[:3] > bb[3:]) or np.any(bb[:3] > ba[3:]):
                continue
            v = vol(A ^ B_)
            if v > 0.005:
                rep['collisions'].append((a, b, round(v, 3)))
    others = union([P['face'], P['back'], H['servo'], P['servo_bracket'], P['stand']])
    jm = P['jaw']
    for a in np.arange(JAW_CLOSE_STOP, JAW_OPEN_DEG + JAW_STOP_MARGIN + 0.01, 1.0):
        v = vol(jm.transform(rot_x_about(*hinge, a)) ^ others)
        rep['jaw_sweep'].append((round(float(a), 1), round(v, 3)))
    # stop check: one step past each stop must collide (finger in the slot end)
    for a in (JAW_CLOSE_STOP - 1.5, JAW_OPEN_DEG + JAW_STOP_MARGIN + 1.5):
        rep.setdefault('beyond_stops', []).append((float(a), round(vol(jm.transform(rot_x_about(*hinge, a)) ^ P['back']), 3)))
    # joint brackets: the back part slides on along Y; nothing may catch on the way
    rep['bracket_slide'] = []
    for k, m in P.items():
        if k.startswith('joint_bracket'):
            worst = max(vol(m.translate([0, -d, 0]) ^ P['back']) for d in np.arange(0.5, JOINT_Y + 8, 1.0))
            rep['bracket_slide'].append((k, round(worst, 3)))
    return rep


# =============================================================== outputs
def rx(deg):
    a = np.radians(deg); c, s_ = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0, 0], [0, c, -s_, 0], [0, s_, c, 0]], float)


def ry(deg):
    a = np.radians(deg); c, s_ = np.cos(a), np.sin(a)
    return np.array([[c, 0, s_, 0], [0, 1, 0, 0], [-s_, 0, c, 0]], float)


PRINT_ORIENT = {   # rotation into print orientation (then dropped onto z = 0, centred)
    'face': rx(-90),            # seam face on the bed, face up
    'back': rx(90),             # seam face on the bed, crown up
    'jaw': rx(0),               # upright, as in the skull
    'servo_bracket': ry(90 * SERVO_SIDE),   # mounting plate on the bed
    'tray': rx(-90),            # plate on the bed, cradle up
    'stand': rx(0),
    'dowel': rx(0),
}


def print_pose(name, M):
    T = PRINT_ORIENT.get(name, rx(90) if name.startswith('joint_bracket') else rx(0))
    M = M.transform(T)
    b = np.array(M.bounding_box())
    return M.translate([-(b[0] + b[3]) / 2, -(b[1] + b[4]) / 2, -b[2]])


def export(R):
    for f in os.listdir(OUT):
        if f.endswith('.stl'):
            os.remove(os.path.join(OUT, f))
    for name, M in R['parts'].items():
        fn = os.path.join(OUT, name + '.stl')
        P = print_pose(name, M)
        for _ in range(3):
            to_tri(P).export(fn)
            t = trimesh.load(fn)                       # check what a slicer will read
            if t.is_watertight and len(t.split(only_watertight=False)) == 1:
                break
            P = clean(to_man(t), name)
        else:
            raise RuntimeError('%s is not watertight after export' % name)
    log('wrote %d STLs to %s' % (len(R['parts']), OUT))


SCAD = '/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD'
COLORS = dict(face='ivory', back='wheat', jaw='tan', servo_bracket='seagreen', tray='mediumpurple',
              stand='gray', bar='dimgray', modules='black', servo='royalblue', horn='crimson', radar='red',
              esp32='teal')


def render(R):
    import subprocess
    tmp = os.path.join(CACHE, 'render'); os.makedirs(tmp, exist_ok=True)
    items = dict(R['parts']); items.pop('dowel', None)
    items.update(R['hardware'])
    for k, m in items.items():
        to_tri(m).export(os.path.join(tmp, k + '.stl'))
    hinge = R['hinge']

    def scad(fname, body):
        with open(os.path.join(tmp, fname), 'w') as f:
            f.write(body)
        return os.path.join(tmp, fname)

    def col(k):
        return COLORS.get(k, 'orange')

    def asm(skip=(), explode=None, jaw_deg=0.0, extra=''):
        lines = []
        for k in items:
            if k in skip:
                continue
            tr = ''
            if explode and k in explode:
                tr = 'translate([%g,%g,%g]) ' % tuple(explode[k])
            if k in ('jaw',) and jaw_deg:
                tr += 'translate([0,%g,%g]) rotate([%g,0,0]) translate([0,%g,%g]) ' % (
                    hinge[0], hinge[1], jaw_deg, -hinge[0], -hinge[1])
            lines.append('%scolor("%s") import("%s.stl");' % (tr, col(k), k))
        return '\n'.join(lines) + extra

    jobs = []
    a = scad('asm.scad', asm())
    jobs.append(('skull_front.png', a, '0,40,-20,90,0,0,420'))
    jobs.append(('skull_side.png', a, '0,40,-20,90,0,90,420'))
    jobs.append(('skull_iso.png', a, '0,40,-20,70,0,330,440'))
    jobs.append(('skull_bottom.png', scad('bot.scad', asm(skip=('stand',))), '0,40,-20,180,0,0,400'))
    o = scad('open.scad', asm(jaw_deg=JAW_OPEN_DEG))
    jobs.append(('skull_jaw_open.png', o, '0,40,-20,80,0,60,440'))
    ex = dict(face=(0, -90, 0), bar=(0, -45, 0), modules=(0, -45, 0), radar=(0, -70, 0), jaw=(0, 0, -70),
              stand=(0, 0, -110), tray=(0, 70, 0), esp32=(0, 70, 0), back=(0, 25, 0),
              servo=(40, 25, -40), servo_bracket=(40, 25, -40), horn=(40, 25, -40))
    for k in items:
        if k.startswith('joint_bracket'):
            ex[k] = (0, -40, 0)
    e = scad('expl.scad', asm(explode=ex))
    jobs.append(('skull_exploded.png', e, '0,20,-60,65,0,300,700'))
    procs = []
    for fn, f, cam in jobs:
        procs.append(subprocess.Popen([SCAD, '-o', os.path.join(HERE, fn), '--preview', '--imgsize=1400,1100',
                                       '--camera=' + cam, '--projection=o', '--colorscheme=Tomorrow', f],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    for p in procs:
        p.wait()
    sections(R, items)
    log('rendered %d previews + sections' % len(jobs))


def sections(R, items):
    """Filled cross-sections (matplotlib) through the orbits and the jaw mechanism."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch, Patch
    from matplotlib.path import Path
    cols = dict(face='#f2e6c4', back='#d9b87c', jaw='#b88a4a', bar='#666666', modules='#111111',
                servo='#3355cc', servo_bracket='#2e8b57', horn='#cc2233', radar='#ee2222', esp32='#119999',
                tray='#9370db', stand='#999999')
    maps = dict(z=(np.eye(4)[:3], ('x', 'y'), 1), x=(np.array([[0, 1, 0, 0], [0, 0, 1, 0], [1, 0, 0, 0]], float), ('y', 'z'), 1),
                y=(np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0]], float), ('x', 'z'), -1))

    def section(ax, axis, c, xl, yl, title):
        T, lab, sg = maps[axis]
        used = set()
        for n, m in items.items():
            pol = m.transform(T).slice(sg * c).to_polygons()
            if not pol:
                continue
            verts, codes = [], []
            for p in pol:
                verts += list(p) + [p[0]]; codes += [Path.MOVETO] + [Path.LINETO] * (len(p) - 1) + [Path.CLOSEPOLY]
            k = 'joint brackets' if n.startswith('joint') else n
            ax.add_patch(PathPatch(Path(verts, codes), fc=cols.get(n, '#ff9900'), ec='k', lw=0.5))
            used.add((k, cols.get(n, '#ff9900')))
        ax.set_xlim(*xl); ax.set_ylim(*yl); ax.set_aspect('equal'); ax.grid(alpha=0.3)
        ax.set_xlabel(lab[0] + ' (mm)'); ax.set_ylabel(lab[1] + ' (mm)'); ax.set_title(title)
        ax.legend(handles=[Patch(fc=c_, ec='k', label=k) for k, c_ in sorted(used)], loc='upper right', fontsize=8)

    fig, ax = plt.subplots(1, 2, figsize=(18, 8))
    section(ax[0], 'z', 0.0, (-75, 75), (-30, 45), 'Section through the orbit centres (z = 0), seen from above; face toward -y')
    section(ax[1], 'x', EYE_SPACING / 2, (-25, 45), (-35, 30), 'Section through the right-hand eye (x = +27.5)')
    fig.tight_layout(); fig.savefig(os.path.join(HERE, 'skull_section_orbits.png'), dpi=90); plt.close(fig)
    fig, ax = plt.subplots(1, 2, figsize=(18, 8))
    section(ax[0], 'x', 12.0, (20, 120), (-60, 20), 'Section x = +12 (servo, neck boss, tray)')
    section(ax[1], 'y', R['hinge'][0], (-60, 60), (-60, 10), 'Section through the hinge axis (y = %.1f)' % R['hinge'][0])
    fig.tight_layout(); fig.savefig(os.path.join(HERE, 'skull_section_jaw.png'), dpi=90); plt.close(fig)


def main():
    R = build()
    rep = verify(R)
    rep['info'] = R['info']
    for k, v in rep['parts'].items():
        log('%-24s %6.1f cm3  %s mm  watertight=%s bodies=%d' % (k, v['volume_cm3'], v['size'], v['watertight'], v['bodies']))
    log('collisions (> 0.005 cm3):', rep['collisions'] or 'none')
    log('bracket slide-on interference (cm3):', rep['bracket_slide'])
    log('jaw sweep overlaps:', [a for a in rep['jaw_sweep'] if a[1] > 0.005] or 'none',
        '| past the stops:', rep['beyond_stops'])
    export(R)
    with open(os.path.join(OUT, 'build_report.json'), 'w') as f:
        json.dump(rep, f, indent=1, default=lambda o: float(o) if np.isscalar(o) else str(o))
    if '--no-render' not in sys.argv:
        render(R)
    return R, rep


if __name__ == '__main__':
    main()
