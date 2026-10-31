"""M3 heat-set insert practice coupon: insert_block.stl + screw_plate.stl.

Both print flat, top face up, no supports, 0.5 mm bottom chamfer.
Run: hardware/.venv/bin/python hardware/coupons/insert_practice.py
"""
import os, sys
import numpy as np
import trimesh
import manifold3d as mf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'skull'))
import printability  # noqa: E402

OUT = os.path.join(HERE, 'out')
os.makedirs(OUT, exist_ok=True)

BORE = 6.7          # pilot depth (skull INSERT_BORE)
RELIEF = 3.0        # Ø3.2 relief past the pilot
PILOTS = [3.8, 3.9, 4.0, 4.0, 4.1, 4.2]
PITCH = 11.0
X0 = 5.5
YC = 15.0
BL, BW, BH = 77.0, 30.0, 12.0
BOSS_D, BOSS_H, BOSS_BORE = 9.0, 8.0, 4.0
BOSS_X = X0 + PITCH * len(PILOTS)      # 71.5
PL, PT = 66.0, 3.0                      # plate length / thickness (boss stays outside it)
CH = 0.5


def to_man(t):
    return mf.Manifold(mf.Mesh(vert_properties=np.asarray(t.vertices, np.float32),
                               tri_verts=np.asarray(t.faces, np.uint32)))


def cyl(x, y, z0, z1, d, seg=64):
    return mf.Manifold.cylinder(z1 - z0, d / 2, d / 2, seg).translate([x, y, z0])


def chamfered_box(L, W, H):
    pts = []
    for z, i in ((0, CH), (CH, 0), (H, 0)):
        pts += [[i, i, z], [L - i, i, z], [L - i, W - i, z], [i, W - i, z]]
    return to_man(trimesh.convex.convex_hull(np.array(pts, float)))


def bore(x, y, ztop, d):
    return cyl(x, y, ztop - BORE, ztop + 0.3, d) + cyl(x, y, ztop - BORE - RELIEF, ztop - BORE + 0.1, 3.2)


def block():
    m = chamfered_box(BL, BW, BH)
    m = m + cyl(BOSS_X, YC, BH - 0.1, BH + BOSS_H, BOSS_D)
    for i, d in enumerate(PILOTS):
        m = m - bore(X0 + PITCH * i, YC, BH, d)
    m = m - bore(BOSS_X, YC, BH + BOSS_H, BOSS_BORE)
    # V-grooves (n per hole) running up the front face, 1.4 wide x 0.7 deep
    w, dp, gp = 1.4, 0.7, 1.8
    for i in range(len(PILOTS)):
        n = i + 1
        for k in range(n):
            x = X0 + PITCH * i + (k - (n - 1) / 2) * gp
            tri = np.array([[x - w / 2, -0.01], [x + w / 2, -0.01], [x, dp]])
            cs = mf.CrossSection([tri]).extrude(BH + 2).translate([0, 0, -1])
            m = m - cs
    return m


def plate():
    m = chamfered_box(PL, BW, PT)
    for i in range(len(PILOTS)):
        m = m - cyl(X0 + PITCH * i, YC, -1, PT + 1, 3.4)
    return m


def main():
    for name, m in (('insert_block', block()), ('screw_plate', plate())):
        mesh = m.to_mesh()
        t = trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=True)
        t.export(os.path.join(OUT, name + '.stl'))
        r = printability.report(printability.analyse(t, name))
        print(name, 'watertight', t.is_watertight, 'bodies', len(t.split(only_watertight=False)),
              'bbox', np.round(t.extents, 2).tolist(), 'vol', round(t.volume, 1))
        print('  ', r)


if __name__ == '__main__':
    main()
