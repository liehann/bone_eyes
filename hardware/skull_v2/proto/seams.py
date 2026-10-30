"""Prototype: the v2 seam lines drawn on the v1 skull surface.

v2 split (see docs/skull-v2-architecture.md):
- face shell:    everything in front of the seam plane y = Y_SEAM, except the
                 bottom bay over the hinge, servo and neck;
- cranium shell: everything behind y = Y_SEAM (back, top-back, base behind the neck);
- chassis base:  the flat plate that closes the bottom bay (seen from below only);
- liners (black) and jaw as in v1.

Checks every seam point against the straight front view and a margin cone
(az +-15, el 0..15) and writes the renders to docs/skull-v2/.
"""
import os, sys
import numpy as np
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v1_frame import v1_parts, REPO
from splat import sample, render, visible_mask

DOCS = os.path.join(REPO, 'docs', 'skull-v2')
Y_SEAM = float(os.environ.get('Y_SEAM', 100.0))
BAY = dict(x=50.0, y0=48.0, z=-19.0)          # bottom bay (chassis base plate below it)
COL = dict(face=(0.94, 0.91, 0.82), cranium=(0.72, 0.82, 0.95), base=(0.6, 0.6, 0.62),
           jaw=(0.9, 0.78, 0.66), liner=(0.12, 0.12, 0.12))
EYES = [(-27.0, -2.0, 15.5, 18.5), (27.25, -2.0, 15.75, 18.5)]   # x, z, half breadth, half height (v1 report)


def classify(p):
    lab = np.full(len(p), 'face', dtype=object)
    bay = (abs(p[:, 0]) < BAY['x']) & (p[:, 1] > BAY['y0']) & (p[:, 2] < BAY['z']) & (p[:, 1] < Y_SEAM)
    lab[bay] = 'base'
    lab[p[:, 1] >= Y_SEAM] = 'cranium'
    for x, z, a, b in EYES:   # socket bowls -> liners
        m = (((p[:, 0] - x) / a) ** 2 + ((p[:, 2] - z) / b) ** 2 < 1.0) & (p[:, 1] > 1.5) & (p[:, 1] < 16)
        lab[m] = 'liner'
    nose = (abs(p[:, 0]) < 13) & (p[:, 2] > -42) & (p[:, 2] < -12) & (p[:, 1] > -3) & (p[:, 1] < 8)
    lab[nose] = 'liner'
    return lab


def build_layers(dens=8.0):
    P = v1_parts()
    ps, ns = [], []
    for k in ('face', 'back', 'cap'):
        a, b = sample(P[k], int(P[k].area * dens))
        zc = 32.0 - 0.04 * (a[:, 1] + 5.0)
        cut = ((abs(a[:, 2] - zc) < 1.2) & (abs(b[:, 2]) > 0.9)) | ((abs(a[:, 1] - 32.0) < 0.6) & (abs(b[:, 1]) > 0.9)) | \
              ((abs(a[:, 2] + 14.0) < 0.6) & (abs(b[:, 2]) > 0.9) & (a[:, 1] > 31))
        ps.append(a[~cut]); ns.append(b[~cut])   # drop v1's own cut faces
    # fill the hairline gaps at the v1 cuts (cap plane, back cut, floor cut) with the source surface
    from v1_frame import cranium
    cp, cn = sample(cranium(), 1500000)
    zc = 32.0 - 0.04 * (cp[:, 1] + 5.0)
    near = (abs(cp[:, 2] - zc) < 1.5) | ((abs(cp[:, 1] - 32.0) < 1.5) & (cp[:, 2] < zc) & (cp[:, 2] > -15)) | \
           ((abs(cp[:, 2] + 14.0) < 1.5) & (cp[:, 1] > 32.0))
    ps.append(cp[near]); ns.append(cn[near])
    p, n = np.concatenate(ps), np.concatenate(ns)
    lab = classify(p)
    c = np.array([COL[l] for l in lab])
    jp, jn = sample(P['jaw'], int(P['jaw'].area * dens))
    return p, n, lab, c, jp, jn


def seam_points(p, n, lab):
    """Outer-surface points on the seams: plane y = Y_SEAM, and the bay edge."""
    s1 = (abs(p[:, 1] - Y_SEAM) < 0.5) & (p[:, 2] > -36)
    bayedge = ((abs(abs(p[:, 0]) - BAY['x']) < 0.6) & (p[:, 1] > BAY['y0']) & (p[:, 1] < Y_SEAM) & (p[:, 2] < BAY['z'])) | \
              ((abs(p[:, 1] - BAY['y0']) < 0.5) & (abs(p[:, 0]) < BAY['x']) & (p[:, 2] < BAY['z']))
    bayedge &= n[:, 2] < -0.2          # the bay edge is on the underside
    return s1, bayedge


if __name__ == '__main__':
    p, n, lab, c, jp, jn = build_layers()
    s1, s2 = seam_points(p, n, lab)
    plug = []   # eye apertures are closed by the LCDs in the real build
    for x, z, _, _ in EYES:
        t = np.random.default_rng(0).uniform(-1, 1, (4000, 2)); t = t[(t ** 2).sum(1) < 1] * 11
        plug.append(np.c_[x + t[:, 0], np.full(len(t), 15.0), z + 2 + t[:, 1]])
    plug = np.concatenate(plug)
    occl = [dict(p=p), dict(p=jp), dict(p=plug)]
    seam = np.concatenate([p[s1], p[s2]])
    vis_straight = visible_mask(seam, occl, (0, 0))
    vis_margin = vis_straight.copy()
    for az in (-15, 0, 15):
        for el in (0, 8, 15):
            vis_margin |= visible_mask(seam, occl, (az, el))
    # only count outward-facing seam points (inner surfaces seen through cuts do not matter)
    print('Y_SEAM %.0f: seam points %d, visible straight-front %d, visible in margin cone %d'
          % (Y_SEAM, len(seam), vis_straight.sum(), vis_margin.sum()))
    if vis_margin.any():
        v = seam[vis_margin]
        print('  visible (margin) seam points: y %.1f..%.1f z %.1f..%.1f |x| %.1f..%.1f'
              % (v[:, 1].min(), v[:, 1].max(), v[:, 2].min(), v[:, 2].max(), abs(v[:, 0]).min(), abs(v[:, 0]).max()))
    if os.environ.get('NORENDER'):
        sys.exit()
    red = (0.85, 0.1, 0.1)
    L = [dict(p=p, n=n, c=c, s=2), dict(p=jp, n=jn, c=COL['jaw'], s=2),
         dict(p=plug, n=np.tile([0, -1.0, 0], (len(plug), 1)), c=(0.05, 0.05, 0.1), s=2),
         dict(p=p[s1], c=red, s=2, top=True), dict(p=p[s2], c=(1.0, 0.55, 0.0), s=2, top=True)]
    views = [('front', 'Front (straight on): no seam visible'), ('side', 'Side (from the skull\'s left, +X)'),
             ('top', 'Top'), ('back', 'Back'), ('bottom', 'Bottom'), ('iso', '3/4 front')]
    fig, ax = plt.subplots(2, 3, figsize=(21, 14))
    for a, (v, t) in zip(ax.flat, views):
        img, (u0, v1, px, *_) = render(L, v, px=0.3)
        H, W = img.shape[:2]
        a.imshow(img, extent=(u0, u0 + W * px, v1 - H * px, v1)); a.set_title(t, fontsize=14); a.grid(alpha=0.25)
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color=COL[k], label=l) for k, l in [('face', 'face shell'), ('cranium', 'cranium shell'),
               ('base', 'chassis base (flat plate in v2)'), ('jaw', 'jaw'), ('liner', 'liners (black)')]] +
               [Patch(color=red, label='face/cranium seam'), Patch(color=(1.0, 0.55, 0.0), label='hinge bay edge (underside)')], loc='lower center', ncol=7, fontsize=13)
    fig.suptitle('v2 seams on the v1 skull surface (seam plane y = %.0f mm)' % Y_SEAM, fontsize=16)
    plt.tight_layout(rect=(0, 0.04, 1, 0.97))
    plt.savefig(os.path.join(DOCS, 'seams_views.png'), dpi=55)
    # big front view on its own
    img, (u0, v1, px, *_) = render(L, 'front', px=0.2)
    H, W = img.shape[:2]
    plt.figure(figsize=(9, 10)); plt.imshow(img, extent=(u0, u0 + W * px, v1 - H * px, v1))
    plt.title('Front view, straight on. Seams drawn in red where they would show: none do.\nOrange dots by the condyles: hinge-bay edge (an opening, as in v1).')
    plt.grid(alpha=0.2); plt.tight_layout(); plt.savefig(os.path.join(DOCS, 'seams_front.png'), dpi=70)
