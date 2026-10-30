"""Prototype layout: v2 chassis, electronics envelopes and the seam plane drawn
over sections of the v1 skull. The box numbers here are the draft of
hardware/skull_v2/interfaces.py (see the Interfaces table in the doc).
Writes docs/skull-v2/layout_sections.png.
"""
import os, sys
import numpy as np
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v1_frame import v1_parts, REPO, HINGE

DOCS = os.path.join(REPO, 'docs', 'skull-v2')
Y_SEAM = 100.0
# name: ((x0, y0, z0), (x1, y1, z1), colour, owner)
ENV = {
    'base plate':        ((-30, 48, -44), (30, 116, -40), 'dimgray', 'chassis'),
    'base front tongue': ((-22, 38, -44), (22, 48, -40), 'dimgray', 'chassis'),
    'spine':             ((-30, 72, -40), (30, 76, 27), 'gray', 'chassis'),
    'front module arm L': ((31, 27, -4), (35, 72, 27), 'slategray', 'chassis'),
    'front module arm R': ((-35, 27, -4), (-31, 72, 27), 'slategray', 'chassis'),
    'brow plate':        ((-35, 10, 23), (35, 30, 27), 'slategray', 'chassis'),
    'locator key':       ((-8, 10, 27), (8, 24, 32), 'slategray', 'chassis'),
    'eye bar':           ((-31.6, 21.2, -10.4), (31.6, 26.85, 10.4), 'gold', 'v1 part'),
    'LCD modules':       ((-37.6, 15.0, -10.1), (37.6, 21.2, 10.1), 'goldenrod', 'hardware'),
    'LCD leads':         ((-28, 26.85, -5), (28, 43, 5), 'orange', 'hardware'),
    'ESP32 + housings':  ((-27.5, 33.4, 5.5), (27.5, 61.4, 25.6), 'tab:green', 'hardware'),
    'USB plug (90 deg)': ((-36, 42, 8), (-27.5, 53, 26), 'tab:olive', 'hardware'),
    'servo':             ((3.6, 59.0, -40.3), (26.3, 71.2, -7.8), 'tab:blue', 'hardware'),
    'servo bracket':     ((1.0, 55.0, -44), (27, 75, -38), 'tab:cyan', 'chassis'),
    'pivot boss':        ((-31.5, 56, -44), (-16, 74, -18), 'tab:cyan', 'chassis'),
    'radar':             ((-17.5, 2.2, -31), (17.5, 6.4, -24), 'tab:red', 'hardware'),
    'stand flange':      ((-28, 76, -50), (28, 104, -44), 'sienna', 'stand'),
}
KNUCKLE = dict(r=9.5, x0=32.0, x1=48.5)


def draw_box(ax, b, axes, c, alpha=0.35, label=None):
    (p0, p1) = np.array(b[0]), np.array(b[1])
    i, j = axes
    ax.add_patch(Rectangle((p0[i], p0[j]), p1[i] - p0[i], p1[j] - p0[j], fc=c, ec=c, alpha=alpha, lw=1.2, label=label))


def section(ax, P, origin, normal, axes):
    for k, m in P.items():
        s = m.section(plane_origin=origin, plane_normal=normal)
        if s is None: continue
        for e in s.discrete:
            ax.plot(e[:, axes[0]], e[:, axes[1]], color='tan' if k == 'jaw' else 'k', lw=0.6)


if __name__ == '__main__':
    P = v1_parts()
    fig, ax = plt.subplots(2, 2, figsize=(20, 18))
    # side, x = 0 and x = 22 (through the LCD leads / servo)
    for a, xs in ((ax[0, 0], 0.0), (ax[0, 1], 24.0)):
        section(a, P, [xs, 0, 0], [1, 0, 0], (1, 2))
        for name, (p0, p1, c, o) in ENV.items():
            if p0[0] <= xs <= p1[0]:
                draw_box(a, (p0, p1), (1, 2), c, label=name)
        a.axvline(Y_SEAM, color='r', lw=2, label='seam plane y = %.0f' % Y_SEAM)
        a.add_patch(Circle((HINGE[0], HINGE[1]), 1.2, color='r'))
        a.annotate('hinge axis', (HINGE[0], HINGE[1]), (HINGE[0] + 8, HINGE[1] - 12), arrowprops=dict(arrowstyle='->'))
        a.set_title('Side section at x = %.0f (y right = toward the back, z up)' % xs, fontsize=13)
        a.set_aspect('equal'); a.grid(alpha=0.3); a.legend(fontsize=8, loc='upper right')
    # top, z = -30 (hinge level) and z = 15 (eye / ESP32 level)
    for a, zs in ((ax[1, 0], -30.0), (ax[1, 1], 15.0)):
        section(a, P, [0, 0, zs], [0, 0, 1], (0, 1))
        for name, (p0, p1, c, o) in ENV.items():
            if p0[2] <= zs <= p1[2]:
                draw_box(a, (p0, p1), (0, 1), c, label=name)
        if abs(zs - HINGE[1]) < KNUCKLE['r']:
            for s in (-1, 1):
                draw_box(a, ((s * KNUCKLE['x0'], HINGE[0] - 9.5, 0), (s * KNUCKLE['x1'], HINGE[0] + 9.5, 0)), (0, 1), 'tan', 0.5,
                         'jaw knuckle' if s > 0 else None)
        a.axhline(Y_SEAM, color='r', lw=2)
        a.set_title('Top section at z = %.0f (x right = skull left, y down = toward the back)' % zs, fontsize=13)
        a.invert_yaxis(); a.set_aspect('equal'); a.grid(alpha=0.3); a.legend(fontsize=8, loc='lower right')
    plt.tight_layout(); plt.savefig(os.path.join(DOCS, 'layout_sections.png'), dpi=50)
