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
import liners  # noqa: E402

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
SIMPLIFY_TOL = 0.03     # mm; mesh simplification of the big parts before export
MC_SIGMA = 1.2          # voxels; smoothing of the distance field before marching cubes
INNER_SKIN = 0.7        # marching-cubes inner layer starts this far below the voxel surface

# --- eyes ------------------------------------------------------------------
EYE_DEPTH = 15.0        # screen glass behind the orbit rim plane (socket bowl depth)
SOCKET_WALL = 2.0       # bowl wall (>= 1.6)
SCREEN_GAP = 0.6        # bowl back face (bezel) to glass
APERTURE_D = 18.5       # opening at the bottom of the bowl (active circle 18.0, glass 20.12)
ORBIT_SHRINK = 0.0      # pull the orbit rim outline in by this fraction
SOCKET_N = 120          # points round each loft ring
SOCKET_K = 28           # rings from rim to bottom
EYE_DZ = 2.0            # move both eyes up/down from the measured orbit centre

BASE_CLOSE_R = 15.0     # larger closing radius on the skull base (hidden on the stand)
BASE_ROI = dict(y_min=22.0, z_max=-8.0)   # base region: behind the palate, below the orbits
TEMPLE_CLOSE_R = 22.0   # closes the gap behind/under each zygomatic arch
TEMPLE_ROI = dict(abs_x_min=34.0, y_min=8.0, y_max=72.0, z_min=-50.0, z_max=2.0)
# Temporal fossa behind each orbit (above the arch): filled almost flush, like a
# prop skull's full temples. This also widens the space behind the eyes.
FOSSA_CLOSE_R = 30.0
FOSSA_ROI = dict(abs_x_min=30.0, y_min=4.0, y_max=110.0, z_min=-6.0, z_max=75.0)
FOSSA_IGNORE_BELOW = -6.0   # the fossa fill ignores bone below this (the arches), so it hugs the skull
FOSSA_RECESS = 0.0
SMOOTH_SIGMA = 1.5      # voxels; smooths the outside-air boundary (webs) before the shell is taken
CAVITY_PROBE = (0.0, 75.0, 40.0)
# Everything behind the eyes, inside the skull's hull, is made "inside" (sealed
# at WEB_RECESS behind the hull surface). Otherwise outside air reaches in
# through the gaps beside the arches and the shell lines it with walls, which
# end up as a plate behind the eyes that blocks assembly.
BEHIND_EYES = dict(box=((-75.0, -5.0, -18.0), (75.0, 70.0, 50.0)), close_r=22.0)
BEHIND_PROBE = (0.0, 22.0, 0.0)  # between the bowls, behind the eyes: must be inside          # a point inside the brain cavity (leak check)

# --- nose / radar ------------------------------------------------------------
NASAL_RIM_Y = -6.0      # piriform aperture rim depth (eye frame)
NASAL_RECESS = 6.0      # nasal window front face behind the aperture rim
NASAL_T = 1.8           # = radar window thickness
NASAL_BOTTOM = 0.72     # bowl bottom outline = rim outline scaled by this
# Wall across the back of the nasal cavity (in front of the choanae). Without it
# the nasal cavity is open to the throat, counts as outside air and the shell
# lines it with walls right behind the eye bar.
CHOANA = dict(y0=22.0, y1=24.5, seeds=[(-6.0, -28.0), (6.0, -28.0), (0.0, -20.0)], roi=(-24.0, 24.0, -50.0, 2.0))
NOSE_PROBE = (0.0, 15.0, -27.0)   # must end up inside (behind the window, in front of the choana wall)
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
HINGE_CLEAR_EXTRA = 1.4 # extra carve round the condyles (lost to the shell-mesh smoothing)
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
BAR_HOLES = [(-27.5, 16.0), (27.5, 16.0)]   # = skull_mount_holes in the scad
BAR_BOLTS = [0]         # which holes get a bolt + insert post; the others get a printed key peg (Ø3 in the 3.6 slot)
BAR_PLATE = dict(half_w=27.5 + 0.14 + 4.0, half_h=10.4, corner_r=4.0, chamfer=1.0, boss_d=9.0, slot=3.0)
MODULE_ROT = 90         # tip toward the nose (scad module_rot)
FIT = 0.75              # general clearance round parts that drop in
EYE_BAR_BACKOFF = 12.0  # the bar + LCDs come straight back off the posts this far, then lift out
TOOL_D = 8.0            # tool-access check: driver shaft + hand
TOOL_TIP_D = 5.5        # ... the first few mm (bit in a counterbore)
TOOL_TIP_L = 8.0        # ... over the first this many mm past the counterbore
TOOL_LEN = 100.0

# --- split + joints -------------------------------------------------------------
# Skull-cap split. One plane, just above the brow ridge at the front and
# sloping down toward the back: z = z0 - slope * (y - y0). Below it is the
# chassis (face, orbits, cranial base, hinge, servo, ESP32, neck); above it is
# the cap, a cover with no load that lifts off along the plane normal and opens
# the whole top for hands and tools.
SEAM = dict(y0=-5.0, z0=32.0, slope=0.04)
# Back cover: everything below the cap, behind Y_BACK and above Z_FLOOR. It
# lifts off upward (after the cap) and opens the space right behind the eye bar.
Y_BACK = 32.0           # front/back cut, just behind the eye bar and its screw heads
Z_FLOOR = -14.0          # the chassis keeps the cranial floor below this behind Y_BACK
JOINT_H = 12.0          # radial cover screws this far above their seam
JOINTS = []             # no separate brackets: covers hook / sit on lips and take one screw each
LIP = dict(h=5.0, t=2.0, gap=0.5, chamfer=1.5)   # chassis lip inside the back cover's lower edge
CAP_HOOK = dict(w=20.0, slide=6.0, gap=0.5)      # cap hooks under a forehead ledge after a 6 mm slide forward
DOWELS = []
DOWEL_D = 4.0
DOWEL_HOLE_D = 5.0      # loose
INSERT_D = 4.0          # M3 heat-set insert pilot bore
INSERT_L = 5.7          # insert length
INSERT_BORE = INSERT_L + 1.0   # pilot bore depth (insert + 1 mm)
INSERT_WALL = 1.6       # minimum wall round the pilot bore
INSERT_RELIEF = 3.5     # Ø3.2 relief past the bore bottom for a long screw tip
INSERT_MIN_ENGAGE = 4.0 # screw thread engaged in the insert
M3_CLEAR_D = 3.4        # clearance hole for M3 in a clamped part
M3_HEAD = dict(d=5.5, h=3.0)
M2_HEAD = dict(d=3.8, h=1.6)
M3_WASHER = dict(d=9.0, h=3.8)   # M3 head on a Ø9 (DIN 9021) washer: the seat is the washer

# --- electronics / base --------------------------------------------------------------
RADAR = dict(L=35.0, W=7.0, T=1.2, comp=3.0, z=-27.5)    # HLK-LD2410C 35 x 7 mm
# Servo tray: ONE printed part (servo_tray.stl) = the servo L-bracket (its flange takes the 2x M3x8
# into the two insert bosses; no other screws) + a bridge slab + two deep ribs + a narrow ESP32
# cradle plate between the header rows. It drops in from above (cap off) with the servo already
# screwed to it on the bench. The board lies flat, pins down, long axis along X, centred on the
# neck-bore line (y = NECK y), USB end at +X (servo side), high enough that the cable can loop
# down into the neck bore; it lifts out of the cradle without touching the servo.
ESP32 = dict(L=55.0, W=28.0, T=1.6, x_usb=5.5, y=90.0, z=30.0)   # DevKitC-VIE (no holes); x of the USB end, PCB bottom z
TRAY = dict(t=3.0, half_w=9.5, standoff=16.0, wall=2.0, fit=0.5, ledge=5.0, rib_y=7.0, rib_t=2.0,
            bridge_y0=70.0, notch=3.5, tie_w=16.2, far_wall_w=7.0)   # cradle plate between the header rows; ribs at y +-rib_y; cable notch in the bridge
# keep-outs: DuPont housings on both header rows (pins down), their wires (out of the bottom, then
# sideways), the micro-USB plug, its insertion path and grip, the cable to the neck bore, EN/BOOT
DUPONT = dict(row_y=11.4, w=2.6, h=14.0, inset=3.4, wire=15.0)   # 19-pin rows, 48.3 mm long
USB = dict(plug_w=11.0, plug_h=8.0, plug_l=20.0, boot_l=10.0, boot_d=7.0, z_up=1.5, path_l=36.0, clear=0.5,
           grip=9.0, grip_up=30.0, cable_d=4.5, bend_r=15.0)
BUTTONS = dict(dx=4.0, dy=10.0, finger_d=8.0, reach=45.0)   # EN / BOOT beside the USB: dx in from the end, +-dy
TIE_BAR = dict(y=114.0, w=12.0, t=4.0, h=10.0, tunnel_w=7.0, tunnel_h=5.0)  # zip-tie arch on the floor behind the neck
# USB cable leaves through the neck: hollow neck boss (Ø14 bore, passes a USB-A
# plug), into the stand column, which has an open slot down its full length and
# across the base, so the cable drops in sideways.
NECK = dict(y=90.0, r=15.0, z_bottom=-58.0, bore=14.0, screw_z=6.0)   # stand screw: M3 along +Y into an insert
STAND = dict(base_d=110.0, base_t=6.0, col_d=38.0, bore=18.0, h=78.0, socket=10.0, slot=8.0, fit=0.4)

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


def polar_outline(mask, G, c, n, step=0.1, rmax=40.0):
    """Radius of the mask boundary from centre c=(x, z) along n directions."""
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    rs = np.arange(0.5, rmax, step)
    r = np.zeros(n)
    for i, t in enumerate(th):
        xs = c[0] + rs * np.cos(t); zs = c[1] + rs * np.sin(t)
        v = ndimage.map_coordinates(mask.astype(np.float32), [(xs - G.o[0]) / G.h, (zs - G.o[2]) / G.h], order=1)
        out = np.where(v < 0.5)[0]
        r[i] = rs[out[0]] if len(out) else rmax
    return th, r


def circ_smooth(a, w):
    k = np.ones(w) / w
    return np.convolve(np.r_[a[-w:], a, a[:w]], k, mode='same')[w:-w]


def rings_mesh(rings, cap_first=None, cap_last=None, cyclic=False):
    """Closed surface through rings (list of (N,3)); fan caps to the given points."""
    rings = [np.asarray(r, float) for r in rings]
    N = len(rings[0]); V = np.vstack(rings); F = []
    nr = len(rings)
    pairs = [(i, i + 1) for i in range(nr - 1)] + ([(nr - 1, 0)] if cyclic else [])
    for a, b in pairs:
        for j in range(N):
            j1 = (j + 1) % N
            p, q, r_, s_ = a * N + j, a * N + j1, b * N + j, b * N + j1
            F += [[p, r_, q], [q, r_, s_]]
    V = list(V)
    if cap_first is not None:
        ci = len(V); V.append(cap_first)
        F += [[ci, j, (j + 1) % N] for j in range(N)]
    if cap_last is not None:
        ci = len(V); V.append(cap_last); o = (nr - 1) * N
        F += [[ci, o + (j + 1) % N, o + j] for j in range(N)]
    t = trimesh.Trimesh(np.array(V), np.array(F), process=True)
    trimesh.repair.fix_normals(t)
    if t.volume < 0:
        t.invert()
    assert t.is_watertight, 'loft not watertight'
    return to_man(t)


def socket(c, th, r_rim, y_rim, r_bot, y_bot, W, K=SOCKET_K, flat_bottom=False):
    """Smooth bowl lofted from the rim outline (r_rim, y_rim per angle th) to a
    bottom outline (r_bot per angle) at depth y_bot. Profile per angle is a
    quarter ellipse: straight back at the rim, curving in to a flat bottom.
    Returns wall (thickness W behind the visible surface), air (inside the bowl,
    extended forward), plug (bowl + wall, for the voxel stage) and paint (a
    0.2 mm skin on the visible surface, renders only)."""
    s_ = np.linspace(0, np.pi / 2, K)[:, None]
    r = r_bot + (r_rim - r_bot) * np.cos(s_)
    y = y_rim + (y_bot - y_rim) * np.sin(s_)
    nr = (y_bot - y_rim) * np.cos(s_); ny = (r_rim - r_bot) * np.sin(s_)
    L = np.hypot(nr, ny); nr /= L; ny /= L
    ct, st = np.cos(th), np.sin(th)

    def P(rr, yy):
        return np.stack([c[0] + rr * ct, yy, c[1] + rr * st], axis=-1)
    inner = P(r, y)
    outer = P(r + W * nr, y + W * ny)
    paint_in = P(r - 0.2 * nr, y - 0.2 * ny)
    ctr = lambda yy: np.array([c[0], yy, c[1]])
    if flat_bottom:
        wall = rings_mesh([inner[k] for k in range(K)][::-1] + [outer[k] for k in range(K)],
                          cap_first=ctr(y_bot), cap_last=ctr(y_bot + W))
        paint = rings_mesh([paint_in[k] for k in range(K)][::-1] + [inner[k] for k in range(K)],
                           cap_first=ctr(y_bot - 0.2), cap_last=ctr(y_bot))
    else:
        wall = rings_mesh([inner[k] for k in range(K)] + [outer[k] for k in range(K)][::-1], cyclic=True)
        paint = rings_mesh([paint_in[k] for k in range(K)] + [inner[k] for k in range(K)][::-1], cyclic=True)
    front = P(r_rim, y_rim - 12.0)
    air = rings_mesh([front] + [inner[k] for k in range(K)], cap_first=ctr(float(np.mean(y_rim)) - 12.0),
                     cap_last=ctr(y_bot))
    plug = rings_mesh([outer[k] for k in range(K)], cap_first=ctr(float(np.mean(y_rim))), cap_last=ctr(y_bot + W))
    return dict(wall=wall, air=air, plug=plug, paint=paint,
                prof=dict(c=c, th=th, r_rim=r_rim, y_rim=y_rim, r_bot=r_bot, y_bot=y_bot, W=W, flat=flat_bottom))


def make_plugs(G, B, scale):
    """Eye sockets and nose: smooth lofted bowls. Their solids go to the voxel
    stage as plugs (the bowl region becomes inside) and their air as forced
    outside; the exact meshes replace the voxel surfaces afterwards."""
    h = G.h
    Df = front_depth(B, G.o, h)                       # [ix, iz]
    Dn = np.nan_to_num(Df, nan=1e3)
    orbs = measure_orbits(Df, G.o, h, seeds=((-EYE_SPACING / 2, 0.0), (EYE_SPACING / 2, 0.0)),
                          margin=ORBIT_RIM_MARGIN * scale)
    plugs, info, sockets = {}, {}, {}
    y_bot = EYE_DEPTH - SCREEN_GAP - SOCKET_WALL
    for side, o, xc in (('eyeL', orbs[0], -EYE_SPACING / 2), ('eyeR', orbs[1], EYE_SPACING / 2)):
        c = (xc, 0.0)
        th, rb = polar_outline(o['mask'], G, c, SOCKET_N)
        rb = circ_smooth(rb, 5)
        yr = ndimage.map_coordinates(np.clip(Dn, -60, 60), [(c[0] + (rb + 1.5) * np.cos(th) - G.o[0]) / h,
                                                           (c[1] + (rb + 1.5) * np.sin(th) - G.o[2]) / h], order=1)
        yr = np.minimum(circ_smooth(yr, 7), y_bot - 2.0)
        rr = rb * (1 - ORBIT_SHRINK)
        sk = socket(c, th, rr, yr, APERTURE_D / 2, y_bot, SOCKET_WALL)
        sockets[side] = sk
        plugs[side] = G.vox(sk['plug'])
        info[side] = dict(x=o['x'], z=o['z'], rim_y=o['rim_y'], breadth=o['breadth'], height=o['height'],
                          rim_y_range=[float(yr.min()), float(yr.max())])
        log('%s: measured centre x=%.2f z=%.2f (frame), opening %.1f x %.1f, rim y %.1f..%.1f, bowl bottom y=%.1f'
            % (side, o['x'], o['z'], o['breadth'], o['height'], yr.min(), yr.max(), y_bot))
    # nose
    lab, _ = ndimage.label(Dn > NASAL_RIM_Y + 4.0)
    nm = np.zeros_like(Dn, bool)
    for sx, sz in NASAL_SEEDS:
        l = lab[G.idx((sx, 0, sz))[0], G.idx((sx, 0, sz))[2]]
        if l:
            nm |= lab == l
    assert nm.sum() * h * h < 1500, 'nasal opening leaks'
    nm = ndimage.binary_fill_holes(ndimage.binary_closing(nm, iterations=4))
    ii, kk = np.where(nm)
    c = (float(G.x[ii].mean()), float(G.z[kk].mean()))
    th, rb = polar_outline(nm, G, c, SOCKET_N)
    rb = circ_smooth(rb, 5)
    yr = ndimage.map_coordinates(np.clip(Dn, -60, 60), [(c[0] + (rb + 1.5) * np.cos(th) - G.o[0]) / h,
                                                       (c[1] + (rb + 1.5) * np.sin(th) - G.o[2]) / h], order=1)
    y_win = NASAL_RIM_Y + NASAL_RECESS
    yr = np.minimum(circ_smooth(yr, 7), y_win - 2.0)
    sk = socket(c, th, rb, yr, rb * NASAL_BOTTOM, y_win, NASAL_T, flat_bottom=True)
    sockets['nasal'] = sk
    plugs['nasal'] = G.vox(sk['plug'])
    C = CHOANA
    plugs['choana'] = fill_slab_holes(G, B, 1, C['y0'], C['y1'], C['seeds'], C['roi'], close_r=1.0)
    info['nasal'] = dict(centre=list(c), window_y=y_win)
    for k, v in plugs.items():
        log('plug %-6s %6.2f cm3' % (k, v.sum() * h ** 3 / 1000))
    return plugs, info, Df, sockets


def closing_env(S, R, h):
    """Morphological closing of S with a ball of radius R, on a grid padded so
    the dilated solid never touches the border."""
    p = int(np.ceil(R / h)) + 2
    Sp = np.pad(S, p)
    aout = outside(edt(Sp, h) <= R)
    return (edt(aout, h) > R)[p:-p, p:-p, p:-p]


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
    f = FOSSA_ROI
    fossa = (abs(X) >= f['abs_x_min']) & (Y >= f['y_min']) & (Y <= f['y_max']) & (Z >= f['z_min']) & (Z <= f['z_max'])
    rois.append((FOSSA_CLOSE_R, fossa))
    env = S0.copy()
    S0f = S0 & ~((abs(X) > FOSSA_ROI['abs_x_min']) & (Z < FOSSA_IGNORE_BELOW))
    for R, roi in rois:
        log('closing r=%g' % R)
        e = closing_env(S0f if roi is fossa else S0, R, h)
        env |= e if roi is None else (e & roi)
    denv = edt(~env, h)
    rec = np.where(fossa, FOSSA_RECESS, WEB_RECESS)
    core = env & (denv >= rec) & (denv <= rec + WEB_T)
    small = ndimage.binary_closing(S0, iterations=int(round(SMALL_CLOSE_R / h)), border_value=0) | S0
    M = small | core
    be = BEHIND_EYES
    (x0, y0, z0), (x1, y1, z1) = be['box']
    ebe = closing_env(S0, be['close_r'], h)
    M |= ebe & (edt(~ebe, h) >= WEB_RECESS) & (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1) & (Z >= z0) & (Z <= z1)
    if extra_in is not None:
        M |= extra_in
    log('outside air')
    A = outside(M)
    leak = A[G.idx(CAVITY_PROBE)]
    if SMOOTH_SIGMA > 0:           # smooth the air/solid boundary (voxel stair-steps on webs)
        As = ndimage.gaussian_filter(A.astype(np.float32), SMOOTH_SIGMA) > 0.5
        As &= ndimage.binary_dilation(A, iterations=2)       # only nudge the boundary
        As = As & outside(~As)
        if As[G.idx(CAVITY_PROBE)]:
            log('smoothing would open a thin wall; using the unsmoothed boundary')
        else:
            A = As
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
    band = mc_mesh(np.minimum(sd + 0.6, t + 0.25 - sd), G, 0.0, step=2, sigma=MC_SIGMA)
    inner = mc_mesh(np.minimum(sd - INNER_SKIN, t - sd), G, 0.0, step=2, sigma=MC_SIGMA)
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


def insert_bore(p, u, relief=INSERT_RELIEF):
    """Cutter for an M3 heat-set insert: a Ø INSERT_D pilot bore INSERT_BORE deep
    from the joint face point p into the part along unit u (it starts 0.3 mm in
    front of the face so it always opens there), then a Ø3.2 relief for the
    screw tip."""
    p = np.asarray(p, float); u = np.asarray(u, float); u = u / np.linalg.norm(u)
    bore = m_cyl(p - u * 0.3, p + u * INSERT_BORE, INSERT_D / 2)
    return bore + m_cyl(p + u * (INSERT_BORE - 0.1), p + u * (INSERT_BORE + relief), 1.6) if relief > 0 else bore


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
    front = cr ^ m_box([-90, -80, -90], [90, 25.0, hinge[1] - 10.0])     # upper teeth and palate only
    for a in np.arange(-30.0, 15.01, 0.25):
        if jaw.transform(rot_x_about(*hinge, a)).min_gap(front, TEETH_GAP + 0.5) >= TEETH_GAP:
            return float(a)
    raise RuntimeError('no closed angle found')


# =============================================================== jaw mechanism
HORN_JAW_HOLES = (10.0, 14.0)   # Ø2.2 pilots through the jaw pad and ramus, along the horn arm (M2x16 self-tapping)
HORN_ARM_DEG = 20.0     # horn arm direction: this far forward of straight down (along the condyle neck)
HORN_SCREW_L = 16.0
HORN_SCREW_SEAT_MAX = 46.5   # |x| of the screw-head seat at most: the M2x16 then reaches 0.5 mm past the horn arm
# Jaw knuckles: on each side a teardrop outline (seen along the axis) -- a disc of
# radius r round the hinge axis, hulled with a tail disc tail_r at tail mm down the
# condyle neck (HORN_ARM_DEG forward of straight down) -- solid from the pad face
# out to the ramus' outer skin and at least t thick. Above the condyle trim only
# the r disc is kept (it turns in place, so it sweeps only itself); it runs out to
# |x| = x_end as a solid boss round the axis (pivot side: the bolt-head counterbore).
JAW_PAD = dict(r=8.0, tail_r=7.0, tail=16.0, t=13.0, x_end=47.0)    # servo side (smaller disc: keeps the carve over it, and the view in to the servo, low)
PIVOT_PAD = dict(r=9.5, tail_r=7.0, tail=16.0, t=14.0, x_end=48.5)  # pivot side (x_end = the old head_x)
HORN_HUB_CB = 4.0       # Ø7 counterbore depth in the servo-side knuckle for the horn screw head
PAD_FILLET = 4.0        # fillet radius where the knuckles meet the ramus
CONDYLE_TRIM = 3.5      # the condyle heads are trimmed this far above the axis (outside the knuckle discs)
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
    # horn hub / screw-head access through the pad; the horn-screw holes are cut
    # in build() once the pad exists (their counterbores depend on it)
    # (Ø7 x HORN_HUB_CB for the screw head, then Ø5 through for a driver, so the
    # horn screw comes out with the jaw on)
    out['jaw_pad_holes'] = m_cyl([side * (HORN_FACE_X - 1), hinge[0], hinge[1]], [side * (HORN_FACE_X + HORN_HUB_CB), hinge[0], hinge[1]], 3.5) + \
        m_cyl([side * (HORN_FACE_X - 1), hinge[0], hinge[1]], [side * (HORN_FACE_X + 20), hinge[0], hinge[1]], 2.5)
    # pivot side
    o = -side
    x_head = o * (PIVOT_FACE_X + 14.5)               # bolt head seat (M3x20: 14.5 jaw + 0.5 gap + 5 insert)
    out['jaw_pivot_holes'] = union([m_cyl([o * (PIVOT_FACE_X - 1), *hinge], [o * 60, *hinge], 1.75),
                                    m_cyl([x_head, *hinge], [o * 70, *hinge], 3.3)])
    xs0 = o * (PIVOT_FACE_X - 0.5)
    out['skull_pivot'] = union([m_cyl([xs0, *hinge], [o * 22.0, *hinge], 15.0),
                                m_box([min(xs0, o * 22.0), hinge[0] - 9, hinge[1]],
                                      [max(xs0, o * 22.0), hinge[0] + 9, hinge[1] + 15])])
    out['skull_pivot_holes'] = insert_bore([xs0, *hinge], [-o, 0, 0])
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
def horn_dir():
    """Unit (y, z) direction of the horn arm (and the horn screws) from the hinge axis."""
    a = np.radians(HORN_ARM_DEG)
    return np.array([-np.sin(a), -np.cos(a)])


def knuckle_outline(dy, dz, P):
    """Teardrop (seen along the axis): the hull of the r disc on the axis and the
    tail_r disc `tail` mm along horn_dir(). dy, dz: offsets from the axis."""
    d = horn_dir()
    t_ = np.clip(dy * d[0] + dz * d[1], 0, P['tail'])        # nearest point on the spine
    rr = np.hypot(dy - t_ * d[0], dz - t_ * d[1])
    return rr <= P['r'] + (P['tail_r'] - P['r']) * t_ / P['tail']


def knuckle_keep(hinge, side, P, x0):
    """The part of the knuckle kept above the condyle trim: the r disc round the
    axis from the pad face to x_end (a cylinder on the axis sweeps only itself)."""
    return m_cyl([side * x0, *hinge], [side * P['x_end'], *hinge], P['r'])


def jaw_pads(jaw, hinge):
    """Knuckles on the inside of each condyle neck, as one voxel solid per side
    (see JAW_PAD / PIVOT_PAD): inside the teardrop outline the jaw is filled solid
    from the pad face |x| = x0 out to 0.8 mm under the ramus' outer skin, and at
    least t thick where there is no ramus outside; the corner where the knuckle
    meets the ramus gets a PAD_FILLET (Euclidean closing), so the knuckle is grown
    out of the bone rather than butted onto it. Returns {side: manifold}."""
    h = 0.3; out = {}
    for name, sg, x0, P in (('servo', SERVO_SIDE, HORN_FACE_X, JAW_PAD), ('pivot', -SERVO_SIDE, PIVOT_FACE_X, PIVOT_PAD)):
        t = P['t']
        lo = np.array([min(sg * (x0 - 2), sg * (x0 + 26)), hinge[0] - 32, hinge[1] - 36])
        hi = np.array([max(sg * (x0 - 2), sg * (x0 + 26)), hinge[0] + 26, hinge[1] + 14])
        G = Grid(lo, hi, h, pad=1.0)
        J = G.vox(jaw)
        X, Y, Z = G.coords()
        s_ = sg * X                                              # |x| measured outward from the midline
        W = knuckle_outline(Y - hinge[0], Z - hinge[1], P)
        if sg > 0:                                               # outer surface: largest |x| with bone in the column
            last = np.where(J.any(0), J.shape[0] - 1 - np.argmax(J[::-1], axis=0), -1)
            x_out = np.where(last >= 0, G.o[0] + last * h, -1e9)
        else:
            first = np.where(J.any(0), np.argmax(J, axis=0), -1)
            x_out = np.where(first >= 0, -(G.o[0] + first * h), -1e9)
        x_out = x_out[None]
        xa = x0 - 2.0                                            # voxel solid starts past the face; cut flat at x0 below
        slab = W & (s_ >= xa) & (s_ <= x0 + t)
        fill = W & (s_ >= xa) & (s_ <= x_out - 0.8)
        S = J | slab | fill
        R_ = PAD_FILLET
        Sc = edt(~(edt(S, h) <= R_), h) > R_                      # closing with a ball of radius PAD_FILLET
        Wd = edt(W, h) <= R_ + 1.0
        fil = Sc & Wd & (s_ >= xa) & ((s_ <= x_out - 0.8) | (s_ <= x0 + t + R_))
        pad = slab | fill | fil
        M = mc_mesh(ndimage.gaussian_filter(pad.astype(np.float32), 1.0) - 0.5, G, 0.0, step=1)
        face_cut = m_box([sg * x0 if sg > 0 else -200, -200, -200], [200 if sg > 0 else sg * x0, 200, 200])
        out[name] = (M ^ face_cut) + knuckle_keep(hinge, sg, P, x0)   # pad face flat at x0
    return out


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
    rc = b['corner_r']
    cx, cy, ch = b['half_w'] - rc, b['half_h'] - rc, b['chamfer']
    pts = [(sx * cx, cy) for sx in (-1, 1)] + [(sx * (cx - ch), -cy) for sx in (-1, 1)] + \
        [(sx * cx, -cy + ch) for sx in (-1, 1)]
    parts = [mf.Manifold.batch_hull([m_cyl([px, pz, -0.5], [px, pz, BAR_T], rc + c) for px, pz in pts])]
    for hx, hz in BAR_HOLES:
        parts.append(mf.Manifold.batch_hull([m_cyl([hx, hz, -0.5], [hx, hz, BAR_T], b['boss_d'] / 2 + b['slot'] / 2 + c),
                                             m_cyl([hx, 0, -0.5], [hx, 0, BAR_T], b['boss_d'] / 2 + c)]))
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


def seam():
    """Seam plane: unit normal n (pointing into the cap) and a point p0."""
    n = np.array([0.0, SEAM['slope'], 1.0]); n /= np.linalg.norm(n)
    return n, np.array([0.0, SEAM['y0'], SEAM['z0']])


def seam_z(y):
    return SEAM['z0'] - SEAM['slope'] * (y - SEAM['y0'])


def plane(name):
    if name == 'cap':
        return seam()
    return np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, Z_FLOOR])


def region(name):
    """Solid regions of the three parts."""
    big = 500.0
    below = halfspace(False)
    behind = m_box([-big, Y_BACK, Z_FLOOR], [big, big, big])
    if name == 'cap':
        return halfspace(True)
    if name == 'back':
        return below ^ behind
    return below - behind


def halfspace(upper, offset=0.0, pl=None):
    """Big solid on one side of a seam plane (shifted by offset along n)."""
    n, p0 = seam() if pl is None else pl
    B = mf.Manifold.cube([1000.0, 1000.0, 500.0]).translate([-500.0, -500.0, 0.0 if upper else -500.0])
    a = -np.arctan2(n[1], n[2])                     # rotate +Z onto n about X
    c, s_ = np.cos(a), np.sin(a)
    M = np.array([[1, 0, 0, 0], [0, c, -s_, 0], [0, s_, c, 0]], float)
    M[:, 3] = p0 + n * offset
    return B.transform(M)


def obox_n(o, er, en, et, r, h, t):
    """Box in the local joint frame: r radial, h along the seam normal, t along the seam."""
    M = np.zeros((3, 4)); M[:, 0] = er; M[:, 1] = en; M[:, 2] = et; M[:, 3] = o
    lo = np.array([r[0], h[0], t[0]]); hi = np.array([r[1], h[1], t[1]])
    return mf.Manifold.cube(list(hi - lo)).translate(list(lo)).transform(M)


def joints(G, sd, inside, cavity, corridor):
    """Bracket joints across the seams. Each bracket bolts onto a boss on the
    lower part just below its seam (screw along the seam normal, driven from
    above while the upper part is off) and reaches up into the upper part,
    where a radial M3 from outside goes through a counterbored pad into an
    insert in the bracket."""
    res = dict(add=dict(face=[], back=[], cap=[]), cut=dict(face=[], back=[], cap=[]), brackets=[], info=[], fasteners=[])
    PAD_IN = 3.0

    def attempt(seam_name, yc, d, jh, sg):
        n, p0 = plane(seam_name)
        below = halfspace(False, 0.3, (n, p0))
        zs = seam_z(yc) if seam_name == 'cap' else Z_FLOOR
        qs = np.array([0.0, yc, zs])
        qj = qs + n * jh
        p_in = inner_point(G, sd, qj, d, SHELL_T)
        p_out = inner_point(G, sd, p_in, d, 0.0)
        er = d; en = n; et = np.cross(er, en)
        rr = []
        for hh in np.arange(0.5, jh + 7.01, 1.0):
            rr.append(float(np.dot(inner_point(G, sd, qs + n * hh, d, SHELL_T), er)))
        r_face = min(min(rr), float(np.dot(p_in, er)) - PAD_IN) - 0.4
        q0 = p_in + er * (r_face - float(np.dot(p_in, er)))
        o = q0 - n * float(np.dot(q0 - p0, n))
        qi = o + n * jh
        arm = obox_n(o, er, en, et, (-8.0, 0.0), (0.3, jh + 7.0), (-6.0, 6.0))
        fl = obox_n(o, er, en, et, (-8.0, 0.0), (0.3, 6.3), tuple(sorted((-6.0 * sg, 18.0 * sg))))
        ns = o - er * 4.0 + et * 12.0 * sg
        br = (arm + fl) ^ (cavity + below)
        bb = np.array(br.bounding_box())
        local = (cavity ^ m_box(bb[:3] - 40, bb[3:] + 40)) + below
        for dd in np.arange(0.5, jh + 10.01, 0.5):      # the upper part comes down along -n onto it
            br = br ^ local.translate(list(n * dd))
        need = [m_cyl(qi, qi - er * (INSERT_L + 1.0), 3.9), m_cyl(ns + n * 0.3, ns + n * 6.3, 3.4)]
        ok = min(vol(br ^ q) / vol(q) for q in need)
        boss = (m_cyl(ns - n * 10.0, ns, 5.5) +
                obox_n(o, er, en, et, (-4.0, 12.0), (-10.0, 0.0), (12.0 * sg - 5.5, 12.0 * sg + 5.5))) ^ inside
        if vol(boss ^ corridor) > 0.005:
            ok = 0.0
        return ok, dict(boss=boss, br=br, er=er, n=n, o=o, qi=qi, ns=ns, p_in=p_in, p_out=p_out)

    for name, seam_name, lower, upper, hints, d in JOINTS:
        d = np.asarray(d, float)
        best = None
        for yc in hints:
            for sg in (1, -1):
                try:
                    ok, J = attempt(seam_name, yc, d, JOINT_H, sg)
                except RuntimeError:
                    continue
                if best is None or ok > best[0]:
                    best = (ok, J, yc)
                if ok > 0.97:
                    break
            if best and best[0] > 0.97:
                break
        ok, J, yc = best
        log('joint %s (%s seam, %s -> %s): y=%.0f, material round insert/screw %.0f %%' % (name, seam_name, lower, upper, yc, 100 * ok))
        assert ok > 0.95, 'no room for joint ' + name
        er, n, qi, ns, p_in, p_out = J['er'], J['n'], J['qi'], J['ns'], J['p_in'], J['p_out']
        pad_face = qi + er * 0.4
        D = float(np.dot(p_out - pad_face, er))
        cb = max(3.0, D - 3.0)
        res['add'][upper].append(m_cyl(p_out + er * 1.0, pad_face, 6.5) ^ inside)
        res['cut'][upper] += [m_cyl(p_out + er * 12, p_out - er * cb, 3.25), m_cyl(p_out + er * 2, pad_face - er * 1.0, 1.7)]
        hole_r = [insert_bore(qi, -er)]
        hole_n = m_cyl(ns - n * 1.0, ns + n * 8.0, 1.75)
        res['brackets'].append((name, J['br'] - union(hole_r + [hole_n])))
        res['add'][lower].append(J['boss'])
        res['cut'][lower] += [insert_bore(ns, -n)]
        st_b = 'brackets_floor' if seam_name == 'floor' else 'brackets_cap'
        st_c = 'back' if upper == 'back' else 'cap'
        res['fasteners'] += [dict(name='bracket %s to %s (M3x12)' % (name, lower), head=ns + n * 6.3, axis=n, stage=st_b, cb=0.0, opening='top'),
                             dict(name='%s to bracket %s (M3x12)' % (upper, name), head=p_out - er * cb, axis=er, stage=st_c, cb=cb,
                                  opening='outside')]
        res['info'].append(dict(name=name, seam=seam_name, y=yc, screw_point=np.round(p_out, 1).tolist(), dir=d.tolist()))
    # dowels along the cap seam normal, front (chassis) and back (back cover)
    n, p0 = seam()
    for x, side in DOWELS:
        yc = 50.0
        qs = np.array([x, yc, seam_z(yc)]) - n * 3.0
        dirv = np.array([0.0, float(side), -SEAM['slope'] * side]); dirv /= np.linalg.norm(dirv)
        q = inner_point(G, sd, qs, dirv, SHELL_T)
        c0 = q - dirv * 5.0
        c0 = c0 - n * float(np.dot(c0 - p0, n))
        lower = 'back' if (c0[1] > Y_BACK and c0[2] > Z_FLOOR) else 'face'
        fb = m_cyl(c0 - n * 10, c0, 5.5) ^ inside
        if vol(fb ^ corridor) > 0.005:
            log('dowel %s skipped (in an insertion path)' % ('front' if side < 0 else 'back'))
            continue
        res['add'][lower].append(fb)
        res['add']['cap'].append(m_cyl(c0, c0 + n * 10, 5.5) ^ inside)
        hcut = m_cyl(c0 - n * 7, c0 + n * 7, DOWEL_HOLE_D / 2)
        res['cut'][lower].append(hcut); res['cut']['cap'].append(hcut)
        log('dowel (%s / cap) at %s' % (lower, np.round(c0, 1)))
    return res


def head_seat(G, sd, c, ax, r, n=24):
    """Outer skull surface along unit ax round a ring of radius r about the axis
    through c (c inside the skull): (nearest, farthest) distance from c."""
    c = np.asarray(c, float); ax = np.asarray(ax, float); ax = ax / np.linalg.norm(ax)
    e1 = np.cross(ax, [1.0, 0, 0] if abs(ax[0]) < 0.9 else [0, 1.0, 0]); e1 /= np.linalg.norm(e1)
    e2 = np.cross(ax, e1)
    ds = []
    for a in np.linspace(0, 2 * np.pi, n, endpoint=False):
        q = c + r * (np.cos(a) * e1 + np.sin(a) * e2)
        ds.append(float(np.dot(inner_point(G, sd, q, ax, 0.0) - c, ax)))
    return min(ds), max(ds)


def cover_joints(G, sd, inside, cavity):
    """Cover joints without brackets.
    Back cover: its lower edge drops over a lip on the chassis floor; one M3 from
    behind, low at the back, into an insert post on the chassis.
    Cap: a hook on its front edge slides forward under a ledge on the chassis
    forehead (lower the cap 6 mm back, slide forward); one M3 from behind
    through the cap into an insert boss on the back cover."""
    t = SHELL_T; L = LIP
    out = dict(face=[], back=[], cap=[], cut_face=[], cut_back=[], cut_cap=[], fasteners=[])

    def band(lo, hi):
        return mc_mesh(np.minimum(sd - lo, hi - sd), G, 0.0, step=1, sigma=0.8)
    perim = m_box([-200, Y_BACK + 1.0, -200], [200, 400, 200]) - m_box([-40, Y_BACK, -200], [40, 120, 200])
    lip = (band(t - 0.5, t + L['gap'] + L['t']) ^ m_box([-200, -200, Z_FLOOR - 4], [200, 400, Z_FLOOR]) +
           band(t + L['gap'], t + L['gap'] + L['t']) ^ m_box([-200, -200, Z_FLOOR], [200, 400, Z_FLOOR + L['h'] - L['chamfer']]) +
           band(t + L['gap'] + 1.0, t + L['gap'] + L['t']) ^ m_box([-200, -200, Z_FLOOR + L['h'] - L['chamfer']], [200, 400, Z_FLOOR + L['h']]))
    out['lip'] = lip ^ perim
    # back cover screw: low at the back, along +Y into an insert post on the chassis.
    # The back of the head overhangs here (the wall faces down and back), and the
    # cover drops straight down, so the post face has to stay in front of every
    # bit of cover wall below it. The cover gets a pad out to the post face, and
    # a flat spot face for the screw head on the slanted outside.
    zb = Z_FLOOR + 5.0
    ys = [inner_point(G, sd, [x_, 100.0, z_], [0, 1.0, 0], t)[1]
          for x_ in (-6.0, 0.0, 6.0) for z_ in np.arange(Z_FLOOR + 0.5, zb + 6.01, 0.5)]
    yb = min(ys) - L['gap']                                    # post (joint) face
    ax_b = np.array([0, 1.0, 0])
    s0, s1 = head_seat(G, sd, [0.0, yb, zb], ax_b, M3_HEAD['d'] / 2 + 0.5)
    y_seat = yb + s0 - 0.5                                     # spot face: the head bears on a flat ring
    out['face_post'] = m_box([-6.0, yb - 13.0, Z_FLOOR - 30.0], [6.0, yb, zb + 4.9]) ^ inside
    out['cut_face'].append(insert_bore([0, yb, zb], -ax_b))
    out['back'].append(m_cyl([0, yb + L['gap'], zb], [0, yb + s1 + 1.0, zb], 5.0) ^ inside ^
                       m_box([-20, 0, Z_FLOOR + 0.3], [20, 300, 50]))
    out['cut_back'] += [m_cyl([0, yb - 1.0, zb], [0, y_seat + 30.0, zb], M3_CLEAR_D / 2),
                        m_cyl([0, y_seat, zb], [0, y_seat + 30.0, zb], M3_HEAD['d'] / 2 + 0.5)]
    out['fasteners'].append(dict(name='back cover screw (M3x12)', head=np.array([0, y_seat, zb]), axis=ax_b, stage='back',
                                 cb=yb + s1 - y_seat, opening='outside',
                                 spec=dict(kind='insert', L=12.0, d=3.0, clamped=['back'], receiver='face',
                                           head=M3_HEAD, clear_d=M3_CLEAR_D)))
    # cap: forehead ledge (chassis) + hook (cap)
    n, p0 = seam()
    tb = np.array([0.0, 1.0, -SEAM['slope']]); tb /= np.linalg.norm(tb)          # along the seam, backward
    xh = np.array([1.0, 0, 0])
    q = np.array([0.0, 40.0, seam_z(40.0)]) - n * 2.0
    pp = q.copy()
    for _ in range(1000):                       # walk forward to the forehead's inner surface
        if sd[G.idx(pp)] <= t:
            break
        pp = pp - tb * 0.2
    o_f = pp - n * float(np.dot(pp - p0, n))
    hw = CAP_HOOK['w'] / 2; g = CAP_HOOK['gap']
    ledge = obox_n(o_f, tb, n, xh, (-1.5, 4.0), (-3.0, 0.0), (-hw - 2, hw + 2))
    out['face'].append(ledge)
    hook = union([obox_n(o_f, tb, n, xh, (-1.5, 7.0), (g, 4.0), (-hw, hw)),                  # bridge over the ledge
                  obox_n(o_f, tb, n, xh, (4.0 + g, 7.0), (-6.0, 4.0), (-hw, hw)),             # stem behind it
                  obox_n(o_f, tb, n, xh, (g, 7.0), (-6.0, -3.0 - g), (-hw, hw))])             # foot under it
    out['cap'].append(hook)
    # cap screw: through the cap at the back, into a boss on the back cover
    yq = 120.0
    qb = np.array([0.0, yq, seam_z(yq)]) + n * 6.0
    pc = inner_point(G, sd, qb, tb, t)
    pco = inner_point(G, sd, pc, tb, 0.0)
    o_b = pc - n * float(np.dot(pc - p0, n))
    # the boss reaches up across the seam to the screw axis (6 mm above it); the
    # part above the seam keeps 0.6 mm off the cap wall. The two blocks overlap
    # so they fuse (face-to-face blocks came out as two bodies, and the clean-up
    # dropped the upper one).
    c6 = o_b + n * 6.0
    p_cav = inner_point(G, sd, c6 - tb * 6.0, tb, t + 0.6)
    r_f = float(np.dot(p_cav - o_b, tb)) - 0.5             # flat boss face, square to the screw
    boss_up = obox_n(o_b, tb, n, xh, (-14.0, r_f), (-1.0, 10.0), (-6.0, 6.0)) ^ cavity
    boss_lo = obox_n(o_b, tb, n, xh, (-14.0, 1.5), (-8.0, 0.0), (-6.0, 6.0)) ^ inside
    out['back'].append(boss_up + boss_lo)
    p_face = o_b + n * 6.0 + tb * r_f
    out['cut_back'].append(insert_bore(p_face, -tb))
    s0, s1 = head_seat(G, sd, c6 - tb * 3.0, tb, M3_HEAD['d'] / 2 + 0.5)
    c_seat = c6 - tb * 3.0 + tb * (s0 - 0.3)
    out['cut_cap'] += [m_cyl(c6 - tb * 1.0, c6 + tb * 30.0, M3_CLEAR_D / 2),
                       m_cyl(c_seat, c_seat + tb * 30.0, M3_HEAD['d'] / 2 + 0.5)]
    out['fasteners'].append(dict(name='cap screw (M3x12)', head=c_seat, axis=tb, stage='cap', cb=s1 - s0 + 0.3, opening='outside',
                                 spec=dict(kind='insert', L=12.0, d=3.0, clamped=['cap'], receiver='back',
                                           head=M3_HEAD, clear_d=M3_CLEAR_D)))
    out['slide_dir'] = tb
    log('cap hook at %s, cap screw at %s, back screw at %s' % (np.round(o_f, 1), np.round(pco, 1), np.round([0, y_seat, zb], 1)))
    return out


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


def esp32_frame():
    """Board placement: x ends, centre y, PCB bottom/top z, USB plug axis (x, y, z)."""
    E = ESP32
    xb1 = E['x_usb']; xb0 = xb1 - E['L']; zb = E['z']; zt = zb + E['T']
    return dict(xb0=xb0, xb1=xb1, yc=E['y'], zb=zb, zt=zt, zp=zt + USB['z_up'])


def servo_tray_parts(mech):
    """The servo bracket and the ESP32 cradle as ONE part (skull coordinates).

    mech['bracket'] (servo plate under the tabs + flange onto the two insert
    bosses) is unchanged, so the shaft stays on the hinge axis. Added to it:
    two gussets in the flange/plate corner (beside the servo case), a bridge
    slab continuing the flange toward +Y (with an open notch for the USB cable),
    two deep ribs (y = yc +- rib_y) carrying a narrow cradle plate that sits
    between the DuPont rows, end ledges, end walls (USB cut at +X) and a zip-tie
    pair at the far end. Returns (part, board) where board is the ESP32 with
    its header rows + DuPont housings (hardware, for the collision checks)."""
    T = TRAY; E = ESP32; F = esp32_frame(); c = T['fit']; D = DUPONT
    xb0, xb1, yc, zb, zt = F['xb0'], F['xb1'], F['yc'], F['zb'], F['zt']
    br = mech['bracket']
    bb = np.array(br.bounding_box())
    zf0 = float(mech['bracket_bolts'][0][2]); zf1 = zf0 + BRACKET_T      # flange bottom / top
    assert SERVO_SIDE == 1, 'servo_tray_parts assumes the servo on +X'
    xp_in = bb[3] - BRACKET_T                                             # inner face of the servo plate (x)
    sv = np.array(mech['servo'].bounding_box())                          # servo case y range: sv[1] .. sv[4]
    z1 = zb - T['standoff']; z0 = z1 - T['t']                             # cradle plate top / bottom
    xw0 = xb0 - c - T['wall']; xw1 = xb1 + c + T['wall']                  # outer faces of the end walls
    hw = E['W'] / 2 + c + T['wall']
    parts = [br]
    # gussets in the flange / servo-plate corner, outside the servo case (w = +-W/2 + 0.6)
    for y_a, y_b in ((bb[1], sv[1] - 0.6), (sv[4] + 0.6, bb[4])):
        parts.append(mf.Manifold.batch_hull([m_box([xp_in - 12.0, y_a, zf0 - 0.5], [xp_in + 0.01, y_b, zf0 + 0.01]),
                                             m_box([xp_in - 0.5, y_a, zf0 - 24.0], [xp_in + 0.01, y_b, zf0 + 0.01])]))
    # bridge slab: the flange continued toward +Y, from the flange's -X edge to the USB end wall
    parts.append(m_box([bb[0], T['bridge_y0'], zf0], [xw1, yc + T['rib_y'] + T['rib_t'] / 2, zf1]))
    # two ribs: full depth (slab to cradle plate) over the bridge, tapering toward the far end
    for sy in (-1, 1):
        y_a = yc + sy * T['rib_y'] - T['rib_t'] / 2; y_b = y_a + T['rib_t']
        parts.append(mf.Manifold.batch_hull([m_box([bb[0], y_a, zf0], [xw1, y_b, z1]),
                                             m_box([xw0, y_a, z0 - 3.0], [xw0 + 3.0, y_b, z1])]))
    parts.append(m_box([xw0, yc - T['half_w'], z0], [xw1, yc + T['half_w'], z1]))        # cradle plate
    # far end: zip-tie tab under the board end (between the board edge and the first header pin)
    # and a short end wall; both kept inside the back cover's drop footprint, which narrows there
    parts.append(m_box([xb0, yc - T['tie_w'], z0], [xb0 + D['inset'] - 0.5, yc + T['tie_w'], z1]))
    for sg, xend in ((-1, xb0), (1, xb1)):
        hw_ = T['far_wall_w'] if sg < 0 else hw
        parts.append(m_box([min(xend + sg * c, xend + sg * (c + T['wall'])), yc - hw_, z0],
                           [max(xend + sg * c, xend + sg * (c + T['wall'])), yc + hw_, zt + 3.0]))     # end wall
        parts.append(m_box([min(xend, xend - sg * T['ledge']), yc - 9.0, z1 - 0.01],
                           [max(xend, xend - sg * T['ledge']), yc + 9.0, zb]))                       # ledge
    part = union(parts)
    cuts = [m_box([xb1 - 0.1, yc - 6.5, zb - 2.0], [xw1 + 1, yc + 6.5, zt + 10]),                   # USB plug
            m_box([-2.0, yc - T['notch'], zf0 - 1], [xw1 + 1, yc + T['notch'], zf1 + 1])] + \
        [m_cyl(p - [0, 0, 1.0], p + [0, 0, BRACKET_T + 1.0], 1.9) for p in mech['bracket_bolts']]   # bracket bolt holes (re-cut through the slab)
    for sy in (-1, 1):
        cuts.append(m_box([xb0 + 0.2, min(yc + sy * (E['W'] / 2 + 0.2), yc + sy * (E['W'] / 2 + 1.4)), z0 - 1], [xb0 + D['inset'] - 0.7, max(yc + sy * (E['W'] / 2 + 0.2), yc + sy * (E['W'] / 2 + 1.4)), z1 + 1]))  # zip tie
    part = part - union(cuts)
    D = DUPONT
    board = union([m_box([xb0, yc - E['W'] / 2, zb], [xb1, yc + E['W'] / 2, zt])] +
                  [m_box([xb0 + D['inset'], yc + sy * D['row_y'] - D['w'] / 2, zb - D['h']],
                         [xb1 - D['inset'], yc + sy * D['row_y'] + D['w'] / 2, zb]) for sy in (-1, 1)])   # header rows + DuPont housings
    return part, board


def usb_keepouts():
    """Keep-out volumes round the ESP32 (skull coordinates), see USB / DUPONT / BUTTONS.

    plug:   micro-USB overmold + strain-relief boot, plugged in;
    path:   straight insertion path along the connector axis (overmold section + clearance);
    grip:   finger room either side of the plug and up to the open top (cap off);
    cable:  Ø cable_d (+ clearance) from the boot: a 180° loop down (bend_r) in the plane
            y = yc, back toward the neck, a 90° bend down onto the bore axis, then down the bore;
    dupont: per row, the housings (w x h) and their wires (out of the bottom, then sideways);
    buttons: a fingertip column from above onto EN and BOOT."""
    U = USB; F = esp32_frame(); D = DUPONT; Bt = BUTTONS; N = NECK
    xr, yc, zp = F['xb1'], F['yc'], F['zp']
    cl = U['clear']; R = U['bend_r']; rc = U['cable_d'] / 2 + cl
    x_om = xr + 0.5 + U['plug_l']; x_bt = x_om + U['boot_l']
    out = {}
    out['plug'] = m_box([xr + 0.5, yc - U['plug_w'] / 2, zp - U['plug_h'] / 2], [x_om, yc + U['plug_w'] / 2, zp + U['plug_h'] / 2]) + \
        m_cyl([x_om - 0.01, yc, zp], [x_bt, yc, zp], U['boot_d'] / 2)
    out['path'] = m_box([xr + 0.2, yc - U['plug_w'] / 2 - cl, zp - U['plug_h'] / 2 - cl],
                        [xr + U['path_l'], yc + U['plug_w'] / 2 + cl, zp + U['plug_h'] / 2 + cl])
    out['grip'] = m_box([xr + 3.5, yc - U['plug_w'] / 2 - U['grip'], zp - U['plug_h'] / 2 - 2.0],
                        [x_bt, yc + U['plug_w'] / 2 + U['grip'], zp + U['grip_up']])
    # cable centre line in the plane y = yc: (x, z) points
    pts = [(xr + U['plug_l'], zp), (x_bt, zp)]
    for a in np.radians(np.arange(90, -90.1, -10)):                       # loop down, away from the board
        pts.append((x_bt + R * np.cos(a), zp - R + R * np.sin(a)))
    zl = zp - 2 * R                                                       # leg back toward the bore
    for a in np.radians(np.arange(90, 180.1, 10)):                        # bend down onto the bore axis
        pts.append((N.get('x', 0.0) + R + R * np.cos(a), zl - R + R * np.sin(a)))
    z_mouth = zl - R
    pts.append((0.0, N['z_bottom'] - 5.0))
    P3 = [np.array([x, yc, z]) for x, z in pts]
    out['cable_line'] = P3
    out['cable_bare'] = union([m_cyl(a, b, U['cable_d'] / 2, seg=24) for a, b in zip(P3[:-1], P3[1:]) if np.linalg.norm(b - a) > 1e-6] +
                              [mf.Manifold.sphere(U['cable_d'] / 2, 24).translate(list(p)) for p in P3[1:-1]])
    out['cable_mouth_z'] = z_mouth
    out['cable'] = union([m_cyl(a, b, rc, seg=24) for a, b in zip(P3[:-1], P3[1:]) if np.linalg.norm(b - a) > 1e-6] +
                         [mf.Manifold.sphere(rc, 24).translate(list(p)) for p in P3[1:-1]])
    # DuPont rows: housings + wires (down out of the housing, then sideways outward)
    hb = F['zb'] - D['h']
    xs = (F['xb0'] + D['inset'], F['xb1'] - D['inset'])
    rows = []
    for sy in (-1, 1):
        yi = yc + sy * (D['row_y'] - D['w'] / 2); yo = yc + sy * (D['row_y'] + D['w'] / 2)
        house = m_box([xs[0], min(yi, yo), hb], [xs[1], max(yi, yo), F['zb']])
        wire = m_box([xs[0], min(yi, yo + sy * D['wire']), hb - D['wire']], [xs[1], max(yi, yo + sy * D['wire']), hb + 0.01])
        rows.append(house + wire)
    out['dupont'] = rows
    out['buttons'] = union([m_cyl([xr - Bt['dx'], yc + sy * Bt['dy'], F['zt'] + 1.0],
                                  [xr - Bt['dx'], yc + sy * Bt['dy'], F['zt'] + 1.0 + Bt['reach']], Bt['finger_d'] / 2)
                            for sy in (-1, 1)])
    return out


def usb_checks(R):
    """ESP32 / USB / DuPont / button / servo-tray checks. Volumes in cm3 (> 0.005 fails)."""
    P, H, hinge = R['parts'], R['hardware'], R['hinge']
    K = usb_keepouts()
    jm = P['jaw']
    jaw_sw = union([jm.transform(rot_x_about(*hinge, a))
                    for a in np.arange(JAW_CLOSE_STOP, JAW_OPEN_DEG + JAW_STOP_MARGIN + 0.01, 1.0)])
    horn = R['mech']['horn']                                  # swept horn disc
    fixed = dict(face=P['face'], back=P['back'], servo_tray=P['servo_tray'], servo=H['servo'], horn_sweep=horn,
                 jaw_sweep=jaw_sw, bar=H['bar'], modules=H['modules'], radar=H['radar'])
    cap_on = dict(fixed, cap=P['cap'], stand=P['stand'])
    res = {}

    def hits(M, obst):
        d = {}
        for k, o in obst.items():
            v = vol(M ^ o)
            if v > 0.005:
                d[k] = round(v, 3)
        return d
    res['plug_plugged'] = hits(K['plug'], dict(cap_on, esp32=H['esp32']))
    res['insertion_path'] = hits(K['path'], dict(fixed, esp32=H['esp32']))
    res['grip'] = hits(K['grip'], dict(fixed, esp32=H['esp32']))
    res['cable'] = hits(K['cable'], dict(cap_on, esp32=H['esp32']))
    # covers on/off with the cable plugged in: the back cover lifts straight up, the cap along its path
    n_s, _ = seam()
    back_sw = union([P['back'].translate([0, 0, d]) for d in np.arange(0.0, 60.01, 2.0)])
    sl = CAP_HOOK['slide'] + 0.5
    cap_sw = union([P['cap'].translate(list(R['cap_slide'] * d)) for d in np.arange(0.0, sl + 0.01, 1.0)] +
                   [P['cap'].translate(list(R['cap_slide'] * sl + n_s * d)) for d in np.arange(1.0, 40.01, 3.0)])
    res['cable_cover_seams'] = hits(K['cable_bare'] + K['plug'], dict(back_on_off=back_sw, cap_on_off=cap_sw))
    for i, sy in enumerate(('front', 'back')):
        res['dupont_' + sy] = hits(K['dupont'][i], cap_on)
    res['buttons'] = hits(K['buttons'], dict(fixed, plug=K['plug']))
    # servo tray drops in from above (cap off, back cover off) with the servo and horn on it
    grp = union([P['servo_tray'], H['servo'], H['horn']])
    early = union([P['face'], H['bar'], H['modules'], H['radar']])
    res['servo_tray_drop'] = round(max(vol(grp.translate([0, 0, d]) ^ early) for d in np.arange(0.5, 100.01, 1.5)), 3)
    # the ESP32 lifts out of the cradle with the servo tray in place (cap off)
    rest = union([P['face'], P['back'], P['servo_tray'], H['servo'], H['horn'], H['bar'], H['modules'], H['radar']])
    res['esp32_lift_out'] = round(max(vol(H['esp32'].translate([0, 0, d]) ^ rest) for d in np.arange(0.5, 60.01, 1.5)), 3)
    F = esp32_frame()
    res['layout'] = dict(board_x=(F['xb0'], F['xb1']), board_y=F['yc'], pcb_bottom_z=F['zb'], usb_axis_z=round(F['zp'], 2),
                         usb_faces='+X', cable_mouth_z=round(K['cable_mouth_z'], 2), neck_top_z=-12.0)
    res['failures'] = ['usb/' + k for k, v in res.items() if (isinstance(v, dict) and v and k != 'layout') or
                       (isinstance(v, float) and v > 0.005)]
    if K['cable_mouth_z'] < -12.0 - 0.01:
        res['failures'].append('usb/cable bend below the neck bore mouth')
    return res, K


def stand():
    """Base + column. The neck boss drops into a socket at the top and is held by one
    radial M3. An open slot runs down the column and across the base for the USB cable."""
    S = STAND; N = NECK
    zt = N['z_bottom']; zb = zt - S['h']; y = N['y']
    col = m_cyl([0, y, zb], [0, y, zt + S['socket']], S['col_d'] / 2, seg=72)
    base = m_cyl([0, y, zb], [0, y, zb + S['base_t']], S['base_d'] / 2, seg=96)
    socket = m_cyl([0, y, zt], [0, y, zt + S['socket'] + 1], N['r'] + S['fit'], seg=72)
    bore = m_cyl([0, y, zb - 1], [0, y, zt + 1], S['bore'] / 2)
    slot = m_box([-S['col_d'], y - S['slot'] / 2, zb - 1], [0.0, y + S['slot'] / 2, zt + S['socket'] + 1])     # open toward -X
    slot_b = m_box([-S['base_d'], y - S['slot'] / 2, zb - 1], [0.0, y + S['slot'] / 2, zb + S['base_t'] + 1])
    screw = m_cyl([0, y, zt + N['screw_z']], [0, y + S['col_d'], zt + N['screw_z']], 1.7) + \
        m_cyl([0, y + S['col_d'] / 2 - 1.5, zt + N['screw_z']], [0, y + S['col_d'], zt + N['screw_z']], 3.0)     # M3 + head seat
    return (col + base) - union([socket, bore, slot, slot_b, screw])


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
    return max(M.decompose(), key=lambda m: m.volume())


def build():
    cr, jaw = load_sources()
    cr, jaw, info = frame(cr, jaw)
    hinge = jaw_hinge(jaw)
    a0 = jaw_closed_angle(jaw, cr, hinge)
    log('hinge y=%.2f z=%.2f; source jaw pose closes at %.2f deg' % (hinge[0], hinge[1], a0))
    jaw = jaw.transform(rot_x_about(*hinge, a0))
    info.update(hinge=list(hinge), jaw_closed_from_source_deg=a0)
    mech = mechanism(hinge)
    pads = jaw_pads(jaw, hinge)
    o_ = -SERVO_SIDE
    # nothing of the condyles inboard of the pad faces (the medial poles would rub
    # on the skull boss and the horn)
    inboard = union([m_box([min(sg * x0, sg * 20.0), hinge[0] - 22, hinge[1] - 26], [max(sg * x0, sg * 20.0), hinge[0] + 16, hinge[1] + 30])
                     for sg, x0 in ((SERVO_SIDE, HORN_FACE_X), (o_, PIVOT_FACE_X))])
    jaw_moving = union([jaw - inboard, pads['servo'], pads['pivot'], mech['finger']])
    # trim the condyle heads just above the axis (outside the knuckle discs they
    # would sweep into the skull); the knuckle discs round the axis are kept
    keep = union([knuckle_keep(hinge, SERVO_SIDE, JAW_PAD, HORN_FACE_X), knuckle_keep(hinge, o_, PIVOT_PAD, PIVOT_FACE_X)])
    jaw_moving = jaw_moving - (m_box([-80, hinge[0] - 16, hinge[1] + CONDYLE_TRIM], [80, hinge[0] + 16, hinge[1] + 30]) - keep)
    log('jaw knuckles: servo side %.1f cm3, pivot side %.1f cm3' % (vol(pads['servo']), vol(pads['pivot'])))
    angles = np.arange(JAW_CLOSE_STOP - 1.0, JAW_OPEN_DEG + JAW_STOP_MARGIN + 1.01, 1.5)
    sweep = union([jaw_moving.transform(rot_x_about(*hinge, a)) for a in angles] + [mech['horn']])
    b = np.array(cr.bounding_box())
    G = Grid(b[:3] - [0, 0, 20], b[3:], VOX)
    log('grid', G.shape)
    Bv = G.vox(cr)
    plugs, einfo, Df, sockets = make_plugs(G, Bv, info['scale'])
    info['eyes'] = einfo
    sv = G.vox(sweep)
    sweep_v = ndimage.binary_dilation(sv, iterations=int(round(JAW_SWEEP_CLEAR / G.h)))
    # round the condyles the voxel dilation above is short of JAW_SWEEP_CLEAR on the
    # diagonals and the shell mesh is smoothed: there the carve is a true distance
    # (+ HINGE_CLEAR_EXTRA for the smoothing), so the knuckles keep their clearance
    i0 = G.idx([-70.0, hinge[0] - 30, hinge[1] - 34]); i1 = G.idx([70.0, hinge[0] + 30, hinge[1] + 24])
    sl_ = tuple(slice(max(a, 0), min(b, n)) for a, b, n in zip(i0, i1, G.shape))
    sub = edt(sv[sl_], G.h) <= JAW_SWEEP_CLEAR + HINGE_CLEAR_EXTRA
    xs_ = np.abs(G.x[sl_[0]])[:, None, None]
    sweep_v[sl_] |= sub & (xs_ >= 24.0)
    for sk in sockets.values():                    # the bowls' air is outside by definition
        sweep_v |= G.vox(sk['air'])
    # the shell is taken from the outside of the marked volume, so grow the cup by the wall
    cup_v = ndimage.binary_dilation(G.vox(mech['cup_env']), iterations=int(np.ceil((SHELL_T + 0.4) / G.h)))
    sh = shell(G, Bv, plugs, extra_in=cup_v, extra_out=sweep_v)
    assert not sh['leak'], 'the cavity is visible from outside'
    if sh['A'][G.idx(NOSE_PROBE)] and os.environ.get('SKULL_DEBUG'):
        np.savez_compressed(os.path.join(CACHE, 'debug_A.npz'), A=sh['A'], o=G.o)
    assert not sh['A'][G.idx(NOSE_PROBE)], 'the nasal cavity is still open to the throat'
    assert not sh['A'][G.idx(BEHIND_PROBE)], 'the space behind the eyes is open to the outside'
    crm = shell_mesh(G, cr, sh)
    sd = sh['sd']
    inside = mc_mesh(sd - 0.4, G, 0.0, step=2)
    cavity = mc_mesh(sd - (SHELL_T + 0.6), G, 0.0, step=2)      # free space inside the shell

    # ---- eyes
    y_glass = EYE_DEPTH
    y_back = y_glass + MODULE_T + STANDOFF_H + BAR_T
    y_front = y_back - BAR_T
    T = scad_to_skull(y_back)
    bar = to_man(trimesh.load(EYE_BAR_STL)).transform(T)
    modules = place_modules(module_local()).transform(T)
    eye_clear = (place_modules(module_local(FIT, True)) + bar_clearance_local()).transform(T)
    posts = union([m_cyl([hx, y_front, hz], [hx, y_front - 45, hz], 4.5) for hx, hz in BAR_HOLES]) ^ inside
    bolts_ = [BAR_HOLES[i] for i in BAR_BOLTS]
    post_holes = union([insert_bore([hx, y_front, hz], [0, -1.0, 0]) for hx, hz in bolts_])
    pegs = [BAR_HOLES[i] for i in range(len(BAR_HOLES)) if i not in BAR_BOLTS]
    peg = union([m_cyl([hx, y_front - 0.5, hz], [hx, y_front + 4.0, hz], 1.5) for hx, hz in pegs]) if pegs else None
    socket_air = union([sk['air'] for sk in sockets.values()])
    socket_wall = union([sk['wall'] for sk in sockets.values()])
    apert = union([m_cyl([xe, y_glass - SCREEN_GAP - SOCKET_WALL - 1, 0], [xe, y_glass - 0.05, 0], APERTURE_D / 2)
                   for xe in (-EYE_SPACING / 2, EYE_SPACING / 2)])
    info.update(y_glass=y_glass, y_bar_back=y_back)
    log('eyes: glass %.2f mm behind the rim plane, bar back face at y=%.2f' % (y_glass, y_back))

    # ---- radar
    y_wall_back = NASAL_RIM_Y + NASAL_RECESS + NASAL_T
    radar, radar_clear, radar_frame = radar_parts(y_wall_back)
    n_seam, p_seam = seam()
    info['seam'] = dict(SEAM, normal=np.round(n_seam, 4).tolist(), y_back=Y_BACK, z_floor=Z_FLOOR)
    # insertion paths. Fixed chassis features must stay out of them.
    # Eye bar with both modules and their cables: straight back out of the back
    # opening (60 mm). Radar: out of its frame, then on edge up the slot between
    # the bowls and out of the top.
    corridor = union([eye_clear.translate([0, dy, 0]) for dy in np.arange(0, EYE_BAR_BACKOFF + 0.01, 1.5)] +
                     [eye_clear.translate([0, EYE_BAR_BACKOFF, dz]) for dz in np.arange(0, 70.01, 2.0)])
    corridor_back = corridor ^ m_box([-300, -300, -300], [300, Y_BACK + 2.0, 300])
    R_ = RADAR
    radar_path = m_box([-R_['L'] / 2 - 0.6, y_wall_back + 0.2, R_['z'] - R_['W'] / 2 - 0.6],
                       [R_['L'] / 2 + 0.6, 14.0, R_['z'] + R_['W'] / 2 + 0.6])
    radar_lift = m_box([-R_['W'] / 2 - 0.7, 9.0, R_['z'] - R_['W'] / 2 - 0.6], [R_['W'] / 2 + 0.7, 9.0 + 4.8, seam_z(11.0) + 30.0])
    # clearance cuts must stay inside the skull, or they would open holes in the surface
    skin = mc_mesh(np.where(sh['env'] | (sd > 0), 1.0, -1.0).astype(np.float32), G, 0.0, step=2) + socket_air
    inner_reg = region('face')
    pierce = dict(eyes=vol(eye_clear - skin), radar=vol(radar_clear - skin),
                  eye_bar_path=vol((corridor ^ inner_reg) - skin), radar_path=vol(((radar_path + radar_lift) ^ inner_reg) - skin))
    info['clearance_outside_skull_cm3'] = {k: round(v, 3) for k, v in pierce.items()}
    log('clearance volume outside the skull surface (cm3):', info['clearance_outside_skull_cm3'])
    radar_frame = (radar_frame ^ inside) - radar_clear

    # ---- joints (bosses must stay out of the insertion paths)
    J = joints(G, sd, inside, cavity, corridor + radar_path + radar_lift)
    info['joints'] = J['info']
    CJ = cover_joints(G, sd, inside, cavity)

    # ---- chassis features: servo cup bosses, jaw pivot, neck, tie bar (the servo tray needs no posts of its own)
    slot = union([mech['finger_clear'].transform(rot_x_about(*hinge, a))
                  for a in np.arange(JAW_CLOSE_STOP, JAW_OPEN_DEG + JAW_STOP_MARGIN + 0.01, 0.5)])
    # the pivot boss is rooted in the cranial floor: a gusset flaring from the
    # boss top out over the floor (kept inside the skin and below the chassis cut)
    xs_p = -SERVO_SIDE * (PIVOT_FACE_X - 0.5)
    root = mf.Manifold.batch_hull([m_box([min(xs_p, -SERVO_SIDE * 22.0), hinge[0] - 9, hinge[1] + 6],
                                         [max(xs_p, -SERVO_SIDE * 22.0), hinge[0] + 9, hinge[1] + 15]),
                                   m_box([min(xs_p, -SERVO_SIDE * 14.0), hinge[0] - 17, hinge[1] + 12],
                                         [max(xs_p, -SERVO_SIDE * 14.0), hinge[0] + 17, min(hinge[1] + 15, Z_FLOOR - 0.5)])])
    pivot = (mech['skull_pivot'] + (root ^ inside)) - slot - mech['skull_pivot_holes']
    sboss = union([m_cyl(p, p - np.array([0, 0, 40.0]), 4.5) for p in mech['bracket_bolts']]) ^ inside
    sboss_h = union([insert_bore(p, [0, 0, -1.0]) for p in mech['bracket_bolts']])
    N = NECK
    neck = m_cyl([0, N['y'], N['z_bottom']], [0, N['y'], -12.0], N['r'])
    zs_ = N['z_bottom'] + N['screw_z']
    neck_h = m_cyl([0, N['y'], N['z_bottom'] - 1], [0, N['y'], 5.0], N['bore'] / 2) + \
        insert_bore([0, N['y'] + N['r'], zs_], [0, -1.0, 0], relief=0.0)      # cable bore + stand-screw insert (no relief: the cable bore is behind it)
    U = dict(x=0.0); Tb = TIE_BAR; ty = Tb['y']
    zf2 = inner_point(G, sd, [U['x'], ty, 0.0], [0, 0, -1.0], SHELL_T)[2]
    tie = m_box([U['x'] - Tb['w'] / 2, ty - Tb['t'] / 2, zf2 - 3], [U['x'] + Tb['w'] / 2, ty + Tb['t'] / 2, zf2 + Tb['h']]) - \
        m_box([U['x'] - Tb['tunnel_w'] / 2, ty - Tb['t'], zf2 + 1.0], [U['x'] + Tb['tunnel_w'] / 2, ty + Tb['t'], zf2 + 1.0 + Tb['tunnel_h']])
    # ---- split: chassis / back cover / cap
    face = crm ^ region('face')
    backc = crm ^ region('back')
    cap = crm ^ region('cap')

    # chassis
    face = face - socket_air - eye_clear - radar_clear
    face = union([face, socket_wall, posts, radar_frame, pivot, sboss, neck, tie ^ inside] + J['add']['face'] + CJ['face'])
    face = face - union([post_holes, apert, radar_clear, socket_air, mech['cup_env'], mech['cup_slot'],
                         mech['skull_pivot_holes'], slot, sboss_h, neck_h] + J['cut']['face'] + CJ['cut_face'])
    face = face - eye_clear - corridor_back
    if peg is not None:
        face = face + peg
    face = clean(face, 'face')
    # back cover
    backc = union([backc ^ region('back')] + J['add']['back'] + CJ['back']) - union(J['cut']['back'] + CJ['cut_back'])
    back = clean(backc, 'back')
    # floor lip: whatever of it the back cover would hit on its way down is trimmed off
    dropzone = union([back.translate([0, 0, h_]) for h_ in np.arange(0.0, 30.01, 0.5)])
    lip = CJ['lip'] - dropzone
    info['floor_lip_cm3'] = round(vol(lip), 2)
    log('floor lip after trimming to the drop path: %.2f cm3 (before %.2f)' % (vol(lip), vol(CJ['lip'])))
    # the back-cover post goes on after the lip trim, and its insert bore is cut
    # after it is added (it used to be cut before, so the post came out solid)
    face = clean(face + lip + CJ['face_post'] - union(CJ['cut_face']), 'face')
    # black socket/nose liners: the face is cut back to take them (liners.py)
    face, liner_parts = liners.make_liners(face, sockets, dict(
        eye_clear=eye_clear, corridor=corridor, radar_clear=radar_clear, radar=radar, bar=bar, modules=modules,
        skin=skin, radar_path=radar_path + radar_lift, y_eye_base=y_glass - FIT, y_nose_base=y_wall_back), log=log)
    face = clean(face, 'face')
    info['liners'] = liners.REPORT
    PRINT_ORIENT.update({k: liners.PRINT_ROT for k in liner_parts})
    COLORS.update({k: '#181818' for k in liner_parts})
    # cap
    cap = union([cap ^ region('cap')] + J['add']['cap'] + CJ['cap']) - union(J['cut']['cap'] + CJ['cut_cap'])
    cap = clean(cap, 'cap')

    # ---- fasteners (head point, outward tool axis, stage) for the tool-access check
    Tm = scad_to_skull(y_back)
    fast = []
    for xe in (-EYE_SPACING / 2, EYE_SPACING / 2):
        a_ = np.radians(eye_rot(xe))
        for sx in (-1, 1):
            lx, ly = sx * 7.875, -0.14
            px, py = xe + lx * np.cos(a_) - ly * np.sin(a_), lx * np.sin(a_) + ly * np.cos(a_)
            fast.append(dict(name='M2 module screw (x=%.0f)' % px, head=Tm[:, :3] @ [px, py, 0.0] + Tm[:, 3],
                             axis=np.array([0, 1.0, 0]), stage='eyebar', cb=0.0, opening='back',
                             spec=dict(kind='hw', L=8.0, d=2.0, clamped=['bar'], receiver='modules', head=M2_HEAD, clear_d=2.2,
                                       min_engage=2.0, note='into the module standoff (M2 thread, 3 mm)')))
    for hx, hz in bolts_:
        fast.append(dict(name='eye-bar bolt (M3x12, x=%.0f)' % hx, head=np.array([hx, y_back, hz]), axis=np.array([0, 1.0, 0]), stage='eyebar',
                         cb=0.0, opening='back', hand=True,
                         spec=dict(kind='insert', L=12.0, d=3.0, clamped=['bar'], receiver='face', head=M3_WASHER, clear_d=3.4,
                                   note='with a Ø9 M3 washer (DIN 9021): a head or a Ø7 washer only bears on the sides of the 3.7 x 6.7 slot')))
    Ps = servo_frame(hinge); S_ = SERVO; u_ax = np.array([float(SERVO_SIDE), 0, 0])
    vmid = (-S_['shaft_off'] + S_['L'] - S_['shaft_off']) / 2
    for v in (vmid - S_['hole_sp'] / 2, vmid + S_['hole_sp'] / 2):
        fast.append(dict(name='servo tab screw (v=%.0f)' % v, head=Ps(S_['tab_top'], v, 0), axis=u_ax, stage='bench_servo', cb=0.0,
                         spec=dict(kind='selftap', L=8.0, d=2.0, clamped=['servo'], receiver='servo_tray', head=M2_HEAD,
                                   clear_d=None, pilot_d=1.8, through=True, note='supplied servo screw, length assumed 8 mm')))
    fast.append(dict(name='horn screw', head=Ps(S_['spline_top'] + 1.0, 0, 0), axis=u_ax, stage='bench_horn', cb=0.0,
                     spec=dict(kind='hw', clamped=['horn'], receiver='servo', note='supplied; horn onto the spline, not modelled')))
    for p_ in mech['bracket_bolts']:
        fast.append(dict(name='servo tray bolt (M3x8, y=%.0f)' % p_[1], head=p_ + [0, 0, BRACKET_T], axis=np.array([0, 0, 1.0]), stage='servo_tray',
                         cb=0.0, opening='top',
                         spec=dict(kind='insert', L=8.0, d=3.0, clamped=['servo_tray'], receiver='face', head=M3_HEAD, clear_d=3.8)))
    # horn-to-jaw screws (M2x16 self-tapping) from outside the ramus: Ø2.2 pilot,
    # and a Ø4.8 counterbore only where the ramus is thicker than the screw allows
    hd = horn_dir(); sg_ = SERVO_SIDE; tj = to_tri(jaw_moving); horn_cut = []
    for r_ in HORN_JAW_HOLES:
        c_ = np.array([hinge[0] + r_ * hd[0], hinge[1] + r_ * hd[1]])
        ring = [(c_[0] + 2.4 * np.cos(a), c_[1] + 2.4 * np.sin(a)) for a in np.linspace(0, 2 * np.pi, 24, endpoint=False)]
        org = np.array([[sg_ * (HORN_FACE_X + 0.5), y, z] for y, z in ring])
        loc, ri, _ = tj.ray.intersects_location(org, np.tile([sg_, 0, 0], (len(org), 1)))
        x_out = [min(sg_ * loc[ri == i][:, 0]) if (ri == i).any() else HORN_FACE_X for i in range(len(org))]
        xs_ = min(HORN_SCREW_SEAT_MAX, min(x_out) - 0.3)
        horn_cut += [m_cyl([sg_ * (HORN_FACE_X - 1), *c_], [sg_ * 80, *c_], 1.1),
                     m_cyl([sg_ * xs_, *c_], [sg_ * 80, *c_], 3.0)]     # Ø6: room for the bit
        fast.append(dict(name='horn-to-jaw screw (r=%.0f)' % r_, head=np.array([sg_ * xs_, *c_]), axis=u_ax, stage='jaw',
                         cb=max(x_out) - xs_, opening='outside',
                         spec=dict(kind='selftap', L=HORN_SCREW_L, d=2.0, clamped=['jaw'], receiver='horn', head=M2_HEAD,
                                   clear_d=2.2, through=True)))
        log('horn screw r=%.0f at (y, z) = (%.1f, %.1f): head seat |x| = %.1f (ramus outside %.1f..%.1f)'
            % (r_, c_[0], c_[1], xs_, min(x_out), max(x_out)))
    horn_holes = union(horn_cut)
    fast.append(dict(name='jaw pivot bolt (M3x20)', head=np.array([-SERVO_SIDE * (PIVOT_FACE_X + 14.5), hinge[0], hinge[1]]),
                     axis=-u_ax, stage='jaw', cb=PIVOT_PAD['x_end'] - PIVOT_FACE_X - 14.5, opening='outside',
                     spec=dict(kind='insert', L=20.0, d=3.0, clamped=['jaw'], receiver='face', head=M3_HEAD, clear_d=3.5)))
    fast += J['fasteners']
    fast += CJ['fasteners']
    fast.append(dict(name='stand screw (M3x8)', head=np.array([0.0, N['y'] + STAND['col_d'] / 2 - 1.5, N['z_bottom'] + N['screw_z']]),
                     axis=np.array([0, 1.0, 0]), stage='stand', cb=1.5, opening='outside',
                     spec=dict(kind='insert', L=8.0, d=3.0, clamped=['stand'], receiver='face', head=M3_HEAD, clear_d=3.4)))
    hand = dict(eye_bar=corridor, radar=radar_path + radar_lift)
    skin_v = (sh['env'] | (sd > 0))

    # jaw
    jaw_part = clean(jaw_moving - mech['jaw_pad_holes'] - mech['jaw_pivot_holes'] - horn_holes, 'jaw')

    servo_tray, board = servo_tray_parts(mech)
    servo_tray = clean(servo_tray, 'servo_tray')
    parts = dict(face=face, back=back, cap=cap, jaw=jaw_part, servo_tray=servo_tray, stand=stand())
    parts.update(liner_parts)
    for name, br in J['brackets']:
        parts['joint_bracket_' + name] = br
    P = servo_frame(hinge); St = SERVO
    ha = (-15 * np.cos(np.radians(HORN_ARM_DEG)), -15 * np.sin(np.radians(HORN_ARM_DEG)))   # arm tip (v, w)
    horn_show = m_cyl(P(St['spline_top'] - 2.4, 0, 0), P(St['spline_top'] + 1.0, 0, 0), 3.6) + \
        mf.Manifold.batch_hull([m_cyl(P(St['spline_top'] - 0.8, 0, 0), P(St['spline_top'] + 1.0, 0, 0), 3.2),
                                m_cyl(P(St['spline_top'] - 0.8, *ha), P(St['spline_top'] + 1.0, *ha), 2.0)])
    hardware = dict(bar=bar, modules=modules, servo=mech['servo'], horn=horn_show, radar=radar, esp32=board)
    paint = union([sk['paint'] for sk in sockets.values()])
    screens = union([m_cyl([xe, y_glass - 0.15, 0], [xe, y_glass + 0.05, 0], 9.0) for xe in (-EYE_SPACING / 2, EYE_SPACING / 2)])
    yb_ = y_glass - SCREEN_GAP - SOCKET_WALL
    paint = union([paint] + [m_cyl([xe, yb_ - 0.05, 0], [xe, y_glass - 0.1, 0], APERTURE_D / 2 + 0.15) -
                             m_cyl([xe, yb_ - 1, 0], [xe, y_glass, 0], APERTURE_D / 2 - 0.2) for xe in (-EYE_SPACING / 2, EYE_SPACING / 2)])
    return dict(parts=parts, hardware=hardware, display=dict(paint=paint, screens=screens), info=info,
                fasteners=fast, hand=hand, skin_v=skin_v, peg=peg, cap_slide=CJ['slide_dir'], hinge=hinge, mech=mech, jaw_moving=jaw_moving,
                G=G, sh=sh, inside=inside, crm=crm)


# =============================================================== verification
HOLELESS = ('servo', 'horn')     # stand-in models without their screw holes


def fastener_check(R):
    """Every screw in its assembled position, against the parts it joins.
    s is the distance from the nominal head point into the joint (along -axis).
    - head seat s_h: where the head (a ring between the clearance hole and the
      head diameter) first touches the clamped part; the seat must be flat
      (>= 60 % of that ring in material 0.6 mm further in);
    - joint face s_j: where the receiving part starts (a ring round the bore in
      material, or, for a part modelled without its hole, the axis);
    - (a) clearance: the hole through the clamped parts, from the seat to the
      joint face, is empty in every part;
    - (b) insert: an empty Ø INSERT_D bore in the receiving part from the joint
      face, INSERT_BORE deep, and room for the screw tip (no part in the way);
    - (c) wall: at least INSERT_WALL of material round the bore over its depth
      (>= 97 % of that annulus);
    - (d) length: engagement e = L - (s_j - s_h); an insert needs
      >= INSERT_MIN_ENGAGE of thread in it, a self-tapping screw through a thin
      part must pass right through it, hardware threads need the given minimum."""
    allp0 = dict(R['parts']); allp0.update(R['hardware'])
    out = []
    for f in R['fasteners']:
        sp = f.get('spec'); r = dict(name=f['name'], problems=[])
        c_box = m_box(np.asarray(f['head']) - 40, np.asarray(f['head']) + 40)    # parts cropped round the screw (speed)
        allp = {k: m ^ c_box for k, m in allp0.items()}
        allp = {k: m for k, m in allp.items() if not m.is_empty()}
        tm = {}

        def T(k):
            if k not in tm:
                tm[k] = to_tri(allp[k])
            return tm[k]
        out.append(r)
        if sp is None:
            r['problems'].append('no fastener spec'); r['ok'] = False
            continue
        h0 = np.asarray(f['head'], float); ax = np.asarray(f['axis'], float); ax /= np.linalg.norm(ax); u = -ax
        e1 = np.cross(u, [1.0, 0, 0] if abs(u[0]) < 0.9 else [0, 1.0, 0]); e1 /= np.linalg.norm(e1); e2 = np.cross(u, e1)
        ang = np.linspace(0, 2 * np.pi, 16, endpoint=False)

        def pts(ss, rad):
            ss = np.atleast_1d(ss); rad = np.atleast_1d(rad)
            P_ = [h0 + u * s_ + r_ * (np.cos(a) * e1 + np.sin(a) * e2) for s_ in ss for r_ in rad for a in ang] if rad.max() > 0 \
                else [h0 + u * s_ for s_ in ss]
            return np.array(P_)

        def frac_along(part, ss, rad):
            n_ = len(ang) * len(np.atleast_1d(rad)) if np.max(rad) > 0 else 1
            return T(part).contains(pts(ss, rad)).reshape(len(ss), n_).mean(1)

        def cyl(s0, s1, rad):
            return m_cyl(h0 + u * s0, h0 + u * s1, rad)
        if sp['kind'] == 'hw' and 'L' not in sp:
            r.update(ok=True, note=sp.get('note', ''), s_head=0.0)
            continue
        L_ = sp['L']; hr = sp['head']['d'] / 2
        cl_r = (sp.get('clear_d') or sp['d']) / 2
        c0 = sp['clamped'][0]; rec = sp['receiver']
        skip = [k for k in sp['clamped'] + [rec] if k in HOLELESS]    # joined stand-ins modelled without the hole
        # head seat
        ss = np.arange(-4.0, 4.0, 0.05)
        fr = frac_along(c0, ss, np.linspace(cl_r + 0.25, hr - 0.05, 3))
        hit = np.where(fr > 0)[0]
        if not len(hit):
            r['problems'].append('the head never meets %s' % c0); r['ok'] = False
            continue
        s_h = float(ss[hit[0]])
        flat = float(frac_along(c0, [s_h + 0.6], np.linspace(cl_r + 0.25, hr - 0.05, 3))[0])   # past a 0.5 mm edge chamfer
        if flat < 0.6:
            r['problems'].append('head seat not flat (%.0f %% of the head ring bears)' % (100 * flat))
        # joint face
        ss = np.arange(s_h + 0.2, s_h + L_ + 3.0, 0.05)
        bored = sp['kind'] == 'insert' or (sp['kind'] == 'selftap' and sp.get('pilot_d'))
        if sp['kind'] == 'insert':
            fr = frac_along(rec, ss, [INSERT_D / 2 + 0.8])
        elif bored:
            fr = frac_along(rec, ss, [sp['pilot_d'] / 2 + 0.6])
        else:
            fr = frac_along(rec, ss, [0.0])
        hit = np.where(fr >= 0.5)[0]
        if not len(hit):
            r['problems'].append('the screw never reaches %s' % rec); r['ok'] = False
            continue
        s_j = float(ss[hit[0]])
        e = s_h + L_ - s_j
        r.update(L=L_, s_head=round(s_h, 2), s_joint=round(s_j, 2), clamp=round(s_j - s_h, 2), engage=round(e, 2),
                 seat_flat=round(flat, 2))
        # (a) clearance through the clamped parts
        if sp.get('clear_d') and s_j - s_h > 0.3:
            c_ = cyl(s_h + 0.1, s_j - 0.1, cl_r - 0.1)
            bl = {k: round(vol(c_ ^ m) * 1000, 2) for k, m in allp.items() if k not in skip and vol(c_ ^ m) > 0.002}
            r['clearance_blocked_mm3'] = bl
            if bl:
                r['problems'].append('clearance hole blocked by %s' % bl)
        tip = s_h + L_
        if sp['kind'] == 'insert':
            b_ = cyl(s_j - 0.3, s_j + INSERT_BORE - 0.05, INSERT_D / 2 - 0.05)
            r['bore_blocked_mm3'] = round(vol(b_ ^ allp[rec]) * 1000, 2)
            if r['bore_blocked_mm3'] > 2:
                r['problems'].append('insert bore (Ø%.1f x %.1f) not empty: %.1f mm3' % (INSERT_D, INSERT_BORE, r['bore_blocked_mm3']))
            an = cyl(s_j, s_j + INSERT_BORE, INSERT_D / 2 + INSERT_WALL) - cyl(s_j - 1, s_j + INSERT_BORE + 1, INSERT_D / 2 + 0.05)
            r['wall_frac'] = round(vol(an ^ allp[rec]) / vol(an), 3)
            if r['wall_frac'] < 0.97:
                r['problems'].append('wall round the bore %.0f %% (< 97 %% of %.1f mm)' % (100 * r['wall_frac'], INSERT_WALL))
            if min(e, INSERT_L) < INSERT_MIN_ENGAGE:
                r['problems'].append('only %.1f mm of thread in the insert' % min(e, INSERT_L))
        elif bored:
            pr = sp['pilot_d'] / 2
            b_ = cyl(s_j - 0.3, min(tip, s_j + 6.0), pr - 0.05)
            r['bore_blocked_mm3'] = round(vol(b_ ^ allp[rec]) * 1000, 2)
            if r['bore_blocked_mm3'] > 1:
                r['problems'].append('pilot hole not empty')
            an = cyl(s_j, min(tip, s_j + 3.0), pr + 1.2) - cyl(s_j - 1, s_j + 4, pr + 0.05)
            r['wall_frac'] = round(vol(an ^ allp[rec]) / vol(an), 3)
            if r['wall_frac'] < 0.9:
                r['problems'].append('wall round the pilot %.0f %%' % (100 * r['wall_frac']))
        if sp.get('through'):                         # thin receiver: the screw has to pass right through it
            sa = np.arange(s_j, s_j + 12.0, 0.05)
            ins = frac_along(rec, sa, [sp['pilot_d'] / 2 + 0.6] if bored else [0.0]) >= 0.5
            th = float(sa[np.argmin(ins)] - s_j) if not ins.all() else 12.0
            r['receiver_thickness'] = round(th, 2)
            if e < th + 0.3:
                r['problems'].append('does not pass through %s (%.1f in, %.1f thick)' % (rec, e, th))
        if sp.get('min_engage') and e < sp['min_engage']:
            r['problems'].append('engagement %.1f < %.1f' % (e, sp['min_engage']))
        if sp['kind'] != 'hw':                        # the tip must not hit anything past the bore
            t_ = cyl(s_j + 0.2, tip + 0.3, sp['d'] / 2 * 0.8)
            bl = {k: round(vol(t_ ^ m) * 1000, 2) for k, m in allp.items()
                  if k not in skip and k != (rec if not bored else '') and vol(t_ ^ m) > 0.002}
            if bl:
                r['problems'].append('screw tip runs into %s' % bl)
        r['ok'] = not r['problems']
    return out


KNUCKLE_WALL = 4.0      # jaw knuckles: least wall round the pivot bolt, its head counterbore and the horn screws
PIVOT_BOSS_WALL = 2.5   # skull pivot boss: least wall round the insert bore
KNUCKLE_GAP = 1.0       # least clearance of the knuckles (above the trim) to the skull over the sweep


def jaw_check(R):
    """Jaw knuckles and the skull pivot boss, measured on the finished parts in
    sections square to the hinge axis (72 rays round each hole, every 0.5 mm of
    |x| over the knuckle): the wall from each hole to the nearest air. Also the
    clearance of the knuckle tops to the skull (face + back) over the sweep."""
    from matplotlib.path import Path
    hinge = R['hinge']; hy, hz = hinge
    jaw, face = R['parts']['jaw'], R['parts']['face']
    box = m_box([-70, hy - 40, hz - 40], [70, hy + 40, hz + 30])
    jaw, face = jaw ^ box, face ^ box
    Tm = np.array([[0, 1, 0, 0], [0, 0, 1, 0], [1, 0, 0, 0]], float)
    ang = np.linspace(0, 2 * np.pi, 72, endpoint=False)

    def wall(M, x, r0, c):
        pol = M.transform(Tm).slice(x).to_polygons()
        if not pol:
            return 0.0
        v, cd = [], []
        for p_ in pol:
            v += list(p_) + [p_[0]]; cd += [Path.MOVETO] + [Path.LINETO] * (len(p_) - 1) + [Path.CLOSEPOLY]
        rs = np.arange(r0 + 0.05, 25.0, 0.05)
        P_ = np.array([[c[0] + r * np.cos(a), c[1] + r * np.sin(a)] for a in ang for r in rs])
        inn = Path(v, cd).contains_points(P_).reshape(len(ang), len(rs))
        w = np.where(inn.all(1), 25.0, rs[np.argmin(inn, axis=1)] - r0)
        w[~inn[:, 0]] = 0.0
        return float(w.min())
    out = []

    def item(name, M, xs, r0, c, need):
        ws = [wall(M, x, r0, c) for x in xs]
        out.append(dict(name=name, wall=round(min(ws), 2), need=need, ok=min(ws) >= need))
    o = -SERVO_SIDE; sg = SERVO_SIDE
    item('pivot bolt hole (Ø3.5) in the jaw', jaw, o * np.arange(PIVOT_FACE_X + 0.3, PIVOT_FACE_X + 14.5, 0.5), 1.75, (hy, hz), KNUCKLE_WALL)
    item('pivot head counterbore (Ø6.6) in the jaw', jaw, o * np.arange(PIVOT_FACE_X + 14.7, PIVOT_PAD['x_end'] - 0.2, 0.5), 3.3, (hy, hz),
         KNUCKLE_WALL)
    item('horn-hub counterbore (Ø7) in the jaw', jaw, sg * np.arange(HORN_FACE_X + 0.3, HORN_FACE_X + HORN_HUB_CB - 0.2, 0.5), 3.5, (hy, hz),
         KNUCKLE_WALL)
    item('horn driver hole (Ø5) in the jaw', jaw, sg * np.arange(HORN_FACE_X + HORN_HUB_CB + 0.2, JAW_PAD['x_end'] - 0.2, 0.5), 2.5, (hy, hz),
         KNUCKLE_WALL)
    hd = horn_dir(); seats = {f['name']: f['head'] for f in R['fasteners'] if f['name'].startswith('horn-to-jaw')}
    for r_ in HORN_JAW_HOLES:
        xh = abs(seats['horn-to-jaw screw (r=%.0f)' % r_][0])
        item('horn screw pilot (Ø2.2, r=%.0f) in the jaw' % r_, jaw, sg * np.arange(HORN_FACE_X + 0.3, xh - 0.2, 0.5), 1.1,
             (hy + r_ * hd[0], hz + r_ * hd[1]), KNUCKLE_WALL)
    item('pivot insert bore (Ø4) in the skull boss', face, o * np.arange(PIVOT_FACE_X - 0.8, PIVOT_FACE_X - 0.5 - INSERT_BORE, -0.5),
         INSERT_D / 2, (hy, hz), PIVOT_BOSS_WALL)
    # knuckle tops (above the condyle trim, outboard of the pad faces) to the skull
    sk = union([R['parts']['face'], R['parts']['back']]) ^ box
    tops = union([jaw ^ m_box([min(s_ * (x0 + 0.6), s_ * 70), hy - 20, hz + CONDYLE_TRIM - 1.0],
                              [max(s_ * (x0 + 0.6), s_ * 70), hy + 20, hz + 30])
                  for s_, x0 in ((sg, HORN_FACE_X), (o, PIVOT_FACE_X))])
    g = min(tops.transform(rot_x_about(hy, hz, a)).min_gap(sk, 3.0)
            for a in np.arange(JAW_CLOSE_STOP, JAW_OPEN_DEG + JAW_STOP_MARGIN + 0.01, 1.0))
    out.append(dict(name='knuckle tops to the skull over the sweep', wall=round(g, 2), need=KNUCKLE_GAP, ok=g >= KNUCKLE_GAP))
    return out


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
                for q in (A ^ B_).decompose():
                    if q.volume() > 2:
                        log('  clash %s/%s %.1f mm3 at %s' % (a, b, q.volume(), np.round(q.bounding_box(), 1)))
    others = union([P['face'], P['back'], H['servo'], P['servo_tray'], P['stand']])
    jm = P['jaw']
    for a in np.arange(JAW_CLOSE_STOP, JAW_OPEN_DEG + JAW_STOP_MARGIN + 0.01, 1.0):
        v = vol(jm.transform(rot_x_about(*hinge, a)) ^ others)
        rep['jaw_sweep'].append((round(float(a), 1), round(v, 3)))
    # stop check: one step past each stop must collide (finger in the slot end)
    for a in (JAW_CLOSE_STOP - 1.5, JAW_OPEN_DEG + JAW_STOP_MARGIN + 1.5):
        rep.setdefault('beyond_stops', []).append((float(a), round(vol(jm.transform(rot_x_about(*hinge, a)) ^ P['face']), 3)))
    # ---- tool access: every fastener needs a straight tool path when it is driven
    STAGES = ['bench_servo', 'bench_horn', 'eyebar', 'radar', 'servo_tray', 'esp32', 'jaw', 'brackets_floor', 'back',
              'brackets_cap', 'cap', 'stand']
    FITTED = dict(eyebar=['bar', 'modules'], radar=['radar'], servo_tray=['servo', 'servo_tray', 'horn'],
                  esp32=['esp32'], jaw=['jaw'], brackets_floor=[k for k in P if k.startswith('joint_bracket_back')], back=['back'],
                  brackets_cap=[k for k in P if k.startswith('joint_bracket_cap')], cap=['cap'], stand=['stand'])
    allp = dict(P); allp.update(H)

    def present(stage):
        if stage == 'bench_servo':
            return ['servo', 'servo_tray']
        if stage == 'bench_horn':
            return ['servo', 'servo_tray', 'horn']
        out = ['face']
        for st in STAGES[2:STAGES.index(stage) + 1]:
            out += FITTED.get(st, [])
        return out
    rep['tool_access'] = []
    tools = []; hands = []
    G = R['G']; n_seam, p_seam = seam()
    for f in R['fasteners']:
        h0 = np.asarray(f['head'], float); ax = np.asarray(f['axis'], float); ax /= np.linalg.norm(ax)
        a_len = f.get('cb', 0.0) + TOOL_TIP_L
        tool = m_cyl(h0 + ax * 0.2, h0 + ax * a_len, TOOL_TIP_D / 2) + m_cyl(h0 + ax * a_len, h0 + ax * TOOL_LEN, TOOL_D / 2)
        tools.append((f.get('opening', 'bench'), tool))
        obst = union([allp[k] for k in present(f['stage'])])
        v = vol(tool ^ obst)
        blockers = [k for k in present(f['stage']) if vol(tool ^ allp[k]) > 0.005] if v > 0.005 else []
        # which opening does the tool leave through?
        pres = present(f['stage'])
        exit_ = 'bench'
        if not f['stage'].startswith('bench'):
            exit_ = None; last = None
            for tt in np.arange(f.get('cb', 0.0) + 3.0, TOOL_LEN + 0.01, 1.0):
                q = h0 + ax * tt
                ii = G.idx(q)
                inside_ = all(0 <= ii[k_] < G.shape[k_] for k_ in range(3)) and R['skin_v'][ii]
                reg = 'cap' if np.dot(q - p_seam, n_seam) > 0 else ('back' if (q[1] > Y_BACK and q[2] > Z_FLOOR) else 'face')
                if not inside_:
                    break
                last = reg
            exit_ = 'outside' if last is None else {'cap': 'top', 'back': 'back', 'face': 'face'}[last]
            exit_ = exit_ or 'none'
        want = f.get('opening', 'bench')
        hand_v = 0.0
        if f.get('hand'):
            c_ = h0 + ax * 85.0
            hb = m_box([c_[0] - 30, c_[1] - 25, c_[2] - 20], [c_[0] + 30, c_[1] + 25, c_[2] + 20])
            hands.append(hb)
            hand_v = vol(hb ^ obst)
        rep['tool_access'].append(dict(name=f['name'], stage=f['stage'], blocked_cm3=round(v, 3), blocked_by=blockers,
                                       exits=exit_, wanted=want, hand_blocked_cm3=round(hand_v, 3),
                                       ok=(v <= 0.005 and (want == 'bench' or exit_ == want) and hand_v <= 0.005)))
    for op in ('back', 'top', 'outside'):
        sel = [t_ for o_, t_ in tools if o_ == op]
        if sel:
            R['display']['tools_' + op] = union(sel)
    if hands:
        R['display']['hands'] = union(hands)
    # ---- hand access for the eye bar and the radar (the cap off, earlier parts fitted)
    hd = R['hand']
    rep['hand_access'] = dict(
        eye_bar_path=round(vol(hd['eye_bar'] ^ (P['face'] - R['peg'] if R['peg'] is not None else P['face'])), 3),
        radar_path=round(vol(hd['radar'] ^ union([P['face'], H['bar'], H['modules']])), 3))
    # covers: the back lifts straight up (cap already off), the cap along its normal
    under = union([P['face'], P['jaw'], P['servo_tray'], H['servo'], H['horn'], H['esp32'], H['bar'], H['modules'],
                   H['radar']] + [m for k, m in P.items() if k.startswith('joint_bracket_back')])
    bl = [(vol(P['back'].translate([0, 0, d]) ^ under), d) for d in np.arange(1.0, 121.0, 2.0)]
    rep['back_lift'] = max(bl)[0]
    if rep['back_lift'] > 0.005:
        d = max(bl)[1]
        for q in (P['back'].translate([0, 0, d]) ^ under).decompose():
            if q.volume() > 1:
                log('  back drop-in clash at lift %g: %.1f mm3 at %s' % (d, q.volume(), np.round(q.bounding_box(), 1)))
    under2 = union([under, P['back']] + [m for k, m in P.items() if k.startswith('joint_bracket_cap')])
    sl = CAP_HOOK['slide'] + 0.5
    cap_path = [R['cap_slide'] * d for d in np.arange(0.5, sl + 0.01, 0.5)] + \
        [R['cap_slide'] * sl + n_seam * d for d in np.arange(1.0, 121.0, 2.0)]
    rep['cap_lift'] = max(vol(P['cap'].translate(list(v)) ^ under2) for v in cap_path)
    # joint brackets: the back part slides on along Y; nothing may catch on the way
    rep['bracket_slide'] = []
    for k, m in P.items():
        if k.startswith('joint_bracket'):
            fl_ = 'back' in k[len('joint_bracket_'):].split('_')[0]
            n_s = np.array([0, 0, 1.0]) if fl_ else seam()[0]
            upper_ = P['back'] if fl_ else P['cap']
            worst = max(vol(m.translate(list(-n_s * d)) ^ upper_) for d in np.arange(0.5, JOINT_H + 10, 1.0))
            rep['bracket_slide'].append((k, round(worst, 3)))
    rep['fastener_check'] = fastener_check(R)
    rep['jaw_check'] = jaw_check(R)
    return rep


# =============================================================== outputs
def rx(deg):
    a = np.radians(deg); c, s_ = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0, 0], [0, c, -s_, 0], [0, s_, c, 0]], float)


def ry(deg):
    a = np.radians(deg); c, s_ = np.cos(a), np.sin(a)
    return np.array([[c, 0, s_, 0], [0, 1, 0, 0], [-s_, 0, c, 0]], float)


PRINT_ORIENT = {   # rotation into print orientation (then dropped onto z = 0, centred)
    'face': rx(0),              # upright (it has two cut faces at right angles; supports needed)
    'back': rx(0),              # lower cut (z = Z_FLOOR) on the bed
    'cap': 'seam_up',           # cut face on the bed, crown up
    'jaw': rx(0),               # upright, as in the skull
    'servo_tray': ry(90 * SERVO_SIDE),   # servo mounting plate on the bed; slab, ribs and cradle stand up
    'stand': rx(0),
    'dowel': rx(0),
}


def print_pose(name, M):
    T = PRINT_ORIENT.get(name, rx(90) if name.startswith('joint_bracket') else rx(0))
    if isinstance(T, str):                     # put the seam plane on the bed
        n, _ = seam()
        a = np.degrees(np.arctan2(n[1], n[2]))  # tilt of n from +Z toward +Y
        T = rx(a) if T == 'seam_up' else rx(a + 180.0)
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
        if P.num_tri() > 150000:          # keep the STLs small enough for git (< 25 MB)
            n0 = P.num_tri(); P = P.simplify(SIMPLIFY_TOL)
            log('%s: simplified %d -> %d triangles (tolerance %.2f mm)' % (name, n0, P.num_tri(), SIMPLIFY_TOL))
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
COLORS = dict(face='ivory', back='wheat', cap='navajowhite', jaw='tan', servo_tray='mediumpurple',
              stand='gray', bar='dimgray', modules='black', servo='royalblue', horn='crimson', radar='red',
              esp32='teal', paint='#1a1a1a', screens='gold', tools='deepskyblue')


def render(R):
    import subprocess
    tmp = os.path.join(CACHE, 'render'); os.makedirs(tmp, exist_ok=True)
    for f in os.listdir(tmp):                       # no stale parts (the viewer reads this folder)
        if f.endswith('.stl'):
            os.remove(os.path.join(tmp, f))
    items = dict(R['parts']); items.pop('dowel', None)
    items.update(R['hardware'])
    items.update(R['display'])
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
            if k in skip or k.startswith('tools') or k == 'hands':
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
    # exploded in assembly order: face (chassis) stays put; eye bar + LCDs and radar
    # come out of its back, then the servo, the tray + ESP32, the jaw, the cover
    n_, _ = seam()
    lift = lambda d: tuple(float(v) for v in n_ * d)
    ex = dict(bar=(0, 70, 0), modules=(0, 70, 0), radar=(0, 40, 60), esp32=(0, 0, 115),
              servo=(0, 0, 70), servo_tray=(0, 0, 70), horn=(0, 0, 70), jaw=(0, 0, -70),
              back=(0, 150, 60), cap=lift(250), stand=(0, 0, -120))
    for k in items:
        if k.startswith('joint_bracket_back'):
            ex[k] = (0, 110, 60)
        elif k.startswith('joint_bracket'):
            ex[k] = lift(190)
    e = scad('expl.scad', asm(explode=ex))
    jobs.append(('skull_exploded.png', e, '0,90,90,70,0,300,1250'))
    eyes_hw = ('bar', 'modules', 'radar', 'screens', 'paint')
    allhw = eyes_hw + ('servo', 'servo_tray', 'horn', 'esp32', 'jaw')

    def imp(keys, extra=''):
        return 'color("ivory") import("face.stl");\n' + '\n'.join(
            'color("%s") import("%s.stl");' % (col(k), k) for k in items if k in keys) + extra
    fb = scad('chassis_back_tools.scad', imp(eyes_hw, '\ncolor("deepskyblue", 0.5) import("tools_back.stl");'
                                                    '\ncolor("orange", 0.25) import("hands.stl");'))
    jobs.append(('skull_chassis_from_behind.png', fb, '0,60,10,90,0,180,360'))
    jobs.append(('skull_chassis_from_behind_34.png', fb, '0,60,10,70,0,215,420'))
    ft = scad('chassis_top_tools.scad', imp(allhw + tuple(k for k in items if k.startswith('joint_bracket_back')),
                                             '\ncolor("deepskyblue", 0.5) import("tools_top.stl");'))
    jobs.append(('skull_chassis_from_above.png', ft, '0,60,0,20,0,200,420'))
    fo = scad('chassis_open.scad', imp(allhw))
    jobs.append(('skull_chassis_34_hw.png', fo, '0,50,-10,55,0,140,380'))
    bk = scad('covers.scad', 'color("wheat") import("back.stl");\ntranslate([0,0,60]) color("navajowhite") import("cap.stl");')
    jobs.append(('skull_covers.png', bk, '0,90,40,60,0,140,520'))
    # jaw knuckles: each half of the jaw on its own, from outside and from inside (3/4 views)
    for k_, lo_, hi_ in (('jaw_left', -100.0, 0.0), ('jaw_right', 0.0, 100.0)):
        to_tri(items['jaw'] ^ m_box([lo_, -100, -150], [hi_, 200, 100])).export(os.path.join(tmp, k_ + '.stl'))
    for side_, nm_ in ((-SERVO_SIDE, 'pivot'), (SERVO_SIDE, 'horn')):
        k_ = 'jaw_left' if side_ < 0 else 'jaw_right'
        f_ = scad('%s_half.scad' % nm_, 'color("tan") import("%s.stl");' % k_)
        c_ = '%g,%g,%g' % (side_ * 40, hinge[0] - 5, hinge[1] - 8)
        rz_out, rz_in = (240, 120) if side_ < 0 else (120, 240)
        jobs.append(('out/closeup_jaw_%s_34.png' % nm_, f_, '%s,65,0,%d,150' % (c_, rz_out)))
        jobs.append(('out/closeup_jaw_%s_34_inside.png' % nm_, f_, '%s,65,0,%d,150' % (c_, rz_in)))
    procs = []
    for fn, f, cam in jobs:
        procs.append(subprocess.Popen([SCAD, '-o', os.path.join(HERE, fn), '--preview', '--imgsize=1400,1100',
                                       '--camera=' + cam, '--projection=o', '--colorscheme=Tomorrow', f],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    for p in procs:
        p.wait()
    for f in os.listdir(tmp):                         # keep the viewer to real parts
        if f.startswith('tools') or f in ('hands.stl', 'jaw_left.stl', 'jaw_right.stl'):
            os.remove(os.path.join(tmp, f))
    sections(R, items)
    log('rendered %d previews + sections' % len(jobs))


def render_usb(R, K):
    """skull_esp32_usb.png: the chassis with the cap off, the servo tray, the ESP32 and the
    keep-outs (DuPont housings + wires orange, plug + boot red, insertion path and grip yellow,
    cable blue, EN/BOOT fingertips green). Left: from above, back cover on; right: from behind
    and above with the back cover off, showing the cable loop down into the neck bore."""
    import subprocess
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    tmp = os.path.join(CACHE, 'render_usb'); os.makedirs(tmp, exist_ok=True)
    P, H = R['parts'], R['hardware']
    items = dict(face=P['face'], back=P['back'], servo_tray=P['servo_tray'], jaw=P['jaw'], servo=H['servo'], horn=H['horn'],
                 esp32=H['esp32'], bar=H['bar'], modules=H['modules'], radar=H['radar'],
                 ko_dupont=union(K['dupont']), ko_plug=K['plug'], ko_path=K['path'] - K['plug'], ko_grip=K['grip'] - K['path'],
                 ko_cable=K['cable'], ko_buttons=K['buttons'])
    for k, m in items.items():
        to_tri(m).export(os.path.join(tmp, k + '.stl'))
    cols = dict(COLORS, ko_dupont='"orange", 0.55', ko_plug='"red"', ko_path='"yellow", 0.35', ko_grip='"gold", 0.2',
                ko_cable='"dodgerblue"', ko_buttons='"lime", 0.5', back='"wheat", 0.9')

    def body(skip):
        return '\n'.join('color(%s) import("%s.stl");' % (cols[k] if cols.get(k, '').startswith('"') else '"%s"' % cols.get(k, 'orange'), k)
                         for k in items if k not in skip)
    shots = [('a.scad', body(()), '0,90,0,0,0,0,330'), ('b.scad', body(('back', 'jaw')), '5,85,0,62,0,160,330')]
    pngs = []
    procs = []
    for fn, b, cam in shots:
        with open(os.path.join(tmp, fn), 'w') as f:
            f.write(b)
        png = os.path.join(tmp, fn.replace('.scad', '.png')); pngs.append(png)
        procs.append(subprocess.Popen([SCAD, '-o', png, '--preview', '--imgsize=1100,1100', '--camera=' + cam, '--projection=o',
                                       '--colorscheme=Tomorrow', os.path.join(tmp, fn)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    for p in procs:
        p.wait()
    fig, ax = plt.subplots(1, 2, figsize=(22, 11.5))
    titles = ['From above, cap off (back cover on)', 'From behind and above, cap and back cover off: cable loop into the neck bore']
    for a, png, t in zip(ax, pngs, titles):
        a.imshow(plt.imread(png)); a.set_axis_off(); a.set_title(t, fontsize=13)
    fig.suptitle('ESP32 on the servo tray: DuPont housings + wires (orange), USB plug + boot (red), insertion path (yellow), '
                 'grip (gold), cable (blue), EN/BOOT fingertips (green)', fontsize=13, y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.95)); fig.savefig(os.path.join(OUT, 'skull_esp32_usb.png'), dpi=80); plt.close(fig)


def sections(R, items):
    """Filled cross-sections (matplotlib) through the orbits and the jaw mechanism."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch, Patch
    from matplotlib.path import Path
    cols = dict(face='#f2e6c4', back='#d9b87c', jaw='#b88a4a', bar='#666666', modules='#111111',
                servo='#3355cc', servo_tray='#9370db', horn='#cc2233', radar='#ee2222', esp32='#119999', stand='#999999', paint='#111111', screens='#e0b000', cap='#f5deb3')
    maps = dict(z=(np.eye(4)[:3], ('x', 'y'), 1), x=(np.array([[0, 1, 0, 0], [0, 0, 1, 0], [1, 0, 0, 0]], float), ('y', 'z'), 1),
                y=(np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0]], float), ('x', 'z'), -1))

    def section(ax, axis, c, xl, yl, title):
        T, lab, sg = maps[axis]
        used = set()
        for n, m in items.items():
            if n.startswith('tools') or n == 'hands':
                continue
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
    fig, ax = plt.subplots(1, 3, figsize=(24, 8))
    section(ax[0], 'x', 0.0, (-25, 15), (12, 48), 'Cap front: hook under the chassis ledge (x = 0)')
    section(ax[1], 'x', 0.0, (110, 165), (-30, 40), 'Back: cover screw into chassis post (low), cap screw into back-cover boss (high)')
    section(ax[2], 'x', -52.0, (30, 140), (-30, 40), 'Side (x = -52): back cover on the floor lip')
    fig.tight_layout(); fig.savefig(os.path.join(HERE, 'skull_cover_joints.png'), dpi=90); plt.close(fig)
    closeups(R, items, cols)
    fig, ax = plt.subplots(1, 2, figsize=(18, 9))
    section(ax[0], 'x', 0.0, (40, 140), (-140, 0), 'Cable path (x = 0): neck bore -> stand column -> base')
    section(ax[1], 'z', NECK['z_bottom'] - 30.0, (-60, 60), (40, 140), 'Stand column (z = %.0f): open cable slot toward -X' % (NECK['z_bottom'] - 30))
    fig.tight_layout(); fig.savefig(os.path.join(HERE, 'skull_stand_cable.png'), dpi=90); plt.close(fig)


def closeups(R, items, cols):
    """Close-up sections through screw axes (into out/): the plane holds the
    screw axis (and a second in-plane direction); the screw is drawn over the
    parts: head (dark), shank to its tip (red outline), insert (gold)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch, Patch, Rectangle, Polygon
    from matplotlib.path import Path
    F = {f['name']: f for f in R['fasteners']}

    def panel(ax, origin, eu, ev, half, title, screws):
        origin = np.asarray(origin, float); eu = np.asarray(eu, float) / np.linalg.norm(eu)
        ev = np.asarray(ev, float); ev = ev - eu * np.dot(ev, eu); ev /= np.linalg.norm(ev)
        en = np.cross(eu, ev)
        M = np.zeros((3, 4)); M[0, :3] = eu; M[1, :3] = ev; M[2, :3] = en
        M[:, 3] = -M[:, :3] @ origin
        used = set()
        for n, m in items.items():
            if n.startswith('tools') or n == 'hands' or n in ('paint', 'screens'):
                continue
            mm = m.transform(M)
            b = np.array(mm.bounding_box())
            if b[2] > 0 or b[5] < 0 or b[0] > half or b[3] < -half or b[1] > half or b[4] < -half:
                continue
            pol = mm.slice(0.0).to_polygons()
            if not pol:
                continue
            verts, codes = [], []
            for p in pol:
                verts += list(p) + [p[0]]; codes += [Path.MOVETO] + [Path.LINETO] * (len(p) - 1) + [Path.CLOSEPOLY]
            ax.add_patch(PathPatch(Path(verts, codes), fc=cols.get(n, '#ff9900'), ec='k', lw=0.6))
            used.add((n, cols.get(n, '#ff9900')))
        for nm in screws:
            f = F[nm]; sp = f['spec']; a = -np.asarray(f['axis'], float); a /= np.linalg.norm(a)
            h = np.asarray(f['head'], float)
            pu = lambda q: (np.dot(q - origin, eu), np.dot(q - origin, ev))
            w = np.array([np.dot(a, eu), np.dot(a, ev)]); w /= np.linalg.norm(w); nn = np.array([-w[1], w[0]])

            def quad(s0, s1, r):
                c0 = np.array(pu(h)) + w * s0; c1 = np.array(pu(h)) + w * s1
                return [c0 + nn * r, c1 + nn * r, c1 - nn * r, c0 - nn * r]
            ax.add_patch(Polygon(quad(-sp['head']['h'], 0, sp['head']['d'] / 2), fc='#333333', ec='k', lw=0.8, alpha=0.85))
            ax.add_patch(Polygon(quad(0, sp['L'], sp['d'] / 2), fc='none', ec='red', lw=1.6, ls='--'))
            t = [x for x in R.get('fcheck', []) if x['name'] == nm]
            if sp['kind'] == 'insert' and t and 's_joint' in t[0]:
                sj = t[0]['s_joint']
                ax.add_patch(Polygon(quad(sj, sj + INSERT_L, 2.0), fc='#e0b000', ec='#806000', lw=0.8, alpha=0.6))
        ax.set_xlim(-half, half); ax.set_ylim(-half, half); ax.set_aspect('equal'); ax.grid(alpha=0.3)
        ax.set_title(title, fontsize=10)
        hd = [Patch(fc=c_, ec='k', label=k) for k, c_ in sorted(used)]
        hd += [Patch(fc='#333333', label='screw head'), Patch(fc='none', ec='red', ls='--', label='screw'),
               Patch(fc='#e0b000', alpha=0.6, label='heat-set insert')]
        ax.legend(handles=hd, loc='lower left', fontsize=7)
        ax.set_xlabel('mm'); ax.set_ylabel('mm')

    def one(fname, panels):
        fig, axs = plt.subplots(1, len(panels), figsize=(8 * len(panels), 8))
        for ax, pnl in zip(np.atleast_1d(axs), panels):
            panel(ax, *pnl)
        fig.tight_layout(); fig.savefig(os.path.join(OUT, fname), dpi=90); plt.close(fig)
    fb = F['back cover screw (M3x12)']; fc = F['cap screw (M3x12)']
    one('closeup_back_cover_screw.png', [
        (fb['head'] - fb['axis'] * 6, [0, 1.0, 0], [0, 0, 1.0], 16, 'Back cover -> chassis post (x = 0, side view, back to the right)',
         [fb['name']]),
        (fb['head'] - fb['axis'] * 6, [0, 1.0, 0], [1.0, 0, 0], 16, 'Same screw, horizontal section through the axis (from above)',
         [fb['name']])])
    one('closeup_cap_screw.png', [
        (fc['head'] - fc['axis'] * 6, fc['axis'], [0, -SEAM['slope'], 1.0], 16,
         'Cap -> back-cover boss (x = 0, side view, back to the right)', [fc['name']]),
        (fc['head'] - fc['axis'] * 6, fc['axis'], [1.0, 0, 0], 16, 'Same screw, section across (from above)', [fc['name']])])
    hn = [k for k in F if k.startswith('horn-to-jaw')]
    fh = F[hn[0]]; hd_ = horn_dir()
    one('closeup_jaw_horn_pad.png', [
        (np.array([SERVO_SIDE * 38.0, *R['hinge']]) + np.array([0, *hd_]) * 8, [1.0, 0, 0], [0, *hd_], 18,
         'Jaw servo-side pad: section along the horn arm through both M2x16 screws', hn),
        (np.array([SERVO_SIDE * 37.0, *R['hinge']]), [0, 1.0, 0], [0, 0, 1.0], 24,
         'Jaw servo-side knuckle, seen from inside (x = %.0f): outline, horn-screw holes' % (SERVO_SIDE * 37.0), [])])
    fp = F['jaw pivot bolt (M3x20)']
    one('closeup_jaw_pivot.png', [
        (np.array([-SERVO_SIDE * 36.0, *R['hinge']]), [1.0, 0, 0], [0, 0, 1.0], 20,
         'Jaw pivot: section through the bolt axis (y = %.1f), seen from the front' % R['hinge'][0], [fp['name']]),
        (np.array([-SERVO_SIDE * 37.0, *R['hinge']]), [0, 1.0, 0], [0, 0, 1.0], 20,
         'Jaw pivot knuckle (x = %.0f): Ø%.0f round the bolt + tail down the neck, stop finger' % (-SERVO_SIDE * 37.0, 2 * PIVOT_PAD['r']), [])])


def main():
    R = build()
    rep = verify(R)
    R['fcheck'] = rep['fastener_check']
    rep['info'] = R['info']
    for k, v in rep['parts'].items():
        log('%-24s %6.1f cm3  %s mm  watertight=%s bodies=%d' % (k, v['volume_cm3'], v['size'], v['watertight'], v['bodies']))
    log('collisions (> 0.005 cm3):', rep['collisions'] or 'none')
    log('bracket slide-on interference (cm3):', rep['bracket_slide'])
    log('back cover drop-in (straight down, cap off): %.3f cm3; cap (lower 6.5 mm back, slide forward under the hook): %.3f cm3'
        % (rep['back_lift'], rep['cap_lift']))
    bad = [t for t in rep['tool_access'] if not t['ok']]
    for t in rep['tool_access']:
        msg = 'OK ' if t['ok'] else 'FAIL'
        det = 'exits %-7s (wanted %s)' % (t['exits'], t['wanted'])
        if t['blocked_cm3'] > 0.005:
            det += ', BLOCKED by %s' % ', '.join(t['blocked_by'])
        if t['hand_blocked_cm3'] > 0.005:
            det += ', hand space blocked %.2f cm3' % t['hand_blocked_cm3']
        log('  %s %-34s %-14s %s' % (msg, t['name'], t['stage'], det))
    log('hand access (blocked cm3):', rep['hand_access'])
    log('fastener check (s: mm from the head point; clamp = seat to joint face; e = thread engaged):')
    for t in rep['fastener_check']:
        log('  %s %-34s clamp %5s  e %5s  wall %5s  %s' % ('OK ' if t['ok'] else 'FAIL', t['name'], t.get('clamp', '-'), t.get('engage', '-'),
                                                         t.get('wall_frac', '-'), '; '.join(t['problems']) or t.get('note', '')))
    rep['usb'], usb_k = usb_checks(R)
    for k, v in rep['usb'].items():
        log('  usb/esp32 %-18s %s' % (k, v if v != {} else 'clear'))
    rep['failures'] = rep['usb']['failures'] + [t['name'] for t in bad] + [k for k, v in rep['hand_access'].items() if v > 0.005] + \
        (['back lift-off'] if rep['back_lift'] > 0.005 else []) + (['cap lift-off'] if rep['cap_lift'] > 0.005 else []) + \
        ['collision %s/%s' % (a, b) for a, b, v in rep['collisions']] + \
        ['fastener %s' % t['name'] for t in rep['fastener_check'] if not t['ok']] + \
        ['jaw %s' % t['name'] for t in rep['jaw_check'] if not t['ok']] + \
        ['jaw sweep overlap at %g deg' % a for a, v in rep['jaw_sweep'] if v > 0.005] + \
        ['jaw stop at %g deg does not stop' % a for a, v in rep['beyond_stops'] if v <= 0.005] + liners.failures()
    log('jaw knuckles (least wall / clearance, mm):')
    for t in rep['jaw_check']:
        log('  %s %-48s %5.2f (>= %.1f)' % ('OK ' if t['ok'] else 'FAIL', t['name'], t['wall'], t['need']))
    log('jaw sweep overlaps:', [a for a in rep['jaw_sweep'] if a[1] > 0.005] or 'none',
        '| past the stops:', rep['beyond_stops'])
    export(R)
    with open(os.path.join(OUT, 'build_report.json'), 'w') as f:
        json.dump(rep, f, indent=1, default=lambda o: float(o) if np.isscalar(o) else str(o))
    if '--no-render' not in sys.argv:
        render(R)
        render_usb(R, usb_k)
        liners.render_png(R['parts']['face'], {k: v for k, v in R['parts'].items() if k.startswith('liner_')},
                          os.path.join(OUT, 'skull_face_liners.png'), SCAD, log)
    if rep['failures']:
        log('FAILED access checks:', rep['failures'])
        sys.exit(1)
    return R, rep


if __name__ == '__main__':
    main()
