"""Numpy z-buffer line-art renderer (IKEA-style): face-ID, depth and normal
buffers -> black lines where the part changes, depth jumps or creases > ~30 deg.

    img, cam = render(parts, view, styles)
    cam.project(points) -> pixel (x, y) in the returned image
"""
import numpy as np
from scipy import ndimage
from PIL import Image


def basis(az, el):
    """Camera looking at the origin from azimuth az (deg, 0 = from the front, i.e. from -Y,
    90 = from +X) and elevation el (deg, up). Returns right, up, d (view direction)."""
    a, e = np.radians(az), np.radians(el)
    eye = np.array([np.sin(a) * np.cos(e), -np.cos(a) * np.cos(e), np.sin(e)])   # camera position direction
    d = -eye
    right = np.cross(d, [0, 0, 1.0]); right /= np.linalg.norm(right)
    up = np.cross(right, d)
    return right, up, d


class Cam:
    def __init__(self, right, up, d, x0, y1, s, W, H):
        self.r, self.u, self.d, self.x0, self.y1, self.s, self.W, self.H = right, up, d, x0, y1, s, W, H

    def project(self, P):
        P = np.atleast_2d(np.asarray(P, float))
        return np.c_[(P @ self.r - self.x0) / self.s, (self.y1 - P @ self.u) / self.s]

    def mm(self, length):
        return length / self.s


def raster(V2, Z, F, W, H, fid0, depth, ids, tri_id_buf):
    """Rasterise triangles F (n,3) with screen coords V2 (pixels) and depth Z into the buffers."""
    if len(F) == 0:
        return
    A, B, C = V2[F[:, 0]], V2[F[:, 1]], V2[F[:, 2]]
    za, zb, zc = Z[F[:, 0]], Z[F[:, 1]], Z[F[:, 2]]
    mn = np.floor(np.minimum(np.minimum(A, B), C) - 0.5).astype(int)
    mx = np.ceil(np.maximum(np.maximum(A, B), C) - 0.5).astype(int)
    mn = np.maximum(mn, 0); mx = np.minimum(mx, [W - 1, H - 1])
    ok = (mx >= mn).all(1)
    area = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (B[:, 1] - A[:, 1]) * (C[:, 0] - A[:, 0])
    ok &= np.abs(area) > 1e-9
    ext = (mx - mn + 1).max(1)
    idx_all = np.nonzero(ok)[0]
    for K in (1, 2, 4, 8, 16, 32, 64, 128, 256, 100000):
        sel = idx_all[(ext[idx_all] <= K)]
        idx_all = idx_all[ext[idx_all] > K]
        if len(sel) == 0:
            continue
        if K > 256:
            for t in sel:      # rare huge triangles: one at a time
                _tri(t, A, B, C, za, zb, zc, area, mn, mx, W, fid0, depth, ids, tri_id_buf)
            continue
        chunk = max(1, 4_000_000 // (K * K))
        g = np.arange(K)
        for c0 in range(0, len(sel), chunk):
            t = sel[c0:c0 + chunk]
            px = (mn[t, 0][:, None, None] + g[None, None, :]) + np.zeros((1, K, 1), int)
            py = (mn[t, 1][:, None, None] + g[None, :, None]) + np.zeros((1, 1, K), int)
            valid = (px <= mx[t, 0][:, None, None]) & (py <= mx[t, 1][:, None, None])
            _resolve(t, px, py, valid, A, B, C, za, zb, zc, area, W, fid0, depth, ids, tri_id_buf)


def _tri(t, A, B, C, za, zb, zc, area, mn, mx, W, fid0, depth, ids, tri_id_buf):
    xs = np.arange(mn[t, 0], mx[t, 0] + 1); ys = np.arange(mn[t, 1], mx[t, 1] + 1)
    px, py = np.meshgrid(xs, ys)
    _resolve(np.array([t]), px[None], py[None], np.ones((1,) + px.shape, bool),
             A, B, C, za, zb, zc, area, W, fid0, depth, ids, tri_id_buf)


def _resolve(t, px, py, valid, A, B, C, za, zb, zc, area, W, fid0, depth, ids, tri_id_buf):
    sh = (-1,) + (1,) * (px.ndim - 1)
    cx, cy = px + 0.5, py + 0.5
    ax, ay = A[t, 0].reshape(sh), A[t, 1].reshape(sh)
    bx, by = B[t, 0].reshape(sh), B[t, 1].reshape(sh)
    qx, qy = C[t, 0].reshape(sh), C[t, 1].reshape(sh)
    ar = area[t].reshape(sh)
    w0 = ((bx - cx) * (qy - cy) - (by - cy) * (qx - cx)) / ar
    w1 = ((qx - cx) * (ay - cy) - (qy - cy) * (ax - cx)) / ar
    w2 = 1.0 - w0 - w1
    eps = -1e-6
    inside = valid & (w0 >= eps) & (w1 >= eps) & (w2 >= eps)
    z = w0 * za[t].reshape(sh) + w1 * zb[t].reshape(sh) + w2 * zc[t].reshape(sh)
    tt = np.broadcast_to(t.reshape(sh), px.shape)
    pix = (py * W + px)[inside]; z = z[inside]; tt = tt[inside]
    if len(pix) == 0:
        return
    o = np.lexsort((z, pix))
    pix, z, tt = pix[o], z[o], tt[o]
    first = np.r_[True, pix[1:] != pix[:-1]]
    pix, z, tt = pix[first], z[first], tt[first]
    better = z < depth[pix]
    pix, z, tt = pix[better], z[better], tt[better]
    depth[pix] = z
    tri_id_buf[pix] = tt + fid0


def render(parts, az, el, s=0.06, pad=4.0, bounds2d=None, ss=2, styles=None, crease_deg=32.0,
           depth_jump=1.2, widths=None, fills=None):
    """parts: list of (name, trimesh). styles: name -> 'hi' | 'norm' | 'ghost'.
    s: mm per final pixel. Returns (RGBA uint8 image, Cam in final pixels)."""
    styles = styles or {}
    right, up, d = basis(az, el)
    s_r = s / ss
    allV = np.vstack([m.vertices for _, m in parts])
    X, Y = allV @ right, allV @ up
    if bounds2d is None:
        bounds2d = (X.min() - pad, X.max() + pad, Y.min() - pad, Y.max() + pad)
    x0, x1, y0, y1 = bounds2d
    W = int(np.ceil((x1 - x0) / s_r)); H = int(np.ceil((y1 - y0) / s_r))
    depth = np.full(W * H, np.inf); tbuf = np.full(W * H, -1, np.int64)
    normals, part_of_tri = [], []
    fid0 = 0
    for k, (name, m) in enumerate(parts):
        V = np.asarray(m.vertices); F = np.asarray(m.faces); N = np.asarray(m.face_normals)
        front = (N @ d) < 1e-6
        V2 = np.c_[(V @ right - x0) / s_r, (y1 - V @ up) / s_r]
        Z = V @ d
        idx = np.nonzero(front)[0]     # rasterise front faces only; keep ids aligned with N
        sub_t = np.full(W * H, -1, np.int64)
        raster(V2, Z, F[idx], W, H, 0, depth, None, sub_t)
        hit = sub_t >= 0
        tbuf[hit] = fid0 + idx[sub_t[hit]]
        normals.append(N); part_of_tri.append(np.full(len(F), k))
        fid0 += len(F)
    normals = np.vstack(normals); part_of_tri = np.concatenate(part_of_tri)
    tb = tbuf.reshape(H, W); dep = depth.reshape(H, W)
    bg = tb < 0
    pid = np.where(bg, -1, part_of_tri[np.maximum(tb, 0)])
    nrm = normals[np.maximum(tb, 0)]
    nrm[bg] = 0
    edge_owner = np.full((H, W), -1, int)
    cosc = np.cos(np.radians(crease_deg))
    for axis in (0, 1):
        sl_a = (slice(None, -1), slice(None)) if axis == 0 else (slice(None), slice(None, -1))
        sl_b = (slice(1, None), slice(None)) if axis == 0 else (slice(None), slice(1, None))
        pa, pb = pid[sl_a], pid[sl_b]; da, db = dep[sl_a], dep[sl_b]
        na, nb = nrm[sl_a], nrm[sl_b]
        both = (pa >= 0) & (pb >= 0)
        e = (pa != pb)
        dd = np.abs(np.where(both, da - db, 0))
        e |= both & (dd > depth_jump)
        e |= both & ((na * nb).sum(-1) < cosc)
        # owner = nearer pixel
        a_near = (da <= db) | (pb < 0)
        own = np.where(a_near & (pa >= 0), pa, pb)
        own = np.where(pa < 0, pb, own)
        tgt_a = e & a_near & (pa >= 0)
        tgt_b = e & ~tgt_a
        ea = edge_owner[sl_a]; eb = edge_owner[sl_b]
        ea[tgt_a] = own[tgt_a]
        eb[tgt_b] = own[tgt_b]
    # compose
    names = [n for n, _ in parts]
    st = np.array([{'hi': 2, 'norm': 1, 'ghost': 0, 'faint': 3}.get(styles.get(n, 'norm'), 1) for n in names] + [1])
    widths = widths or {0: 1, 1: 2, 2: 4, 3: 1}
    fills = fills or {0: 255, 1: 255, 2: 232, 3: 255}
    lcol = {0: 150, 1: 0, 2: 0, 3: 200}
    img = np.full((H, W), 255, np.uint8)
    alpha = np.where(bg, 0, 255).astype(np.uint8)
    for k in range(len(names)):
        img[pid == k] = fills[st[k]]
    for level in (3, 0, 1, 2):
        ks = [k for k in range(len(names)) if st[k] == level]
        if not ks:
            continue
        m = np.isin(edge_owner, ks)
        w = widths[level] * ss / 2.0
        if w > 0.75:
            r = int(round(w))
            yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
            m = ndimage.binary_dilation(m, structure=(xx ** 2 + yy ** 2) <= (w + 0.25) ** 2)
        img[m] = np.minimum(img[m], lcol[level]); alpha[m] = 255
    rgba = np.dstack([img, img, img, alpha])
    im = Image.fromarray(rgba, 'RGBA')
    if ss > 1:
        im = im.resize((W // ss, H // ss), Image.LANCZOS)
    cam = Cam(right, up, d, x0, y1, s, W // ss, H // ss)
    return np.asarray(im), cam
