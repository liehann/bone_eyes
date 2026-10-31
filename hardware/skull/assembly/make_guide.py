"""IKEA-style printable assembly guide for the skull -> hardware/skull/assembly_guide.pdf

Line art is rasterised here from the assembled meshes (lineart.py: numpy z-buffer,
part / depth / crease edges); matplotlib composes the US Letter pages and draws
the screws, callouts and arrows as vectors.

    hardware/.venv/bin/python hardware/skull/assembly/make_guide.py [--pngs DIR]
"""
import os, sys, hashlib, pickle
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Polygon, FancyArrowPatch, Circle, Rectangle, FancyBboxPatch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scene, lineart   # noqa: E402

SK = scene.SK
PDF = os.path.join(SK, 'assembly_guide.pdf')
RCACHE = os.path.join(scene.CACHE, 'renders'); os.makedirs(RCACHE, exist_ok=True)
PW, PH = 8.5, 11.0          # US Letter, inches
M = 0.5                     # print margin
MM = 25.4
P = scene.load_parts()
FA = {**scene.fasteners(), **scene.cover_fasteners(P)}
INS = scene.inserts(P)
LW = 1.4                    # vector line weight (pt)
FONT = 'DejaVu Sans'
plt.rcParams.update({'font.family': FONT, 'font.size': 11})


# ------------------------------------------------------------------ rendering
def view(parts, az, el, styles=None, off=None, s=0.10, pad=6.0, bounds_extra=()):
    """parts: names; off: name -> translation (mm). Cached on disk."""
    off = off or {}; styles = styles or {}
    key = hashlib.md5(repr((parts, az, el, sorted(styles.items()), sorted((k, tuple(v)) for k, v in off.items()),
                            s, pad, [tuple(np.round(b, 2)) for b in bounds_extra], 3)).encode()).hexdigest()
    fn = os.path.join(RCACHE, key + '.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    ms = []
    for n in parts:
        m = P[n].copy()
        if n in off:
            m.apply_translation(off[n])
        ms.append((n, m))
    b2 = None
    if bounds_extra:
        r, u, d = lineart.basis(az, el)
        V = np.vstack([m.vertices for _, m in ms] + [np.atleast_2d(b) for b in bounds_extra])
        X, Y = V @ r, V @ u
        b2 = (X.min() - pad, X.max() + pad, Y.min() - pad, Y.max() + pad)
    img, cam = lineart.render(ms, az, el, s=s, pad=pad, styles=styles, bounds2d=b2)
    pickle.dump((img, cam), open(fn, 'wb'))
    print('rendered', parts, az, el, img.shape)
    return img, cam


class Panel:
    """An axes at (x, y, w, h) inches on the page showing a rendered image, with
    3D -> axes helpers."""
    def __init__(self, fig, rect, img, cam, zoom=None):
        x, y, w, h = rect
        self.ax = fig.add_axes([x / PW, y / PH, w / PW, h / PH])
        self.ax.set_axis_off()
        self.cam = cam
        H, W = img.shape[:2]
        self.ax.imshow(img, extent=(0, W, H, 0), interpolation='lanczos')
        # fit: keep aspect, centre
        ra = w / h
        if W / H > ra:
            hh = W / ra; self.ax.set_xlim(0, W); self.ax.set_ylim((H + hh) / 2, (H - hh) / 2)
        else:
            ww = H * ra; self.ax.set_xlim((W - ww) / 2, (W + ww) / 2); self.ax.set_ylim(H, 0)
        self.ax.set_aspect('equal')
        self.ppi = (self.ax.get_xlim()[1] - self.ax.get_xlim()[0]) / w     # image px per inch on paper

    def p(self, X):
        return self.cam.project(X)[0]

    def px(self, mm):
        return mm / self.cam.s


def explode_pts(f, e):
    return f['head'] + f['axis'] * e


def screw2d(pn, head, axis, L, d, e=0.0, washer=None, dash=True, lw=LW):
    """Draw a screw on its axis: head seat at `head`, pulled out e mm along `axis`."""
    ax = pn.ax
    hp = head + axis * e
    H2, T2 = pn.p(hp), pn.p(hp - axis * L)
    hd, hh = (5.5, 3.0) if d >= 3 else (3.8, 1.6)
    v = H2 - T2; ln = np.linalg.norm(v)
    if dash and e > 0.5:
        a2 = pn.p(head - axis * 1.0)
        ax.plot([T2[0], a2[0]], [T2[1], a2[1]], ls=(0, (4, 3)), color='k', lw=0.9, zorder=5)
    if washer:
        wd = washer
        wp = head + axis * (e * 0.45 if e > 0 else 0)
        _ring(pn, wp, axis, wd / 2, 1.7, lw)
    if ln < pn.px(1.0):        # axis toward the viewer: draw the head as a circle
        ax.add_patch(Circle(H2, pn.px(hd / 2), fc='white', ec='k', lw=lw, zorder=7))
        ax.add_patch(Circle(H2, pn.px(hd / 5), fc='k', ec='k', lw=lw * 0.6, zorder=7))
        return H2
    u = v / ln; n = np.array([-u[1], u[0]])
    r = pn.px(d / 2); R = pn.px(hd / 2); hz = pn.px(hh)
    shaft = [T2 + n * r * 0.7 - u * 0, T2 - n * r * 0.7, T2 - n * r + u * r * 0.6, H2 - n * r, H2 + n * r, T2 + n * r + u * r * 0.6]
    ax.add_patch(Polygon(shaft, closed=True, fc='white', ec='k', lw=lw, zorder=6, joinstyle='round'))
    pitch = pn.px(0.5 if d < 3 else 0.6) * 1.6
    k = pitch
    while k < ln - pitch * 0.5:
        a = T2 + u * k
        ax.plot([a[0] - n[0] * r, a[0] + n[0] * r + u[0] * pitch * 0.5], [a[1] - n[1] * r, a[1] + n[1] * r + u[1] * pitch * 0.5],
                color='k', lw=0.5, zorder=6)
        k += pitch
    head_poly = [H2 + n * R, H2 - n * R, H2 - n * R * 0.8 + u * hz, H2 + n * R * 0.8 + u * hz]
    ax.add_patch(Polygon(head_poly, closed=True, fc='white', ec='k', lw=lw, zorder=7, joinstyle='round'))
    return H2 + u * hz


def _ring(pn, c, axis, R, r, lw):
    a = np.asarray(axis, float)
    t = np.cross(a, [0, 0, 1.0]) if abs(a[2]) < 0.9 else np.cross(a, [1.0, 0, 0])
    t /= np.linalg.norm(t); b = np.cross(a, t)
    th = np.linspace(0, 2 * np.pi, 64)
    for rr, fc in ((R, 'white'),):
        pts = np.array([c + rr * (np.cos(q) * t + np.sin(q) * b) for q in th])
        pn.ax.add_patch(Polygon(pn.cam.project(pts), closed=True, fc=fc, ec='k', lw=lw, zorder=6))
    pts = np.array([c + r * (np.cos(q) * t + np.sin(q) * b) for q in th])
    pn.ax.add_patch(Polygon(pn.cam.project(pts), closed=True, fc='white', ec='k', lw=lw * 0.8, zorder=6))


def bubble(pn, xy, text, dxy, fs=12):
    """Callout bubble at xy + dxy (inches on paper) with a leader to xy (px)."""
    k = pn.ppi
    pn.ax.annotate(text, xy=xy, xytext=(xy[0] + dxy[0] * k, xy[1] - dxy[1] * k), fontsize=fs, fontweight='bold',
                   ha='center', va='center', zorder=20,
                   bbox=dict(boxstyle='round,pad=0.35,rounding_size=0.6', fc='white', ec='k', lw=1.3),
                   arrowprops=dict(arrowstyle='-', color='k', lw=1.0, shrinkA=0, shrinkB=2))


def num_bubble(pn, xy, n, dxy, fs=13):
    k = pn.ppi
    pn.ax.annotate(str(n), xy=xy, xytext=(xy[0] + dxy[0] * k, xy[1] - dxy[1] * k), fontsize=fs, fontweight='bold',
                   ha='center', va='center', zorder=20,
                   bbox=dict(boxstyle='circle,pad=0.3', fc='white', ec='k', lw=1.5),
                   arrowprops=dict(arrowstyle='-', color='k', lw=1.0, shrinkA=0, shrinkB=0))
    pn.ax.add_patch(Circle(xy, pn.px(3.2), fc='none', ec='k', lw=2.0, zorder=19))


def arrow3(pn, p0, p1, w=1.0):
    a, b = pn.p(p0), pn.p(p1)
    pn.ax.add_patch(FancyArrowPatch(a, b, arrowstyle='simple,head_length=1.1,head_width=1.2,tail_width=0.45',
                                    mutation_scale=18 * w, fc='#9a9a9a', ec='k', lw=1.1, zorder=15))


def arrow2(ax, a, b, w=1.0, curved=0.0):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle='simple,head_length=1.1,head_width=1.2,tail_width=0.45',
                                 connectionstyle='arc3,rad=%.2f' % curved,
                                 mutation_scale=18 * w, fc='#9a9a9a', ec='k', lw=1.1, zorder=15))


def page(n_step=None, title=None):
    fig = plt.figure(figsize=(PW, PH))
    if n_step is not None:
        fig.text((M + 0.45) / PW, 1 - (M + 0.45) / PH, str(n_step), fontsize=34, fontweight='bold', ha='center', va='center',
                 bbox=dict(boxstyle='circle,pad=0.25', fc='white', ec='k', lw=2.5))
    if title:
        fig.text((M + 1.05) / PW, 1 - (M + 0.45) / PH, title, fontsize=20, fontweight='bold', ha='left', va='center')
    return fig


def note(fig, x, y, text, fs=12, **kw):
    fig.text(x / PW, y / PH, text, fontsize=fs, **kw)


def footer(fig, i):
    fig.text(PW / 2 / PW, (M - 0.2) / PH, str(i), fontsize=9, ha='center', color='0.4')


def check_box(fig, x, y, text, fs=12):
    ax = fig.add_axes([x / PW, y / PH, 0.22 / PW, 0.22 / PH]); ax.set_axis_off()
    ax.add_patch(Rectangle((0.05, 0.05), 0.9, 0.9, fc='white', ec='k', lw=1.5, transform=ax.transAxes))
    fig.text((x + 0.32) / PW, (y + 0.11) / PH, text, fontsize=fs, va='center')


ALL_SKULL = ['face', 'back', 'cap', 'jaw', 'stand', 'liner_eye_L', 'liner_eye_R', 'liner_nose', 'screens']
INSIDE = ['face', 'bar', 'modules', 'screens', 'servo', 'horn', 'bracket', 'radar', 'esp32', 'jaw',
          'liner_eye_L', 'liner_eye_R', 'liner_nose']


def ghost(names, keep=()):
    return {n: ('norm' if n in keep else 'faint') for n in names}


# ------------------------------------------------------------------ pages
def p_cover(pdf):
    fig = page()
    fig.text(0.5, 1 - (M + 0.35) / PH, 'BONE EYES', fontsize=34, fontweight='bold', ha='center', va='center')
    fig.text(0.5, 1 - (M + 0.8) / PH, 'talking skull  ·  assembly', fontsize=14, ha='center', va='center', color='0.3')
    img, cam = view(ALL_SKULL, -35, 15, s=0.14)
    Panel(fig, (M + 0.3, 5.2, PW - 2 * M - 0.6, 4.6), img, cam)
    inv = [('face', 'face', 1, -30, 15), ('back', 'back cover', 1, 150, 25), ('cap', 'cap', 1, -30, 25),
           ('jaw', 'jaw', 1, -40, 15), ('stand', 'stand', 1, -30, 20), ('bracket', 'servo bracket', 1, 60, 25),
           ('liner_eye_L', 'eye liner', 2, -20, 10), ('liner_nose', 'nose liner', 1, -20, 10), ('bar', 'eye bar', 1, 160, 20),
           ('modules', 'LCD module', 2, -20, 10), ('servo', 'servo + horn', 1, 60, 25), ('radar', 'radar', 1, -20, 35),
           ('esp32', 'ESP32', 1, 160, 50)]
    cols, rows = 5, 3
    cw, ch = (PW - 2 * M) / cols, 1.55
    y_top = 5.0
    for i, (n, label, q, az, el) in enumerate(inv):
        r, c = divmod(i, cols)
        x, y = M + c * cw, y_top - (r + 1) * ch
        names = [n] + (['horn'] if n == 'servo' else []) + (['screens'] if n == 'modules' else [])
        img, cam = view(names, az, el, s=0.25 if n in ('face', 'back', 'cap', 'jaw', 'stand') else 0.08)
        Panel(fig, (x + 0.1, y + 0.32, cw - 0.2, ch - 0.42), img, cam)
        fig.text((x + cw / 2) / PW, (y + 0.15) / PH, ('%d×  ' % q) + label, fontsize=10, ha='center', va='center',
                 fontweight='bold' if q > 1 else 'normal')
    # USB cable icon
    r, c = divmod(len(inv), cols)
    x, y = M + c * cw, y_top - (r + 1) * ch
    ax = fig.add_axes([(x + 0.15) / PW, (y + 0.35) / PH, (cw - 0.3) / PW, (ch - 0.5) / PH]); ax.set_axis_off()
    t = np.linspace(0, 1, 50)
    ax.plot(0.15 + 0.7 * t, 0.5 + 0.25 * np.sin(t * 6), color='k', lw=2.2)
    ax.add_patch(Rectangle((0.0, 0.42), 0.16, 0.18, fc='white', ec='k', lw=1.4))
    ax.add_patch(Rectangle((0.84, 0.36), 0.1, 0.12, fc='white', ec='k', lw=1.4))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    fig.text((x + cw / 2) / PW, (y + 0.15) / PH, '1×  USB cable', fontsize=10, ha='center', va='center')
    footer(fig, 1)
    pdf.savefig(fig); return fig


SCREWS = [  # label, d, L, qty, head d, head h, note
    ('M2×8', 2.0, 8, 4, 3.8, 1.6, ''),
    ('M2×16', 2.0, 16, 2, 3.8, 1.6, 'self-tapping'),
    ('M3×8', 3.0, 8, 3, 5.5, 3.0, ''),
    ('M3×12', 3.0, 12, 3, 5.5, 3.0, ''),
    ('M3×20', 3.0, 20, 1, 5.5, 3.0, ''),
]


def p_hardware(pdf):
    fig = page(title='Hardware  ·  1:1')
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off()
    ax.set_xlim(0, PW * MM); ax.set_ylim(0, PH * MM); ax.set_aspect('equal')
    # print-at-100% banner
    yb = PH * MM - M * MM - 24
    ax.add_patch(FancyBboxPatch((M * MM + 2, yb - 9), PW * MM - 2 * M * MM - 4, 14, boxstyle='round,pad=0,rounding_size=3',
                                fc='#e8e8e8', ec='k', lw=1.5))
    ax.text(PW * MM / 2, yb - 2, 'Print at 100 %  ·  "Actual size"  ·  no "fit to page"', fontsize=13, fontweight='bold',
            ha='center', va='center')
    # 50 mm check bar
    y0 = yb - 24
    x0 = M * MM + 10
    ax.add_patch(Rectangle((x0, y0), 50, 4, fc='k', ec='k'))
    for k in range(6):
        ax.plot([x0 + 10 * k] * 2, [y0 - 2, y0 + 6], color='k', lw=1)
    ax.text(x0 + 55, y0 + 2, '= 50 mm  (check with a ruler)', fontsize=11, va='center')
    # screws: horizontal, head left, tip right, 1:1
    y = y0 - 22
    for lab, d, L, q, hd, hh, nt in SCREWS:
        xh = x0 + 40
        ax.add_patch(Polygon([(xh - hh, y - hd / 2 * 0.8), (xh - hh, y + hd / 2 * 0.8), (xh, y + hd / 2), (xh, y - hd / 2)],
                             closed=True, fc='white', ec='k', lw=1.0))
        ax.add_patch(Polygon([(xh, y - d / 2), (xh, y + d / 2), (xh + L - d * 0.3, y + d / 2), (xh + L, y + d * 0.2),
                              (xh + L, y - d * 0.2), (xh + L - d * 0.3, y - d / 2)], closed=True, fc='white', ec='k', lw=1.0))
        p = 0.4 if d < 3 else 0.5
        for xx in np.arange(xh + p, xh + L - 0.4, p * 1.5):
            ax.plot([xx, xx + p * 0.6], [y - d / 2, y + d / 2], color='k', lw=0.35)
        ax.text(x0 - 8, y, '%d×' % q, fontsize=20, fontweight='bold', ha='left', va='center')
        ax.text(x0 + 10, y, lab, fontsize=13, fontweight='bold', ha='left', va='center')
        if nt:
            ax.text(xh + L + 6, y, nt, fontsize=10, ha='left', va='center', color='0.3')
        # top view of the head beside it
        xc = x0 + 130
        ax.add_patch(Circle((xc, y), hd / 2, fc='white', ec='k', lw=1.0))
        ax.add_patch(Circle((xc, y), hd / 5, fc='k', ec='k', lw=0.5))
        y -= 17
    # washers
    y -= 2
    for lab, D, dd, q, nt in (('washer Ø9', 9.0, 3.2, 1, 'eye bar slot'), ('washer M3', 7.0, 3.2, 1, 'jaw pivot')):
        ax.text(x0 - 8, y, '%d×' % q, fontsize=20, fontweight='bold', ha='left', va='center')
        ax.text(x0 + 10, y, lab, fontsize=13, fontweight='bold', ha='left', va='center')
        ax.add_patch(Circle((x0 + 50, y), D / 2, fc='white', ec='k', lw=1.0))
        ax.add_patch(Circle((x0 + 50, y), dd / 2, fc='white', ec='k', lw=1.0))
        ax.add_patch(Rectangle((x0 + 70, y - D / 2), 0.8 if D < 8 else 1.6, D, fc='white', ec='k', lw=1.0))
        ax.text(x0 + 80, y, nt, fontsize=10, va='center', color='0.3')
        y -= 17
    # insert
    ax.text(x0 - 8, y, '7×', fontsize=20, fontweight='bold', ha='left', va='center')
    ax.text(x0 + 10, y, 'M3 insert', fontsize=13, fontweight='bold', ha='left', va='center')
    Lr, Dr = 5.7, 4.6
    xi = x0 + 47
    ax.add_patch(Rectangle((xi, y - Dr / 2), Lr, Dr, fc='white', ec='k', lw=1.0))
    for xx in np.arange(xi + 0.6, xi + Lr - 0.3, 0.9):
        ax.plot([xx, xx + 0.5], [y - Dr / 2, y + Dr / 2], color='k', lw=0.4)
    ax.add_patch(Circle((x0 + 70, y), Dr / 2, fc='white', ec='k', lw=1.0))
    ax.add_patch(Circle((x0 + 70, y), 1.5, fc='white', ec='k', lw=1.0))
    ax.text(x0 + 80, y, 'heat-set (soldering iron)', fontsize=10, va='center', color='0.3')
    y -= 22
    # supplied with the servo
    ax.plot([x0 - 8, PW * MM - M * MM - 10], [y + 9, y + 9], color='0.6', lw=0.8)
    ax.text(x0 - 8, y, 'In the servo bag:', fontsize=12, fontweight='bold', va='center')
    ax.text(x0 + 40, y, '2× tab screw   ·   1× horn screw', fontsize=12, va='center')
    y -= 12
    ax.text(x0 - 8, y, 'Also:', fontsize=12, fontweight='bold', va='center')
    ax.text(x0 + 40, y, 'glue  ·  hot glue  ·  double-sided foam tape  ·  soldering iron', fontsize=12, va='center')
    # tools
    footer(fig, 2)
    pdf.savefig(fig); return fig


def p_inserts(pdf):
    fig = page(n_step=1, title='Inserts  ·  M3 ×7')
    note(fig, M + 1.05, PH - M - 0.85, 'Heat-set, flush, square to the hole.', fs=12, color='0.25')
    # A: face from behind-above (cut-away: covers off)
    img, cam = view(['face'], 150, 38, s=0.10)
    pa = Panel(fig, (M, 4.15, PW - 2 * M, 5.6), img, cam)
    dx = {1: (-0.9, 0.7), 2: (-1.1, -0.4), 3: (-0.9, -0.9), 5: (1.0, 0.6), 6: (0.9, -0.8)}
    for k in (1, 2, 3, 5, 6):
        num_bubble(pa, pa.p(INS[k][0]), k, dx[k])
    # B: face from the skull's right (-X), jaw off: pivot boss
    img, cam = view(['face'], -90, 5, s=0.13)
    pb = Panel(fig, (M, M + 0.25, 3.7, 3.7), img, cam)
    num_bubble(pb, pb.p(INS[4][0]), 4, (-0.6, -0.7))
    # C: back cover from behind-above: cap boss
    img, cam = view(['back'], 200, 30, s=0.13)
    pc = Panel(fig, (M + 3.8, M + 0.25, 3.7, 3.7), img, cam)
    num_bubble(pc, pc.p(INS[7][0]), 7, (0.7, 0.6))
    note(fig, M + 3.9, M + 3.7, 'back cover', fs=11, color='0.3')
    note(fig, M + 0.1, M + 3.7, 'face, from the side', fs=11, color='0.3')
    footer(fig, 3)
    pdf.savefig(fig); return fig


def p_bench(pdf):
    fig = page(n_step=1, title='Servo + bracket')
    S = ['bracket', 'servo', 'horn']
    e_servo, e_horn = 45.0, 78.0
    off = {'servo': (e_servo, 0, 0), 'horn': (e_horn, 0, 0)}
    tabs = [FA['tab_0'], FA['tab_1']]
    extra = [t['head'] + [e_servo + 18, 0, 0] for t in tabs] + [FA['horn_screw']['head'] + [e_horn + 14, 0, 0]]
    img, cam = view(S, 28, 18, styles={'servo': 'hi', 'horn': 'hi'}, off=off, s=0.07, pad=10, bounds_extra=extra)
    pn = Panel(fig, (M, 4.0, PW - 2 * M, 5.9), img, cam)
    c = np.array([25.0, 65.13, -24.0])
    arrow3(pn, c + [e_servo + 6, 0, 18], c + [10, 0, 18])
    for t in tabs:
        tip = screw2d(pn, t['head'] + [e_servo, 0, 0], t['axis'], 8, 2, e=12.0)
    bubble(pn, tip, 'servo tab screw ×2', (0.9, 0.5))
    h = FA['horn_screw']
    tip = screw2d(pn, h['head'] + [e_horn, 0, 0], h['axis'], 5, 2, e=8.0)
    bubble(pn, tip, 'horn screw', (0.1, -1.0))
    # centre + horn-down inset
    ax = fig.add_axes([(M + 0.2) / PW, (M + 0.6) / PH, 3.2 / PW, 3.0 / PH]); ax.set_axis_off(); ax.set_aspect('equal')
    ax.set_xlim(-1.3, 1.3); ax.set_ylim(-1.5, 1.2)
    ax.add_patch(Circle((0, 0), 1.0, fc='white', ec='k', lw=2))
    th = np.radians(np.linspace(-180, 0, 50))
    ax.plot(0.75 * np.cos(th), 0.75 * np.sin(th) * -1, color='0.5', lw=1, ls=':')
    ax.add_patch(Polygon([(-0.12, 0), (0.12, 0), (0.07 + np.sin(np.radians(20)) * 0.0, -0.95), (-0.07, -0.95)], closed=True,
                         fc='#d8d8d8', ec='k', lw=2, transform=matplotlib.transforms.Affine2D().rotate_deg(-20) + ax.transData))
    ax.add_patch(Circle((0, 0), 0.18, fc='white', ec='k', lw=2))
    ax.text(0, 1.12, 'centre (90°)', ha='center', fontsize=12, fontweight='bold')
    ax.text(0, -1.35, 'horn points down the jaw arm', ha='center', fontsize=11)
    note(fig, M + 3.7, M + 2.2, '1. Tab screws\n2. Centre the servo\n3. Horn on, pointing down', fs=13, linespacing=1.6)
    footer(fig, 4)
    pdf.savefig(fig); return fig


def p_liners(pdf):
    fig = page(n_step=2, title='Liners')
    L = ['liner_eye_L', 'liner_eye_R', 'liner_nose']
    e = 70.0
    off = {n: (0, -e, 0) for n in L}
    img, cam = view(['face'] + L, -40, 10, styles={**{n: 'hi' for n in L}, 'face': 'norm'}, off=off, s=0.10, pad=8)
    pn = Panel(fig, (M, 2.4, PW - 2 * M, 7.4), img, cam)
    for n in L:
        c = P[n].bounds.mean(0)
        arrow3(pn, c + [0, -e + 12, 0], c + [0, -8, 0], 1.1)
    # glue dots inset
    ax = fig.add_axes([(M + 0.3) / PW, (M + 0.3) / PH, 3.0 / PW, 1.8 / PH]); ax.set_axis_off(); ax.set_aspect('equal')
    ax.set_xlim(-1.6, 1.6); ax.set_ylim(-1, 1)
    ax.add_patch(matplotlib.patches.Ellipse((0, 0), 2.2, 1.6, fc='white', ec='k', lw=2))
    ax.add_patch(matplotlib.patches.Ellipse((0, 0), 1.5, 1.0, fc='white', ec='k', lw=1.2))
    for q in (90, 210, 330):
        ax.add_patch(Circle((0.92 * np.cos(np.radians(q)), 0.66 * np.sin(np.radians(q))), 0.08, fc='k'))
    note(fig, M + 3.5, M + 1.2, 'glue  2–3 dabs on the seat\npush in from the front, lip flush', fs=13, linespacing=1.6)
    footer(fig, 5)
    pdf.savefig(fig); return fig


def p_eyes(pdf):
    fig = page(n_step=3, title='Eyes')
    eb = 60.0
    B = ['bar', 'modules', 'screens']
    off = {n: (0, eb, 0) for n in B}
    names = ['face', 'servo', 'horn', 'bracket', 'jaw', 'liner_eye_L', 'liner_eye_R', 'liner_nose'] + B
    sty = {**ghost(names, keep=['face']), 'bar': 'hi', 'modules': 'hi', 'screens': 'hi'}
    names = ['face', 'liner_eye_L', 'liner_eye_R'] + B
    sty = {'face': 'norm', 'liner_eye_L': 'ghost', 'liner_eye_R': 'ghost', 'bar': 'hi', 'modules': 'hi', 'screens': 'hi'}
    es = 26.0
    extra = [FA['bar_bolt']['head'] + [0, eb + es + 20, 0]]
    img, cam = view(names, 125, 22, styles=sty, off=off, s=0.085, pad=8, bounds_extra=extra)
    pn = Panel(fig, (M, 2.6, PW - 2 * M, 7.2), img, cam)
    arrow3(pn, np.array([0, 40.0 + eb, -2]), np.array([0, 36.0, -2]), 1.2)
    bubble(pn, pn.p(INS[1][0]), 'post ①', (-0.3, 0.9), fs=10)
    bubble(pn, pn.p([27.5, INS[1][0][1], 16.0]), 'key peg', (-0.6, 0.9), fs=10)
    tips = []
    for k in range(4):
        f = FA['m2_%d' % k]
        tips.append(screw2d(pn, f['head'] + [0, eb, 0], f['axis'], 8, 2, e=es))
    bubble(pn, tips[2], 'M2×8 ×4', (0.9, 0.5))
    f = FA['bar_bolt']
    t = screw2d(pn, f['head'] + [0, eb, 0], f['axis'], 12, 3, e=es + 8, washer=9.0)
    bubble(pn, t, 'M3×12  + washer Ø9', (-1.0, 0.6))
    # dashed guides from the bar holes to post (left) / key peg (right)
    for hx in (-27.5, 27.5):
        a, b = pn.p([hx, scene.B.EYE_DEPTH + 9 + eb, 16]), pn.p([hx, scene.B.EYE_DEPTH + 9, 16])
        pn.ax.plot([a[0], b[0]], [a[1], b[1]], ls=(0, (2, 3)), color='k', lw=0.9, zorder=4)
    note(fig, M + 0.2, M + 1.6, 'Plug the cables into the LCDs first.\nBolt hole → post (insert ①)  ·  other hole → key peg.\nCentre the screens.',
         fs=12, linespacing=1.7)
    footer(fig, 6)
    pdf.savefig(fig); return fig


def p_radar_usb(pdf):
    fig = page(n_step=4, title='Radar')
    names = ['face', 'radar', 'radar_edge']
    up = 50.0
    sty = {'face': 'norm', 'radar': 'hi', 'radar_edge': 'hi'}
    img, cam = view(names, 150, 45, styles=sty, s=0.101, pad=6, off={'radar_edge': (0, 14, up)})
    pn = Panel(fig, (M, 5.4, PW - 2 * M, 4.6), img, cam)
    c = P['radar'].bounds.mean(0)
    arrow3(pn, c + [24, 14, up - 4], c + [24, 14, 12], 1.0)
    arrow3(pn, c + [24, 16, 2], c + [24, 2, 2], 0.8)
    bubble(pn, pn.p(c + [0, 0, 0]), 'hot glue', (1.4, -0.2), fs=10)
    note(fig, M + 0.1, 5.2, 'on edge down the slot, then flat and forward  ·  dab of hot glue', fs=12)
    # 5: USB
    fig.text((M + 0.45) / PW, 4.75 / PH, '5', fontsize=34, fontweight='bold', ha='center', va='center',
             bbox=dict(boxstyle='circle,pad=0.25', fc='white', ec='k', lw=2.5))
    fig.text((M + 1.05) / PW, 4.75 / PH, 'USB cable', fontsize=20, fontweight='bold', ha='left', va='center')
    img, cam = view(['face'], 160, 28, styles={'face': 'norm'}, s=0.12, pad=4)
    pu = Panel(fig, (M, M + 0.2, PW - 2 * M, 3.9), img, cam)
    N = scene.B.NECK
    pts = np.array([[-25, 70, -5], [-10, 85, -6], [0, 90, -10], [0, 90, -35], [0, 90, -66]], float)
    q = pu.cam.project(pts)
    pu.ax.plot(q[:3, 0], q[:3, 1], color='k', lw=3.0, zorder=10, solid_capstyle='round')
    pu.ax.plot(q[2:, 0], q[2:, 1], color='k', lw=3.0, zorder=10, ls=(0, (3, 2)))
    a, b = q[-1], q[-1] + np.array([0, pu.px(12)])
    pu.ax.add_patch(Rectangle((a[0] - pu.px(6), a[1]), pu.px(12), pu.px(9), fc='white', ec='k', lw=1.5, zorder=11))
    pu.ax.text(a[0] + pu.px(9), a[1] + pu.px(5), 'USB-A', fontsize=11, va='center', fontweight='bold')
    arrow3(pu, [12, 90, -8], [12, 90, -40], 0.9)
    bubble(pu, q[0], 'micro-USB end stays inside', (1.6, 0.35), fs=10)
    footer(fig, 7)
    pdf.savefig(fig); return fig


def p_servo(pdf):
    fig = page(n_step=6, title='Servo')
    up = 50.0
    S = ['bracket', 'servo', 'horn']
    names = ['face', 'bar', 'modules', 'radar'] + S
    sty = {'face': 'norm', 'bar': 'ghost', 'modules': 'ghost', 'radar': 'ghost', **{n: 'hi' for n in S}}
    off = {n: (0, 0, up) for n in S}
    es = 22.0
    extra = [FA['bracket_0']['head'] + [0, 0, up + es + 12]]
    img, cam = view(names, 140, 40, styles=sty, off=off, s=0.10, pad=6, bounds_extra=extra)
    pn = Panel(fig, (M, 2.0, PW - 2 * M, 7.9), img, cam)
    c = np.array([18.0, 65.0, -10.0])
    arrow3(pn, c + [8, 0, up - 5], c + [8, 0, 8], 1.2)
    for k in (0, 1):
        f = FA['bracket_%d' % k]
        t = screw2d(pn, f['head'] + [0, 0, up], f['axis'], 8, 3, e=es)
        # dashed guide: bolt line from the bracket down to its boss (insert ② ③)
        a, b = pn.p(f['head'] + [0, 0, up - 3.5]), pn.p(INS[2 + k][0])
        pn.ax.plot([a[0], b[0]], [a[1], b[1]], ls=(0, (2, 3)), color='k', lw=0.9, zorder=4)
    bubble(pn, t, 'M3×8 ×2', (-1.0, 0.4))
    note(fig, M + 0.2, M + 1.0, 'gear tower down the slot in the cup wall', fs=13)
    footer(fig, 8)
    pdf.savefig(fig); return fig


def p_esp32(pdf):
    fig = page(n_step=7, title='ESP32')
    up = 40.0
    names = ['face', 'bar', 'modules', 'radar', 'bracket', 'servo', 'horn', 'esp32']
    sty = {**ghost(names), 'face': 'norm', 'esp32': 'hi'}
    img, cam = view(names, 150, 45, styles=sty, off={'esp32': (0, 0, up)}, s=0.10, pad=6)
    pn = Panel(fig, (M, 3.4, PW - 2 * M, 6.4), img, cam)
    c = P['esp32'].bounds.mean(0)
    arrow3(pn, c + [0, 0, up - 6], c + [0, 0, 5], 1.1)
    # tape
    tb = np.array([[-46, 40, -14.6], [-22, 40, -14.6], [-22, 80, -14.6], [-46, 80, -14.6]], float)
    pn.ax.add_patch(Polygon(pn.cam.project(tb + [0, 0, up * 0.45]), closed=True, fc='#cfcfcf', ec='k', lw=1.0, hatch='///', zorder=9))
    bubble(pn, pn.p([-34, 60, -14.6 + up * 0.45]), 'foam tape', (-1.2, -0.3))
    note(fig, M + 0.2, M + 2.2, 'No tray: tape it flat just behind the eye bar\n(solder side covered).', fs=13, linespacing=1.6)
    note(fig, M + 0.2, M + 0.6, 'Plug in:  LCD ×2  ·  radar  ·  servo  ·  USB', fs=13, fontweight='bold')
    footer(fig, 9)
    pdf.savefig(fig); return fig


def p_jaw(pdf):
    fig = page(n_step=8, title='Jaw')
    names = ['face', 'jaw', 'horn', 'servo', 'bracket']
    sty = {'face': 'norm', 'jaw': 'hi', 'horn': 'ghost', 'servo': 'ghost', 'bracket': 'ghost'}
    es = 30.0
    # A: +X side (horn side)
    extra = [FA['horn_jaw_0']['head'] + [es + 20, 0, 0]]
    img, cam = view(names, 50, 8, styles=sty, s=0.09, pad=6, bounds_extra=extra)
    pa = Panel(fig, (M, 5.25, PW - 2 * M, 4.55), img, cam)
    for k in (0, 1):
        f = FA['horn_jaw_%d' % k]
        t = screw2d(pa, f['head'], f['axis'], 16, 2, e=es)
    bubble(pa, t, 'M2×16 ×2', (0.9, -0.5))
    note(fig, M + 0.2, 5.25, 'from outside, into the horn arm', fs=12)
    # B: -X side (pivot)
    extra = [FA['pivot']['head'] + [-es - 25, 0, 0]]
    img, cam = view(names, -50, 8, styles=sty, s=0.09, pad=6, bounds_extra=extra)
    pb = Panel(fig, (M, M + 0.6, PW - 2 * M, 4.4), img, cam)
    f = FA['pivot']
    t = screw2d(pb, f['head'], f['axis'], 20, 3, e=es, washer=7.0)
    bubble(pb, t, 'M3×20  + washer', (-0.9, -0.6))
    note(fig, M + 0.2, M + 0.4, 'into insert ④  ·  snug, free to swing', fs=12, fontweight='bold')
    footer(fig, 10)
    pdf.savefig(fig); return fig


def p_back(pdf):
    fig = page(n_step=9, title='Test')
    for i, t in enumerate(['eyes', 'jaw', 'radar', 'sound']):
        check_box(fig, M + 1.1 + i * 1.6, PH - M - 1.05, t, fs=13)
    fig.text((M + 0.45) / PW, (PH - M - 1.7) / PH, '10', fontsize=28, fontweight='bold', ha='center', va='center',
             bbox=dict(boxstyle='circle,pad=0.25', fc='white', ec='k', lw=2.5))
    fig.text((M + 1.05) / PW, (PH - M - 1.7) / PH, 'Back cover', fontsize=20, fontweight='bold', ha='left', va='center')
    up = 45.0
    names = ['face', 'jaw', 'stand', 'back', 'bar', 'modules', 'servo', 'horn', 'bracket']
    sty = {**ghost(names), 'face': 'norm', 'jaw': 'norm', 'back': 'hi'}
    es = 28.0
    extra = [FA['back_screw']['head'] + [0, es + 15, up]]
    img, cam = view(names, 155, 22, styles=sty, off={'back': (0, 0, up)}, s=0.11, pad=6, bounds_extra=extra)
    pn = Panel(fig, (M, M + 0.6, PW - 2 * M, 7.6), img, cam)
    c = np.array([45.0, 120.0, 10.0])
    arrow3(pn, c + [0, 0, up + 8], c + [0, 0, 18], 1.2)
    f = FA['back_screw']
    a, b = pn.p(f['head'] + [0, 0, up]), pn.p(INS[5][0])
    pn.ax.plot([a[0], b[0]], [a[1], b[1]], ls=(0, (2, 3)), color='k', lw=0.9, zorder=4)
    t = screw2d(pn, f['head'] + [0, 0, up], f['axis'], 12, 3, e=es)
    bubble(pn, t, 'M3×12', (0.9, 0.3))
    note(fig, M + 0.2, M + 0.35, 'drop onto the floor lip, screw low at the back', fs=12)
    footer(fig, 11)
    pdf.savefig(fig); return fig


def p_cap(pdf):
    fig = page(n_step=11, title='Cap')
    up = 55.0
    names = ['face', 'jaw', 'stand', 'back', 'cap']
    sty = {'face': 'norm', 'jaw': 'norm', 'stand': 'ghost', 'back': 'norm', 'cap': 'hi'}
    es = 28.0
    f = FA['cap_screw']
    extra = [f['head'] + f['axis'] * (es + 15) + [0, 0, up]]
    img, cam = view(names, 150, 20, styles=sty, off={'cap': (0, 0, up)}, s=0.11, pad=6, bounds_extra=extra)
    pn = Panel(fig, (M, M + 0.6, PW - 2 * M, 8.9), img, cam)
    c = np.array([-50.0, 70.0, 45.0])
    arrow3(pn, c + [0, 0, up + 5], c + [0, 0, 8], 1.2)
    a, b = pn.p(f['head'] + [0, 0, up]), pn.p(INS[7][0])
    pn.ax.plot([a[0], b[0]], [a[1], b[1]], ls=(0, (2, 3)), color='k', lw=0.9, zorder=4)
    t = screw2d(pn, f['head'] + [0, 0, up], f['axis'], 12, 3, e=es)
    bubble(pn, t, 'M3×12', (0.9, 0.4))
    note(fig, M + 0.2, M + 0.35, 'straight down onto the cut  ·  screw high at the back', fs=12)
    footer(fig, 12)
    pdf.savefig(fig); return fig


def p_stand(pdf):
    fig = page(n_step=12, title='Stand')
    dn = 60.0
    names = ['face', 'jaw', 'back', 'cap', 'stand']
    sty = {'face': 'norm', 'jaw': 'norm', 'back': 'norm', 'cap': 'norm', 'stand': 'hi'}
    es = 30.0
    f = FA['stand']
    extra = [f['head'] + [0, es + 20, -dn]]
    img, cam = view(names, 215, 12, styles=sty, off={'stand': (0, 0, -dn)}, s=0.12, pad=6, bounds_extra=extra)
    pn = Panel(fig, (M, M + 0.6, PW - 2 * M, 8.9), img, cam)
    arrow3(pn, [40, 90, -125], [40, 90, -78], 1.2)
    # cable in the column slot
    sb = P['stand'].bounds
    pts = np.array([[0, 90, -40], [0, 90, -70], [0, sb[1, 1] + 0.5, -100], [0, sb[1, 1] + 0.5, -dn - 70], [0, sb[1, 1] + 8, -dn - 90]], float)
    pts[2:, 2] += 0
    q = pn.cam.project(pts + [0, 0, 0])
    q2 = pn.cam.project(np.array([[-8, 90, -30], [-8, 90, -58], [-17.5, 90, -52 - dn], [-17.5, 90, -126 - dn],
                                  [-20, 90, -129 - dn], [-62, 90, -129 - dn]]))
    pn.ax.plot(q2[:2, 0], q2[:2, 1], color='k', lw=3.0, zorder=10, ls=(0, (3, 2)))
    pn.ax.plot(q2[2:, 0], q2[2:, 1], color='k', lw=3.0, zorder=10, solid_joinstyle='round')
    bubble(pn, q2[3], 'cable in the slot', (1.0, -0.4))
    a, b = pn.p(f['head'] + [0, 0, -dn]), pn.p(INS[6][0])
    pn.ax.plot([a[0], b[0]], [a[1], b[1]], ls=(0, (2, 3)), color='k', lw=0.9, zorder=4)
    t = screw2d(pn, f['head'] + [0, 0, -dn], f['axis'], 8, 3, e=es)
    bubble(pn, t, 'M3×8', (-0.9, 0.4))
    note(fig, M + 0.2, M + 0.35, 'push the stand onto the neck  ·  screw from behind', fs=12)
    footer(fig, 13)
    pdf.savefig(fig); return fig


def main():
    pngdir = sys.argv[sys.argv.index('--pngs') + 1] if '--pngs' in sys.argv else None
    only = sys.argv[sys.argv.index('--only') + 1].split(',') if '--only' in sys.argv else None
    pages = [p_cover, p_hardware, p_inserts, p_bench, p_liners, p_eyes, p_radar_usb, p_servo, p_esp32, p_jaw, p_back,
             p_cap, p_stand]
    with PdfPages(PDF) as pdf:
        for i, fn in enumerate(pages):
            if only and str(i + 1) not in only:
                continue
            fig = fn(pdf)
            if pngdir:
                fig.savefig(os.path.join(pngdir, 'page%02d.png' % (i + 1)), dpi=70)
            plt.close(fig)
    print('wrote', PDF, '%.1f MB' % (os.path.getsize(PDF) / 1e6))


if __name__ == '__main__':
    main()
