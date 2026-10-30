"""Rough check: the face shell slides on along +Y (backward) over the fitted
jaw. Relative to the shell the jaw then sweeps from behind (P1) to its place,
so the shell must be empty at (x, z) for every y >= the jaw's front-most y at
that (x, z). This lists the v1 face-shell surface that sits in that sweep.

The face-shell region here: v1 surface with y < Y_SEAM, minus the bottom bay
the chassis base plate fills (|x| < BAY_X, y > BAY_Y0, z < BAY_Z).
"""
import os, sys
import numpy as np
from scipy.spatial import cKDTree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v1_frame import v1_parts
from splat import sample

Y_SEAM, BAY_X, BAY_Y0, BAY_Z = 100.0, 50.0, 48.0, -19.0
G = 1.0   # (x, z) grid for the sweep


def jaw_front_map(jaw_pts):
    k = np.round(jaw_pts[:, [0, 2]] / G).astype(int)
    d = {}
    for (i, j), y in zip(map(tuple, k), jaw_pts[:, 1]):
        if y < d.get((i, j), np.inf):
            d[(i, j)] = y
    return d


if __name__ == '__main__':
    P = v1_parts()
    jp, _ = sample(P['jaw'], 400000)
    front = jaw_front_map(jp)
    pts = np.concatenate([sample(P[k], int(P[k].area * 3))[0] for k in ('face', 'back', 'cap')])
    shell = pts[(pts[:, 1] < Y_SEAM) & ~((abs(pts[:, 0]) < BAY_X) & (pts[:, 1] > BAY_Y0) & (pts[:, 2] < BAY_Z))]
    k = np.round(shell[:, [0, 2]] / G).astype(int)
    yj = np.array([front.get(tuple(t), np.inf) for t in k])
    hit = shell[shell[:, 1] >= yj - 1.0]
    print('jaw z max %.1f; jaw points %d' % (jp[:, 2].max(), len(jp)))
    print('face-shell surface points in the jaw sweep: %d' % len(hit))
    if len(hit):
        for name, m in [('coronoid region (y<50)', hit[:, 1] < 50), ('hinge region (y>=50)', hit[:, 1] >= 50)]:
            h = hit[m]
            if len(h):
                print(' %s: %d pts, x %.1f..%.1f  y %.1f..%.1f  z %.1f..%.1f' % (name, len(h), *np.c_[h.min(0), h.max(0)].ravel()))
        np.save(os.path.join(os.path.dirname(__file__), 'cache', 'slide_hits.npy'), hit)
    # coronoid tips
    c = jp[(jp[:, 1] < 50) & (abs(jp[:, 0]) > 25)]
    for s in (-1, 1):
        cc = c[np.sign(c[:, 0]) == s]; i = np.argmax(cc[:, 2])
        print('coronoid tip side %+d: %s' % (s, cc[i].round(1)))
    kn = jp[jp[:, 1] >= 50]; i = np.argmax(kn[:, 2]); print('highest jaw point behind y=50:', kn[i].round(1))
    print('jaw |x| max %.1f at y %.1f' % (abs(jp[:, 0]).max(), jp[np.argmax(abs(jp[:, 0])), 1]))
