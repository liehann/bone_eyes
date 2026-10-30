"""Which parts of the v1 skull surface can be seen from in front of the face.

Views: straight front (az 0, el 0, the hard rule) plus a margin cone of
az -15..15 and el 0..15 (viewer a little to the side or above, and the
perspective of a viewer about 1 m away). A seam must avoid the red region
(straight front) and should avoid the orange one (margin).

Writes docs/skull-v2/front_visibility.png and proto/cache/front_vis.npz.
"""
import os, sys
import numpy as np
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v1_frame import v1_parts, CACHE, REPO
from splat import sample, render, visible_mask

DOCS = os.path.join(REPO, 'docs', 'skull-v2'); os.makedirs(DOCS, exist_ok=True)


def layers(dens=4.0, parts=('face', 'back', 'cap', 'jaw')):
    P = v1_parts(); L = []
    for k in parts:
        p, n = sample(P[k], int(P[k].area * dens))
        L.append(dict(p=p, n=n, c=(0.93, 0.9, 0.82), s=2, name=k))
    return L


def compute():
    fn = os.path.join(CACHE, 'front_vis.npz')
    if os.path.exists(fn):
        z = np.load(fn); return z['p'], z['n'], z['straight'], z['margin']
    L = layers()
    p = np.concatenate([l['p'] for l in L[:3]]); n = np.concatenate([l['n'] for l in L[:3]])
    straight = visible_mask(p, L, (0, 0))
    margin = straight.copy()
    for az in (-15, -7, 7, 15):
        for el in (0, 7, 15):
            margin |= visible_mask(p, L, (az, el))
    for el in (7, 15):
        margin |= visible_mask(p, L, (0, el))
    np.savez_compressed(fn, p=p, n=n, straight=straight, margin=margin)
    return p, n, straight, margin


if __name__ == '__main__':
    p, n, s, m = compute()
    c = np.tile([0.93, 0.9, 0.82], (len(p), 1))
    c[m] = (1.0, 0.65, 0.3); c[s] = (0.9, 0.2, 0.2)
    L = [dict(p=p, n=n, c=c, s=2)]
    fig, ax = plt.subplots(1, 4, figsize=(24, 7))
    for a, v in zip(ax, ['side', 'top', 'back', 'bottom']):
        img, (u0, v1, px, *_) = render(L, v, px=0.35)
        H, W = img.shape[:2]
        a.imshow(img, extent=(u0, u0 + W * px, v1 - H * px, v1)); a.set_title(v); a.grid(alpha=0.3)
    fig.suptitle('Red: seen straight from the front. Orange: seen from up to 15 deg to the side or above.')
    plt.tight_layout(); plt.savefig(os.path.join(DOCS, 'front_visibility.png'), dpi=55)
    # rearmost visible y per height band (where a seam may start)
    for zc in range(-60, 100, 10):
        k = (abs(p[:, 2] - zc) < 5)
        print('z %4d: straight max y %.1f  margin max y %.1f' % (zc, p[k & s, 1].max() if (k & s).any() else np.nan,
                                                              p[k & m, 1].max() if (k & m).any() else np.nan))
