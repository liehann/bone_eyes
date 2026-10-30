"""Prototype: put the v1 STLs (which are exported in print pose) back into the
v1 eye frame, so v2 seams and envelopes can be drawn on the v1 skull surface.

Eye frame (v1 build.py): origin midway between the orbits, -Y is the face
direction, +Z up. Source -> eye: p_eye = (p_src - ORIGIN_SRC) * SCALE.

The v1 parts are only translated (and the cap tilted by the seam angle) into
print pose, so each one is recovered with a translation-only trimmed ICP
against the scaled source cranium. Results are cached in proto/cache/.
Light: no voxels, no booleans.
"""
import os, json
import numpy as np
import trimesh
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
V1 = os.path.join(REPO, 'hardware', 'skull')
V1_OUT = os.path.join(V1, 'out')
CACHE = os.path.join(HERE, 'cache'); os.makedirs(CACHE, exist_ok=True)

_r = json.load(open(os.path.join(V1_OUT, 'build_report.json')))['info']
SCALE = _r['scale']
ORIGIN_SRC = np.array(_r['origin_src'])
HINGE = np.array(_r['hinge'])            # (y, z) of the condyle axis, parallel to X
SEAM_A = np.degrees(np.arctan2(0.04, 0.9992))


def rx(deg):
    a = np.radians(deg); c, s = np.cos(a), np.sin(a)
    M = np.eye(4); M[1:3, 1:3] = [[c, -s], [s, c]]
    return M


def to_eye(m):
    m = m.copy(); m.apply_translation(-ORIGIN_SRC); m.apply_scale(SCALE); return m


def cranium():
    fn = os.path.join(CACHE, 'cranium_eye.stl')
    if not os.path.exists(fn):
        to_eye(trimesh.load(os.path.join(V1, 'cache', 'cranium_src.stl'))).export(fn)
    return trimesh.load(fn)


def jaw_src():
    fn = os.path.join(CACHE, 'jaw_src_eye.stl')
    if not os.path.exists(fn):
        to_eye(trimesh.load(os.path.join(V1, 'cache', 'jaw_src.stl'))).export(fn)
    return trimesh.load(fn)


def _fit_t(P, tree, t0, iters=40, keep=0.6):
    t = np.array(t0, float)
    for _ in range(iters):
        d, i = tree.query(P + t)
        k = d < np.quantile(d, keep)
        dt = (tree.data[i[k]] - (P[k] + t)).mean(0)
        t += dt
        if np.linalg.norm(dt) < 1e-3:
            break
    d, _ = tree.query(P + t)
    return t, float(np.median(d))


def v1_parts():
    """dict name -> trimesh in the eye frame (face, back, cap, jaw)."""
    fn = os.path.join(CACHE, 'v1_fit.json')
    cr = cranium()
    out = {}
    fits = json.load(open(fn)) if os.path.exists(fn) else {}
    tree = None
    for name in ('face', 'back', 'cap', 'jaw'):
        m = trimesh.load(os.path.join(V1_OUT, name + '.stl'))
        if name == 'cap':
            m.apply_transform(rx(-SEAM_A))
        if name not in fits:
            if name == 'jaw':
                ref = jaw_src(); best = None
                for a in np.arange(-14, 14.1, 1.0):
                    J = ref.copy()
                    T = np.eye(4); T[1:3, 3] = HINGE
                    J.apply_transform(T @ rx(a) @ np.linalg.inv(T))
                    jt = cKDTree(J.sample(30000))
                    P = m.sample(6000)
                    t0 = J.bounds.mean(0) - m.bounds.mean(0)
                    t, err = _fit_t(P, jt, t0)
                    if best is None or err < best[2]:
                        best = (a, t, err)
                fits[name] = dict(t=best[1].tolist(), err=best[2], jaw_rot=float(best[0]))
            else:
                if tree is None:
                    tree = cKDTree(cr.sample(200000))
                b = cr.bounds
                guess = dict(face=(0, -28 - m.bounds[0, 1], -58 - m.bounds[0, 2]),
                             back=(0, b[1, 1] - m.bounds[1, 1], -14 - m.bounds[0, 2]),
                             cap=(0, b[0, 1] - m.bounds[0, 1] + 5, b[1, 2] - m.bounds[1, 2]))[name]
                t, err = _fit_t(m.sample(8000), tree, guess)
                fits[name] = dict(t=t.tolist(), err=err)
            json.dump(fits, open(fn, 'w'), indent=1)
        m.apply_translation(fits[name]['t'])
        out[name] = m
    return out


if __name__ == '__main__':
    P = v1_parts()
    print(json.load(open(os.path.join(CACHE, 'v1_fit.json'))))
    for k, m in P.items():
        print(k, m.bounds.round(1).tolist())
    print('cranium', cranium().bounds.round(1).tolist())
