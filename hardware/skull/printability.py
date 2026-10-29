"""Printability check: overhangs and bridges of a part in its print orientation.

`analyse(M)` takes a part already in print pose (on z = 0, +Z up) and returns:

- overhang_mm2: area of the downward-facing surface steeper than 45° from
  vertical (normal more than 45° below horizontal, MAX_ANGLE + ANGLE_TOL),
  not counting the face on the bed;
- bridge_mm2 / longest_bridge_mm: the part of that area that is a near-
  horizontal ceiling held up on two opposite sides (a bridge), and the longest
  span among those. A ceiling region counts as a bridge when, along one
  direction, every point of it lies on a straight run that starts and ends on
  material supported from below (searched in 8 directions; the shortest such
  set of runs gives the span);
- support_mm2: everything else of the overhang, i.e. what a slicer would put
  support under (overhang_mm2 - bridge_mm2);
- bed_mm2: the flat contact area on the bed.

The bridge test works on two slices just above and just below each ceiling
level (manifold3d slices, rasterised at RES mm).
"""
import numpy as np
import trimesh
import manifold3d as mf
from scipy import ndimage

MAX_ANGLE = 45.0        # overhang limit, degrees from vertical
ANGLE_TOL = 1.0         # surfaces up to this much past the limit (meshing of exact 45° chamfers) pass
FLAT = 0.985            # |n_z| above this = a horizontal ceiling (bridge candidate), ~10°
BED_Z = 0.05            # faces with every vertex below this are on the bed
RES = 0.1               # raster cell (mm) for the bridge test
DZ = 0.15               # slices this far above / below a ceiling
DIRS = [(1, 0), (0, 1), (1, 1), (1, -1), (2, 1), (1, 2), (2, -1), (1, -2)]
MAX_SPAN = 80.0         # longest run followed (mm); longer counts as not anchored
BRIDGE_COVER = 0.97     # a ceiling region is a bridge if this fraction of it is spanned in one direction


def _tri(M):
    if isinstance(M, trimesh.Trimesh):
        return M
    m = M.to_mesh()
    return trimesh.Trimesh(np.asarray(m.vert_properties)[:, :3], np.asarray(m.tri_verts), process=False)


def _man(t):
    return mf.Manifold(mf.Mesh(vert_properties=np.asarray(t.vertices, np.float32), tri_verts=np.asarray(t.faces, np.uint32)))


def _raster(M, z, lo, shape):
    """Material at height z as a boolean grid (cells RES, origin lo = (x0, y0))."""
    from PIL import Image, ImageDraw
    acc = np.zeros(shape[::-1], bool)          # rows = y, cols = x
    for poly in M.slice(float(z)).to_polygons():
        p = (np.asarray(poly) - lo) / RES
        if len(p) < 3:
            continue
        im = Image.new('1', (shape[0], shape[1]), 0)
        ImageDraw.Draw(im).polygon([tuple(q) for q in p], fill=1, outline=1)
        acc ^= np.asarray(im, bool)
    return acc.T                               # [ix, iy]


def _spans(U, anchor, lab, comp):
    """For one ceiling component (cells lab == comp): per direction, the fraction
    of its cells on a run through U that ends on `anchor` (material) at both ends,
    and the longest such run (mm)."""
    cells = np.argwhere(lab == comp)
    if len(cells) > 4000:                      # a sample is enough for the fraction and the span
        cells = cells[np.random.default_rng(0).choice(len(cells), 4000, replace=False)]
    best = None
    nx, ny = U.shape
    for d in DIRS:
        step = np.array(d); sl = float(np.hypot(*d)) * RES
        ends = []
        for sgn in (1, -1):
            pos = cells.copy(); dist = np.zeros(len(cells)); hit = np.zeros(len(cells), int)   # 0 open, 1 anchor, 2 free
            alive = np.ones(len(cells), bool)
            for k in range(1, int(MAX_SPAN / sl) + 2):
                pos[alive] += sgn * step
                dist[alive] += sl
                p = pos[alive]
                inb = (p[:, 0] >= 0) & (p[:, 0] < nx) & (p[:, 1] >= 0) & (p[:, 1] < ny)
                idx = np.where(alive)[0]
                out_ = idx[~inb]; hit[out_] = 2; alive[out_] = False
                idx = idx[inb]; p = p[inb]
                inU = U[p[:, 0], p[:, 1]]
                anc = anchor[p[:, 0], p[:, 1]]
                hit[idx[~inU & anc]] = 1
                hit[idx[~inU & ~anc]] = 2
                alive[idx[~inU]] = False
                if not alive.any():
                    break
            ends.append((hit, dist))
            if (hit == 1).mean() < BRIDGE_COVER:
                break
        if len(ends) < 2:
            continue
        ok = (ends[0][0] == 1) & (ends[1][0] == 1)
        frac = ok.mean()
        span = float((ends[0][1] + ends[1][1])[ok].max()) if ok.any() else 0.0
        if frac >= BRIDGE_COVER and (best is None or span < best[1]):
            best = (d, span, frac)
    return best


def analyse(M, name=''):
    t = _tri(M)
    Mm = M if isinstance(M, mf.Manifold) else _man(t)
    n = t.face_normals; A = t.area_faces; V = t.vertices[t.faces]
    zc = V[:, :, 2].mean(1)
    on_bed = V[:, :, 2].max(1) < BED_Z
    lim = -np.sin(np.radians(MAX_ANGLE + ANGLE_TOL))
    steep = (n[:, 2] < lim) & ~on_bed
    flat = steep & (n[:, 2] < -FLAT)
    res = dict(overhang_mm2=round(float(A[steep].sum()), 1), bed_mm2=round(float(A[on_bed & (n[:, 2] < -0.999)].sum()), 1))
    bridged = np.zeros(len(A), bool)
    bridges = []
    # ceiling levels: cluster the flat downward faces by height
    if flat.any():
        zs = np.sort(np.unique(np.round(zc[flat], 2)))
        levels = []
        for z in zs:
            if levels and z - levels[-1][-1] < 0.1:
                levels[-1].append(z)
            else:
                levels.append([z])
        for lv in levels:
            z0 = float(np.mean(lv))
            sel = flat & (np.abs(zc - z0) < 0.12 + (lv[-1] - lv[0]))
            if not sel.any():
                continue
            pts = V[sel].reshape(-1, 3)
            lo = pts[:, :2].min(0) - 25.0; hi = pts[:, :2].max(0) + 25.0
            shape = tuple(int(v) for v in np.ceil((hi - lo) / RES).astype(int) + 1)
            up = _raster(Mm, z0 + DZ, lo, shape)
            dn = _raster(Mm, z0 - DZ, lo, shape) if z0 - DZ > 0 else np.ones_like(up)
            sup = ndimage.binary_dilation(dn, iterations=int(np.ceil(2 * DZ / RES)) + 1)   # 45° over the two slices
            U = ndimage.binary_opening(up & ~sup)  # unsupported (raster slivers along supported edges dropped)
            lab, nl = ndimage.label(U)
            free_ = up & ~dn                       # runs go through this; they end on material (anchor) or air
            fc = t.triangles_center[sel]
            ij = np.clip(np.round((fc[:, :2] - lo) / RES).astype(int), 0, np.array(shape) - 1)
            flab = lab[ij[:, 0], ij[:, 1]]
            fidx = np.where(sel)[0]
            # faces whose centre is not in an unsupported cell are edge slivers of a supported ceiling
            bridged[fidx[flab == 0]] = True
            for c in range(1, nl + 1):
                if not (flab == c).any():
                    continue
                b = _spans(free_, up, lab, c)
                if b is not None:
                    bridged[fidx[flab == c]] = True
                    bridges.append(dict(z=round(z0, 2), span_mm=round(b[1], 1), area_mm2=round(float(A[fidx[flab == c]].sum()), 1)))
    res['bridge_mm2'] = round(float(A[steep & bridged].sum()), 1)
    res['support_mm2'] = round(float(A[steep & ~bridged].sum()), 1)
    res['longest_bridge_mm'] = max([b['span_mm'] for b in bridges], default=0.0)
    res['bridges'] = sorted(bridges, key=lambda b: -b['span_mm'])[:6]
    # where the supported area is (for the report): the largest patches by height
    if (steep & ~bridged).any():
        zz = np.round(zc[steep & ~bridged]); aa = A[steep & ~bridged]
        u, inv = np.unique(zz, return_inverse=True)
        s = np.bincount(inv, aa)
        top = np.argsort(-s)[:5]
        res['support_by_height'] = [(float(u[i]), round(float(s[i]), 1)) for i in top]
    res['_steep'] = steep & ~bridged       # face masks, for the render (dropped from the report)
    res['_bridged'] = steep & bridged
    return res


def report(res):
    return {k: v for k, v in res.items() if not k.startswith('_')}
