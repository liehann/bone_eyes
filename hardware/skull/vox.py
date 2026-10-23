"""Voxel helpers: rasterise a manifold3d solid into a boolean grid via Z slices."""
import numpy as np
import manifold3d as mf


def raster_slice(polys, x0, y0, h, nx, ny):
    """Nonzero-winding fill of polygons onto grid points (x0+i*h, y0+j*h)."""
    xa, ya, xb, yb = [], [], [], []
    for p in polys:
        p = np.asarray(p)
        if len(p) < 3:
            continue
        q = np.roll(p, -1, axis=0)
        xa.append(p[:, 0]); ya.append(p[:, 1]); xb.append(q[:, 0]); yb.append(q[:, 1])
    out = np.zeros((nx, ny), bool)
    if not xa:
        return out
    xa, ya, xb, yb = map(np.concatenate, (xa, ya, xb, yb))
    keep = ya != yb
    xa, ya, xb, yb = xa[keep], ya[keep], xb[keep], yb[keep]
    d = np.where(yb > ya, 1, -1)
    lo = np.minimum(ya, yb); hi = np.maximum(ya, yb)
    j0 = np.ceil((lo - y0) / h).astype(int)
    j1 = np.ceil((hi - y0) / h).astype(int)  # rows j with lo <= yj < hi
    j0 = np.clip(j0, 0, ny); j1 = np.clip(j1, 0, ny)
    cnt = j1 - j0
    m = cnt > 0
    if not m.any():
        return out
    xa, ya, xb, yb, d, j0, cnt = xa[m], ya[m], xb[m], yb[m], d[m], j0[m], cnt[m]
    e = np.repeat(np.arange(len(cnt)), cnt)
    off = np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    j = j0[e] + off
    yc = y0 + j * h
    t = (yc - ya[e]) / (yb[e] - ya[e])
    xc = xa[e] + t * (xb[e] - xa[e])
    i = np.clip(np.ceil((xc - x0) / h).astype(int), 0, nx)
    diff = np.zeros((ny, nx + 1), np.int32)
    np.add.at(diff, (j, i), d[e])
    wind = np.cumsum(diff, axis=1)[:, :nx]
    return (wind != 0).T


def voxelize(man, origin, h, shape):
    nx, ny, nz = shape
    g = np.zeros(shape, bool)
    for k in range(nz):
        z = origin[2] + k * h
        cs = man.slice(z)
        if cs.is_empty():
            continue
        g[:, :, k] = raster_slice(cs.to_polygons(), origin[0], origin[1], h, nx, ny)
    return g
