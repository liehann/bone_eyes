"""Rough volumes for the two shells, printed rim-down on the seam plane, with a
self-supporting interior: every ceiling inside the shell is >= 40 deg from
horizontal, so the shell prints with no support. Where the head is too wide
for a 40 deg tent, the space between the skin and the tent is solid model
(the slicer fills it with sparse infill).

Voxels at 2 mm. The cavity is the largest self-supporting space inside the
skin (swept from the top layer down: C(z) = A(z) & dilate(C(z+1))), plus
the keep-outs that the chassis needs, swept along the insertion axis (Y).
Numbers are estimates for the architecture doc, not build geometry.
"""
import os, sys
import numpy as np
from scipy import ndimage
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v1_frame import v1_parts
from splat import sample

H = 2.0
Y_SEAM = 100.0
SKIN = 1            # voxels (2 mm; the real skin is 2.6 mm)
LO = np.array([-72.0, -32.0, -66.0]); HI = np.array([72.0, 160.0, 102.0])


def grid():
    P = v1_parts()
    pts = np.concatenate([sample(P[k], int(P[k].area * 6))[0] for k in ('face', 'back', 'cap')])
    shape = tuple(np.ceil((HI - LO) / H).astype(int) + 1)
    occ = np.zeros(shape, bool)
    i = np.round((pts - LO) / H).astype(int)
    occ[i[:, 0], i[:, 1], i[:, 2]] = True
    X, Y, Z = np.meshgrid(*[LO[k] + np.arange(shape[k]) * H for k in range(3)], indexing='ij')
    # plugs: eye apertures (screens), neck bore
    for xe in (-27.25, 27.25):
        occ |= (abs(Y - 15.0) < 1.5) & ((X - xe) ** 2 + Z ** 2 < 12.0 ** 2)
    occ |= (abs(Z + 40.0) < 1.5) & (X ** 2 + (Y - 90.0) ** 2 < 10.0 ** 2)
    occ = ndimage.binary_dilation(occ, iterations=int(os.environ.get("DIL", 3)))
    lab, _ = ndimage.label(~occ)
    outside = lab == lab[0, 0, 0]
    inside = ndimage.binary_erosion(~outside, iterations=1) | (~outside & ~occ)
    print("probe inside:", inside[tuple(np.round((np.array([0, 75, 40.]) - LO) / H).astype(int))])
    return inside, X, Y, Z


def tent(A, axis_up):
    """Largest self-supporting cavity inside A, built from the top layer down.
    axis_up: +1 if print-up is +Y, -1 if print-up is -Y."""
    C = np.zeros_like(A)
    n = A.shape[1]
    order = range(n - 1, -1, -1) if axis_up > 0 else range(n)
    prev = None
    st = np.ones((3, 3), bool)   # one voxel (2 mm) per 2 mm layer ~ 45 deg; close to the 40 deg rule
    for j in order:
        a = A[:, j, :]
        C[:, j, :] = a if prev is None else (a & ndimage.binary_dilation(prev, st))
        prev = C[:, j, :]
    return C


def report(name, region, keep, inside, axis_up):
    solid = inside & region
    A = ndimage.binary_erosion(inside, iterations=SKIN) & region
    skin = solid & ~A
    C = tent(A, axis_up) | (keep & A)
    fill = A & ~C
    v = lambda m: m.sum() * H ** 3 / 1000.0
    print('%-8s enclosed %6.0f cm3 | skin %5.0f cm3 | cavity %6.0f cm3 | solid fill %5.0f cm3 (%.0f %% of enclosed)'
          % (name, v(solid), v(skin), v(C), v(fill), 100 * v(fill) / max(v(solid), 1)))
    return dict(enclosed=v(solid), skin=v(skin), cavity=v(C), fill=v(fill))


if __name__ == '__main__':
    inside, X, Y, Z = grid()
    bay = (abs(X) < 50) & (Y > 48) & (Z < -19)
    face = (Y < Y_SEAM) & ~bay
    cran = Y >= Y_SEAM
    # chassis keep-outs inside the face shell, swept back along +Y to the seam (insertion axis)
    keep = np.zeros_like(inside)
    keep |= (abs(X) <= 37) & (Y >= 8) & (Z > -9) & (Z < 34)          # front module, ESP32, bar, LCD leads
    keep |= (abs(X) <= 33) & (Y >= 14) & (Z > -12) & (Z < 23)        # eye bar + modules
    keep |= (abs(X) <= 20) & (Y >= 2) & (Z > -33) & (Z < -22)        # radar pocket + its lead
    keep |= (abs(X) <= 36) & (Y >= 40) & (Z > -46) & (Z < 30)        # spine, servo, USB, cable runs
    keep |= (abs(X) <= 8) & (Y >= 2) & (Z > 20) & (Z < 34)           # locator key socket
    r1 = report('face', face, keep & face, inside, axis_up=-1)
    r2 = report('cranium', cran, (abs(X) <= 36) & (Z < 30) & cran, inside, axis_up=+1)
    import json
    json.dump(dict(face=r1, cranium=r2), open(os.path.join(os.path.dirname(__file__), 'cache', 'fill.json'), 'w'), indent=1)
