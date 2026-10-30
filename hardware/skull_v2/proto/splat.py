"""Prototype renderer: shaded orthographic views by point splatting into a
z-buffer (numpy only, no OpenSCAD, low RAM). Good enough for seam reviews.

Each layer is (trimesh, rgb) or a point set (pts, rgb, size) drawn on top.
"""
import numpy as np
import trimesh

VIEWS = {   # view direction (camera looks along d), up vector
    'front': (np.array([0, 1, 0.]), np.array([0, 0, 1.])),
    'front_high': (np.array([0, np.cos(np.radians(20)), -np.sin(np.radians(20))]), np.array([0, np.sin(np.radians(20)), np.cos(np.radians(20))])),
    'side': (np.array([-1, 0, 0.]), np.array([0, 0, 1.])),       # from +X (skull's left): face to the right? see basis
    'side_r': (np.array([1, 0, 0.]), np.array([0, 0, 1.])),
    'top': (np.array([0, 0, -1.]), np.array([0, -1, 0.])),
    'bottom': (np.array([0, 0, 1.]), np.array([0, -1, 0.])),
    'back': (np.array([0, -1, 0.]), np.array([0, 0, 1.])),
    'iso': (None, None),
}


def view_dir(az, el):
    """Camera in front of the face, az degrees toward +X, el degrees above; looks at the skull."""
    a, e = np.radians(az), np.radians(el)
    d = -np.array([np.sin(a) * np.cos(e), -np.cos(a) * np.cos(e), np.sin(e)])
    up = np.array([0, 0, 1.]); up = up - d * d.dot(up); up /= np.linalg.norm(up)
    return d, up


def basis(name):
    if isinstance(name, tuple):
        d, up = view_dir(*name)
    elif name == 'iso':
        d = np.array([-0.55, 0.65, -0.35]); d /= np.linalg.norm(d)
        up = np.array([0, 0, 1.]); up = up - d * d.dot(up); up /= np.linalg.norm(up)
    elif name == 'iso_back':
        d = np.array([0.55, -0.65, -0.35]); d /= np.linalg.norm(d)
        up = np.array([0, 0, 1.]); up = up - d * d.dot(up); up /= np.linalg.norm(up)
    elif name == 'iso_below':
        d = np.array([-0.5, 0.6, 0.6]); d /= np.linalg.norm(d)
        up = np.array([0, 0, 1.]); up = up - d * d.dot(up); up /= np.linalg.norm(up)
    else:
        d, up = VIEWS[name]
    right = np.cross(d, up)
    return d, up, right


def sample(mesh, n):
    p, fi = trimesh.sample.sample_surface_even(mesh, n) if False else trimesh.sample.sample_surface(mesh, n)
    return p, mesh.face_normals[fi]


def render(layers, view, px=0.25, bounds=None, light=None, bg=1.0):
    """layers: list of dict(p=points, n=normals or None, c=rgb, s=splat radius px, top=bool).
    Returns an HxWx3 float image and the (u0, v0, px) mapping."""
    d, up, right = basis(view)
    if light is None:
        light = -d + 0.6 * up - 0.3 * right
    light = light / np.linalg.norm(light)
    allp = np.concatenate([L['p'] for L in layers])
    U = allp @ right; V = allp @ up
    if bounds is None:
        bounds = (U.min() - 3, U.max() + 3, V.min() - 3, V.max() + 3)
    u0, u1, v0, v1 = bounds
    W = int((u1 - u0) / px) + 1; H = int((v1 - v0) / px) + 1
    zb = np.full((H, W), np.inf); img = np.full((H, W, 3), bg)
    over = []
    for L in layers:
        p = L['p']; u = ((p @ right) - u0) / px; v = (v1 - (p @ up)) / px; z = p @ d
        if L.get('n') is not None:
            sh = np.clip(L['n'] @ light, 0, 1) * 0.75 + 0.25
            back = (L['n'] @ d) > 0          # back faces (inside surfaces seen through cuts)
            sh = np.where(back, 0.35, sh)
        else:
            sh = np.ones(len(p))
        col = np.asarray(L['c'], float)
        cols = sh[:, None] * col[None, :] if col.ndim == 1 else sh[:, None] * col
        s = L.get('s', 1)
        if L.get('top'):
            over.append((u, v, z, cols, s, L.get('depth_test', True))); continue
        for du in range(-s + 1, s):
            for dv in range(-s + 1, s):
                iu = np.round(u + du).astype(int); iv = np.round(v + dv).astype(int)
                ok = (iu >= 0) & (iu < W) & (iv >= 0) & (iv < H)
                iu, iv, zz, cc = iu[ok], iv[ok], z[ok], cols[ok]
                o = np.argsort(-zz)              # far first, near last wins
                iu, iv, zz, cc = iu[o], iv[o], zz[o], cc[o]
                closer = zz < zb[iv, iu]
                zb[iv[closer], iu[closer]] = zz[closer]
                img[iv[closer], iu[closer]] = cc[closer]
    zsurf = zb.copy()
    for u, v, z, cols, s, dt in over:   # lines: drawn where they are not hidden (1.0 mm tolerance)
        for du in range(-s + 1, s):
            for dv in range(-s + 1, s):
                iu = np.round(u + du).astype(int); iv = np.round(v + dv).astype(int)
                ok = (iu >= 0) & (iu < W) & (iv >= 0) & (iv < H)
                iu, iv, zz, cc = iu[ok], iv[ok], z[ok], cols[ok]
                vis = zz <= zsurf[iv, iu] + 1.0 if dt else np.ones(len(zz), bool)
                img[iv[vis], iu[vis]] = cc[vis]
    return img, (u0, v1, px, right, up, d)


def visible_mask(points, layers, view, px=0.6, tol=1.5):
    """Which of `points` are visible (not hidden by the layers) in `view`.
    Occluders are splatted 3x3 so the sparse sampling leaves no holes."""
    d, up, right = basis(view)
    allp = np.concatenate([L['p'] for L in layers])
    U = allp @ right; V = allp @ up
    u0, v1 = U.min() - 3, V.max() + 3
    W = int((U.max() + 3 - u0) / px) + 1; H = int((v1 - V.min() + 3) / px) + 1
    zb = np.full((H, W), np.inf)
    for L in layers:
        p = L['p']
        for du in (-1, 0, 1):
            for dv in (-1, 0, 1):
                iu = np.round(((p @ right) - u0) / px).astype(int) + du; iv = np.round((v1 - p @ up) / px).astype(int) + dv
                ok = (iu >= 0) & (iu < W) & (iv >= 0) & (iv < H)
                np.minimum.at(zb, (iv[ok], iu[ok]), (p @ d)[ok])
    iu = np.round(((points @ right) - u0) / px).astype(int); iv = np.round((v1 - points @ up) / px).astype(int)
    ok = (iu >= 0) & (iu < W) & (iv >= 0) & (iv < H)
    vis = np.zeros(len(points), bool)
    vis[ok] = (points @ d)[ok] <= zb[iv[ok], iu[ok]] + tol
    return vis
