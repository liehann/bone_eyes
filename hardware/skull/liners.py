"""Black socket and nose liners.

Each eye socket and the nose get a separate liner printed in black. Its inner
surface is the analytic bowl that build.py lofts (socket(): rim outline,
quarter-ellipse profile, aperture or flat window), so the visible cavity keeps
its shape and size. The face is cut back by the liner plus a loose gap and gets
a shallow rebate round the rim, where the liner's lip sits flush with the face
surface. A new exact wall behind the cut keeps the face at least 1.2 mm thick.

Cross-sections are worked per rim angle in (r, y): r is the distance from the
bowl axis (through the bowl centre, along Y) in the direction of that angle;
y is depth. Every surface is a loft over the 120 rim angles, so all edges are
smooth lines, not voxel steps.

The liner's outside is the smallest envelope that is self-supporting at 45
degrees when the liner prints base down (aperture or window on the bed): the
build plate needs no supports, and the visible inner surface is all top skin.
"""
import os, pickle
import numpy as np
import trimesh
import manifold3d as mf

T_WALL = 1.2        # liner wall
GAP = 0.3           # liner to face, radial / normal
SEAT_GAP = 0.05     # square to the 45-degree seat under the lip (the only near-contact)
LIP_T = 0.6         # rim lip thickness (into the face surface)
LIP_W = 1.0         # lip width past the liner wall, over the face
FACE_WALL = 2.0     # new face wall behind the liner pocket (>= 1.2 after cuts)
BASE_T = 1.2        # new face wall behind the pocket's base
COLLAR, COLLAR_T = 5.0, 2.7   # radial reach past the rim and depth of the collar that ties it to the bone shell
MIN_LINER_WALL = 0.8  # checks
MIN_FACE_WALL = 1.2   # target behind the liners; samples under it are counted in the report
MIN_FACE_HARD = 0.9   # the build fails under this
RIM_ZONE = 2.5     # the face check reports its first 2.5 mm below the rim (lip, rebate, seat) as rim edge
K = 64              # profile points rim -> bottom
RHO = np.r_[-1.0, -0.5, np.arange(0.0, 7.01, 0.25)]   # radial offsets past the rim at which the face surface is sampled


# ----------------------------------------------------------------------------- mesh helpers
def _mesh(M):
    o = M.to_mesh()
    return (np.asarray(o.vert_properties[:, :3], np.float64), np.asarray(o.tri_verts, np.int64))


def _man(vf):
    v, f = vf
    return mf.Manifold(mf.Mesh(vert_properties=np.asarray(v, np.float32), tri_verts=np.asarray(f, np.uint32)))


def to_tri(M):
    v, f = _mesh(M)
    t = trimesh.Trimesh(v, f, process=False)
    t.merge_vertices()
    return t


def to_man(t):
    t = t.copy(); t.merge_vertices()
    return _man((t.vertices, t.faces))


def vol(M):
    return M.volume() / 1000.0


def loft(rings, cap_first=None, cap_last=None, cyclic=False):
    """Closed surface through rings (list of (N,3), each closed round the bowl);
    fan caps to the given points. Same construction as build.rings_mesh."""
    rings = [np.asarray(r, float) for r in rings]
    N = len(rings[0]); nr = len(rings)
    V = list(np.vstack(rings)); F = []
    pairs = [(i, i + 1) for i in range(nr - 1)] + ([(nr - 1, 0)] if cyclic else [])
    for a, b in pairs:
        for j in range(N):
            j1 = (j + 1) % N
            p, q, r_, s_ = a * N + j, a * N + j1, b * N + j, b * N + j1
            F += [[p, r_, q], [q, r_, s_]]
    if cap_first is not None:
        ci = len(V); V.append(np.asarray(cap_first, float))
        F += [[ci, j, (j + 1) % N] for j in range(N)]
    if cap_last is not None:
        ci = len(V); V.append(np.asarray(cap_last, float)); o = (nr - 1) * N
        F += [[ci, o + (j + 1) % N, o + j] for j in range(N)]
    t = trimesh.Trimesh(np.array(V), np.array(F), process=True)
    trimesh.repair.fix_normals(t)
    if t.volume < 0:
        t.invert()
    assert t.is_watertight, 'liner loft not watertight'
    M = to_man(t)
    assert M.status() == mf.Error.NoError if hasattr(M, 'status') else True
    return M


def union(ms):
    ms = [m for m in ms if m is not None]
    return mf.Manifold.batch_boolean(ms, mf.OpType.Add) if len(ms) > 1 else ms[0]


def cyl(p0, p1, r, seg=96):
    p0 = np.asarray(p0, float); p1 = np.asarray(p1, float); d = p1 - p0; L = np.linalg.norm(d)
    m = mf.Manifold.cylinder(L, r, r, seg)
    z = d / L; x = np.cross(z, [1, 0, 0] if abs(z[0]) < 0.9 else [0, 1, 0]); x /= np.linalg.norm(x); y = np.cross(z, x)
    T = np.zeros((3, 4)); T[:, 0], T[:, 1], T[:, 2], T[:, 3] = x, y, z, p0
    return m.transform(T)


def circ_smooth(a, w):
    """Circular moving average along axis 0."""
    if w <= 1:
        return a
    k = np.ones(w) / w
    pad = np.concatenate([a[-w:], a, a[:w]], axis=0)
    out = np.apply_along_axis(lambda v: np.convolve(v, k, mode='same'), 0, pad)
    return out[w:-w]


# ----------------------------------------------------------------------------- one bowl
class Bowl:
    """The analytic bowl of build.socket(): rim (r_rim, y_rim) per angle th,
    quarter-ellipse profile to the bottom outline r_bot at depth y_bot."""

    def __init__(self, name, p, y_base):
        self.name = name
        self.c = np.asarray(p['c'], float)
        self.th = np.asarray(p['th'], float); self.N = len(self.th)
        self.r_rim = np.asarray(p['r_rim'], float) * np.ones(self.N)
        self.y_rim = np.asarray(p['y_rim'], float) * np.ones(self.N)
        self.r_bot = np.asarray(p['r_bot'], float) * np.ones(self.N)
        self.y_bot = float(p['y_bot']); self.flat = bool(p['flat'])
        self.y_base = y_base                    # back face of the liner (flat, on the bed)
        self.ct, self.st = np.cos(self.th), np.sin(self.th)
        s = np.linspace(0, np.pi / 2, K)[:, None]
        a = (self.r_rim - self.r_bot)[None]; b = (self.y_bot - self.y_rim)[None]
        self.ri = self.r_bot[None] + a * np.cos(s)            # (K, N) inner profile, rim -> bottom
        self.yi = self.y_rim[None] + b * np.sin(s)
        nr, ny = b * np.cos(s), a * np.sin(s)
        L = np.hypot(nr, ny); self.nr, self.ny = nr / L, ny / L
        # offsets are laid off in the (r, y) plane of each rim angle; where the
        # surface also slopes round the rim, scale them so they hold square to it
        Pi = self.P(self.ri, self.yi)                                            # (K, N, 3)
        ds = np.gradient(Pi, axis=0)
        dth = (np.roll(Pi, -1, axis=1) - np.roll(Pi, 1, axis=1)) / 2
        n3 = np.cross(ds, dth); n3 /= np.linalg.norm(n3, axis=-1, keepdims=True) + 1e-12
        n2 = np.stack([self.nr * self.ct[None], self.ny, self.nr * self.st[None]], axis=-1)
        self.kt = 1.0 / np.clip(np.abs((n3 * n2).sum(-1)), 0.5, 1.0)

    def P(self, r, y):
        """(.., N) radii and depths -> (.., N, 3) points."""
        r = np.asarray(r, float); y = np.asarray(y, float) * np.ones_like(r)
        return np.stack([self.c[0] + r * self.ct, y, self.c[1] + r * self.st], axis=-1)

    def ctr(self, y):
        return np.array([self.c[0], y, self.c[1]])

    # --- the face surface round the rim
    def sample_face(self, face_t):
        """Depth of the face surface at radial offsets RHO past the rim (first hit
        along +Y from in front). (len(RHO), N)."""
        y0 = float(self.y_rim.min()) - 30.0
        rr = self.r_rim[None] + RHO[:, None]
        org = self.P(rr, np.full_like(rr, y0)).reshape(-1, 3)
        loc, ri, _ = face_t.ray.intersects_location(org, np.tile([0, 1.0, 0], (len(org), 1)), multiple_hits=True)
        yf = np.full(len(org), np.nan)
        for i in range(len(org)):
            h = loc[ri == i]
            if len(h):
                yf[i] = h[:, 1].min()
        yf = yf.reshape(len(RHO), self.N)
        return yf

    def set_face(self, yf):
        """yf: sampled face depth (len(RHO), N). Sets the lip top L: the face surface,
        but never in front of the rim depth (where bone rises in front of the rim,
        the lip stays at the rim depth and that bone is trimmed back to the rebate),
        and the lip underside ylb (L offset LIP_T into the face along its normal)."""
        yf = yf.copy()
        for k in range(len(RHO)):           # rays that missed: interpolate round the rim
            v = yf[k]; bad = ~np.isfinite(v)
            if bad.all():
                v[:] = self.y_rim + 10.0
            elif bad.any():
                idx = np.arange(self.N)
                v[bad] = np.interp(idx[bad], idx[~bad], v[~bad], period=self.N)
        self.yf_raw = yf
        Lw = np.maximum(yf, self.y_rim[None])
        Lw[RHO < 0] = self.y_rim[None]
        Lw = circ_smooth(Lw.T, 5).T                                   # along the rim
        Lp = np.pad(Lw, ((1, 1), (0, 0)), mode='edge')                # along rho
        Lw = (Lp[:-2] + Lp[1:-1] + Lp[2:]) / 3.0
        Lw = np.maximum(Lw, self.y_rim[None])
        # the lip may slope back at most 45 degrees; where the bone falls away
        # faster, the lip stands just proud of it
        i0 = int(np.searchsorted(RHO, 0.0))
        for k in range(i0 + 1, len(RHO)):
            Lw[k] = np.minimum(Lw[k], Lw[k - 1] + (RHO[k] - RHO[k - 1]))
        self.L = Lw
        # LIP_T measured square to the lip: allow for its slope across and round the rim
        dy = np.gradient(self.L, RHO, axis=0)
        da = (np.roll(self.L, -1, axis=1) - np.roll(self.L, 1, axis=1)) / (2 * (2 * np.pi / self.N)) / \
            np.maximum(self.r_rim[None] + RHO[:, None], 1.0)
        self.ylb = self.L + LIP_T * np.sqrt(1.0 + dy ** 2 + np.minimum(da ** 2, 3.0))
        # where bone stands in front of the rim (a raised margin round the socket)
        # it hides the seam itself: the lip narrows to nothing there, rather than
        # the rebate shaving that bone to a sliver
        m = (RHO >= T_WALL + GAP - 1e-9) & (RHO <= T_WALL + LIP_W + GAP + 0.5 + 1e-9)
        sleeve = np.maximum(0.0, (self.y_rim[None] - yf[m]).max(axis=0))
        lw = LIP_W * np.clip(1.0 - (sleeve - 0.3) / 0.6, 0.0, 1.0)
        lw = np.minimum(lw, circ_smooth(lw, 5))
        self.lip_w = lw
        self.W = T_WALL * self.kt[0] + lw                       # lip outer edge past the rim, per angle
        self.G = GAP * self.kt[0]                                # the gap at the rim, per angle
        self.y_front = self.L[RHO <= T_WALL + LIP_W + GAP + 0.01].min(axis=0)

    def at(self, A, rho):
        """A (len(RHO), N) at per-angle offsets rho (n, N)."""
        return np.stack([np.interp(rho[:, j], RHO, A[:, j]) for j in range(self.N)], 1)

    # --- envelopes
    def envelope(self, t, base, lip=None, M=120):
        """Body whose outside is the smallest envelope that is self-supporting at
        45 degrees from the base plane (y_base + base) of the wall offset t behind
        the bowl, the straight wall forward of the rim and, with lip = (dr, dy),
        the lip underside out to its edge, moved dr outward and dy deeper. Solid to the axis."""
        yb = self.y_base + base
        u_top = yb - (self.y_front - 1.5)                                         # (N,)
        Uo = np.linspace(0, 1, M)[:, None] * u_top[None]                          # (M, N)
        E = np.empty_like(Uo)
        for j in range(self.N):
            tk = t * self.kt[:, j]
            ro = self.ri[:, j] + tk * self.nr[:, j]; uo = yb - (self.yi[:, j] + tk * self.ny[:, j])
            ro = np.r_[ro[::-1], self.r_rim[j] + tk[0], self.r_rim[j] + tk[0]]          # bottom -> rim -> straight forward
            uo = np.r_[uo[::-1], yb - self.y_rim[j] + 1e-6, u_top[j] + 1.0]
            u = Uo[:, j]
            req = np.where(u >= uo[0], np.interp(u, uo, ro), -np.inf)
            # E(u) = max over u' >= u of req(u') - (u' - u)
            E[:, j] = np.maximum.accumulate((req - u)[::-1])[::-1] + u
            if lip is not None:           # the lip underside, and a 45-degree chamfer under it
                dr, dyl = lip
                rr = np.linspace(0.0, self.W[j], 16)
                u0 = yb - (np.interp(rr, RHO, self.ylb[:, j]) + dyl)
                Ep = np.where(u[:, None] <= u0[None] + 1e-9, self.r_rim[j] + rr[None] + dr - (u0[None] - u[:, None]), -np.inf)
                E[:, j] = np.maximum(E[:, j], Ep.max(axis=1))
        E = np.maximum(E, self.r_bot[None] + 0.5)
        rings = [self.P(E[k], yb - Uo[k]) for k in range(M)]
        return loft(rings, cap_first=self.ctr(yb), cap_last=self.ctr(float((yb - u_top).mean())))

    def lip(self):
        """The rim lip, from just inside the cavity to its edge W past the rim,
        between its underside ylb and 0.3 mm above its top L (the front cut trims
        it to L). The underside dips 0.15 mm inside the edge so it overlaps the
        envelope's chamfer."""
        rho = np.linspace(0, 1, 14)[:, None] * (self.W[None] + 0.5) - 0.5            # (n, N)
        Lt = self.at(self.L, rho) - 0.3
        Lb = self.at(self.ylb, rho) + 0.15 * np.clip((self.W[None] - rho) / 0.2, 0, 1)
        rings = [self.P(self.r_rim + rho[k], Lt[k]) for k in range(len(rho))]
        rings += [self.P(self.r_rim + rho[k], Lb[k]) for k in range(len(rho) - 1, -1, -1)]
        return loft(rings, cyclic=True)

    def air(self):
        """The cavity: inside the bowl surface, carried straight forward past the face."""
        yfar = float(self.y_front.min()) - 15.0
        rings = [self.P(self.r_rim, np.full(self.N, yfar))] + [self.P(self.ri[k], self.yi[k]) for k in range(K)]
        return loft(rings, cap_first=self.ctr(yfar), cap_last=self.ctr(self.y_bot))

    def front_air(self, Y, rho_max):
        """Everything in front of the depth curve Y (len(RHO), N), for rim offsets
        -1.5 .. rho_max (a number, or one per angle), open straight forward."""
        yfar = float(self.y_front.min()) - 15.0
        if np.ndim(rho_max) == 0:
            m = RHO <= rho_max + 1e-9
            rho = np.repeat(RHO[m][:, None], self.N, 1); Yr = Y[m]
        else:
            rho = np.linspace(0, 1, 24)[:, None] * (np.asarray(rho_max)[None] + 1.0) - 1.0
            Yr = self.at(Y, rho)
        rings = [self.P(self.r_rim - 1.5, np.full(self.N, yfar))]
        rings += [self.P(self.r_rim + rho[k], Yr[k]) for k in range(len(rho))]
        rings += [self.P(self.r_rim + rho[-1], np.full(self.N, yfar))]
        return loft(rings, cyclic=True)


# ----------------------------------------------------------------------------- checks
def ray_thickness(t, pts, nrm, eps=2e-3, far=50.0, chunk=4000, opposite=False):
    """Distance from each point along -normal to where it leaves the solid
    (first hit of the mesh t). Points on the surface, normals outward. With
    opposite, also return the cosine between the exit face's normal and the
    ray (near 1 for a wall's opposite face, lower where it leaves through an
    edge or a corner)."""
    d = np.full(len(pts), far); cs = np.ones(len(pts))
    for i0 in range(0, len(pts), chunk):
        sl = slice(i0, i0 + chunk)
        org = pts[sl] - nrm[sl] * eps
        loc, ri, ti = t.ray.intersects_location(org, -nrm[sl], multiple_hits=True)
        if len(ri):
            dist = np.einsum('ij,ij->i', loc - org[ri], -nrm[sl][ri])
            ok = dist > 1e-4
            ri, ti, dist = ri[ok], ti[ok], dist[ok]
            o = np.lexsort((dist, ri)); ri, ti, dist = ri[o], ti[o], dist[o]
            first = np.r_[True, ri[1:] != ri[:-1]]
            ri, ti, dist = ri[first], ti[first], dist[first]
            d[i0 + ri] = dist + eps
            cs[i0 + ri] = np.einsum('ij,ij->i', t.face_normals[ti], -nrm[sl][ri])
    return (d, cs) if opposite else d


def near_surface(pts, other, dd, chunk=5000):
    """Mask: points within dd of the surface of Manifold `other`."""
    b = np.array(other.bounding_box())
    m = np.all((pts >= b[:3] - dd) & (pts <= b[3:] + dd), axis=1)
    idx = np.where(m)[0]
    q = trimesh.proximity.ProximityQuery(to_tri(other))
    out = np.zeros(len(pts), bool)
    for i0 in range(0, len(idx), chunk):
        ii = idx[i0:i0 + chunk]
        _, dist, _ = q.on_surface(pts[ii])
        out[ii] = dist <= dd
    return out


def surface_thickness(M, near=None, near_d=0.05, exclude=None, exclude_d=0.05, n_max=20000, seed=0):
    """Wall thickness of solid M at face centroids: optionally only faces within
    near_d of the surface of `near` (a Manifold), and not within exclude_d of
    `exclude`. Returns (thickness array, points, normals)."""
    t = to_tri(M)
    rng = np.random.default_rng(seed)
    b = np.array(near.bounding_box()) if near is not None else None
    w = t.area_faces.copy()
    if b is not None:      # area-weighted points on the faces near `near`'s box
        tc = t.triangles_center
        w[~np.all((tc >= b[:3] - 1.0) & (tc <= b[3:] + 1.0), axis=1)] = 0
    fi = rng.choice(len(w), 8 * n_max, p=w / w.sum())
    u = rng.random((len(fi), 2)); u = np.where(u.sum(1, keepdims=True) > 1, 1 - u, u)
    tri = t.triangles[fi]
    c = tri[:, 0] + u[:, :1] * (tri[:, 1] - tri[:, 0]) + u[:, 1:] * (tri[:, 2] - tri[:, 0])
    n = t.face_normals[fi]
    idx = np.arange(len(c))
    if near is not None:
        idx = idx[near_surface(c[idx], near, near_d)]
    if exclude is not None:
        idx = idx[~near_surface(c[idx], exclude, exclude_d)]
    if len(idx) > n_max:
        idx = rng.choice(idx, n_max, replace=False)
    d, cs = ray_thickness(t, c[idx], n[idx], opposite=True)
    return d, c[idx], n[idx], cs


# ----------------------------------------------------------------------------- the whole job
def dump(face, sockets, ctx, path):
    d = dict(face=_mesh(face), prof={k: s['prof'] for k, s in sockets.items()},
             ctx={k: _mesh(v) for k, v in ctx.items() if isinstance(v, mf.Manifold)},
             consts={k: v for k, v in ctx.items() if not isinstance(v, mf.Manifold)})
    with open(path, 'wb') as f:
        pickle.dump(d, f)


def load(path):
    with open(path, 'rb') as f:
        d = pickle.load(f)
    ctx = {k: _man(v) for k, v in d['ctx'].items()}
    ctx.update(d.get('consts', {}))
    return _man(d['face']), d['prof'], ctx


NAMES = dict(eyeL='liner_eye_L', eyeR='liner_eye_R', nasal='liner_nose')
REPORT = {}


class _Debug(dict):
    """Kept only with LINERS_DEBUG set (development); otherwise drops everything."""
    def __setitem__(self, k, v):
        if os.environ.get('LINERS_DEBUG'):
            dict.__setitem__(self, k, v)

    def setdefault(self, k, v):
        return dict.setdefault(self, k, v) if os.environ.get('LINERS_DEBUG') else v


DEBUG = _Debug()


def bowl_parts(B, face_t):
    """Liner, face cut and new face wall for one bowl."""
    B.set_face(B.sample_face(face_t))
    air = B.air()
    liner = union([B.envelope(T_WALL, 0.0, lip=(-0.03, -0.1)), B.lip()]) - B.front_air(B.L, RHO[-1]) - air
    if not B.flat:                        # screen aperture through the liner's base
        liner = liner - cyl(B.ctr(B.y_bot - 1.0), B.ctr(B.y_base + 1.0), float(B.r_bot[0]))
    # pocket: GAP round the bowl and the base; the 45-degree chamfer under the lip
    # is the seat (SEAT_GAP square to it, so the lip ends flush or 0.07 mm
    # proud), and the rebate leaves GAP round the lip's edge
    pocket = B.envelope(T_WALL + GAP, GAP, lip=(GAP, -GAP + SEAT_GAP * 1.414))
    rebate = B.front_air(B.ylb, B.W + B.G + 0.03)          # 0.03: no face coincident with the pocket
    cut = union([pocket, rebate])
    # new face wall behind the pocket, FACE_WALL thick, and BASE_T behind the
    # pocket's base (the clearance round the screen module cuts it back); behind
    # the rebate floor inside the rebate and 0.8 mm behind the face surface outside it
    Yw = np.where(RHO[:, None] <= B.W[None] + B.G[None] + 1e-9, B.ylb, np.maximum(B.yf_raw, B.L) + 0.8)
    # plus a collar under the face surface round the rim, out to COLLAR past it,
    # that ties the new wall back into the bone shell
    collar = B.front_air(Yw + COLLAR_T, COLLAR) - B.front_air(Yw, COLLAR)
    wall = union([B.envelope(T_WALL + GAP + FACE_WALL, GAP + BASE_T, lip=(GAP + FACE_WALL, -GAP)), collar]) - cut - B.front_air(Yw, RHO[-1]) - air
    gap = pocket - liner - air
    if not B.flat:
        gap = gap - cyl(B.ctr(B.y_bot - 1.0), B.ctr(B.y_base + 2.0), float(B.r_bot[0]))
    return liner, pocket, cut, wall, gap


OPPOSITE = 0.8      # a thickness sample counts when the ray leaves through a face within ~37 deg of square to it


def _stats(th, cs):
    w = cs >= OPPOSITE
    v = th[w] if w.any() else np.array([np.nan])
    return dict(min=round(float(v.min()), 2), p1=round(float(np.percentile(v, 1)), 2), median=round(float(np.median(v)), 2),
                samples=int(w.sum()), edge_samples=int((~w).sum()), under_1_2=int((v < 1.195).sum()))


def check_thickness(liners_, face, pockets, log):
    """Wall thickness by rays square into the part from its surface, counted
    where the ray leaves through the opposite wall (not where it runs out
    through an edge or a corner). Liner: the wall (everything but the lip) and
    the lip; face: every face of the pocket and the rebate."""
    rep = {}
    for k, (lm, B) in liners_.items():
        t = to_tri(lm)
        c, fi = trimesh.sample.sample_surface(t, 8000, seed=1)       # area-weighted points
        n = t.face_normals[fi]
        d = c - np.array([B.c[0], 0, B.c[1]])
        ang = np.arctan2(d[:, 2], d[:, 0]) % (2 * np.pi)
        j = np.round(ang / (2 * np.pi / B.N)).astype(int) % B.N
        rho = np.hypot(d[:, 0], d[:, 2]) - B.r_rim[j]
        ylb = np.array([np.interp(r_, RHO, B.ylb[:, jj]) for r_, jj in zip(rho, j)])
        # the lip and the chamfer seat under it, and the lip-thick top of the wall
        lip = (rho > T_WALL * B.kt[0, j] - 0.1) | (c[:, 1] < ylb + 0.1)
        th, cs = ray_thickness(t, c, n, opposite=True)
        rep[NAMES[k]] = dict(wall=_stats(th[~lip], cs[~lip]), lip=_stats(th[lip], cs[lip]))
        bad = (th < 0.8) & (cs >= OPPOSITE)
        DEBUG['thin_' + k] = (c[bad], n[bad], th[bad], lip[bad])
        w_ = np.where((~lip) & (cs >= OPPOSITE))[0]
        if len(w_):
            q = w_[np.argsort(th[w_])[:3]]
            rep[NAMES[k]]['worst_wall'] = [dict(angle_deg=round(float(np.degrees(ang[i])), 1), past_rim_mm=round(float(rho[i]), 2),
                                    below_rim_mm=round(float(c[i, 1] - B.L[np.searchsorted(RHO, 0.0), j[i]]), 2),
                                    t=round(float(th[i]), 2)) for i in q]
        r = rep[NAMES[k]]
        log('%s: wall min %.2f (1%% %.2f, median %.2f) mm over %d samples; lip min %.2f (median %.2f) mm'
            % (NAMES[k], r['wall']['min'], r['wall']['p1'], r['wall']['median'], r['wall']['samples'], r['lip']['min'], r['lip']['median']))
        log('   thinnest wall samples (angle, mm past the rim, mm below it, t): %s'
            % [(w['angle_deg'], w['past_rim_mm'], w['below_rim_mm'], w['t']) for w in r.get('worst_wall', [])])
    th, cs, rim = [], [], []
    thin_face = []
    worst = []
    for pk, (k_, (lm, B)) in zip(pockets, liners_.items()):
        th_, p_, n_, cs_ = surface_thickness(face, near=pk, near_d=0.05, n_max=3000)
        d = p_ - np.array([B.c[0], 0, B.c[1]])
        j_ = np.round((np.arctan2(d[:, 2], d[:, 0]) % (2 * np.pi)) / (2 * np.pi / B.N)).astype(int) % B.N
        rho = np.hypot(d[:, 0], d[:, 2]) - B.r_rim[j_]
        ylb = np.array([np.interp(r_, RHO, B.ylb[:, jj]) for r_, jj in zip(rho, j_)])
        # the slot's outer side beside the lip edge, and the rim zone (rebate
        # and seat, where the face's own rim edge runs out to a feather edge
        # wherever the bone falls away steeply or stands thin in front of the
        # rim) are the face's rim rather than wall behind the liner: reported apart
        L0 = B.L[np.searchsorted(RHO, 0.0), j_]
        side = ((rho > B.W[j_] + B.G[j_] - 0.1) & (p_[:, 1] < ylb + 0.05)) | (p_[:, 1] < L0 + RIM_ZONE)
        th.append(th_); cs.append(cs_); rim.append(side)
        bad = (th_ < 1.19) & (cs_ >= OPPOSITE)
        thin_face.append((p_[bad], n_[bad], th_[bad]))
        ok_ = (~side) & (cs_ >= OPPOSITE)
        for i in np.where(ok_)[0][np.argsort(th_[ok_])[:3]]:
            worst.append((round(float(th_[i]), 2), k_, round(float(np.degrees(np.arctan2(d[i, 2], d[i, 0]) % (2 * np.pi))), 1),
                          round(float(rho[i]), 2), round(float(p_[i, 1] - L0[i]), 2)))
    th = np.concatenate(th); cs = np.concatenate(cs); rim = np.concatenate(rim)
    rep['face_behind_pockets'] = _stats(th[~rim], cs[~rim])
    rep['face_rim_edge'] = _stats(th[rim], cs[rim])
    rep['face_behind_pockets']['worst'] = sorted(worst)[:5]
    DEBUG['thin_face'] = thin_face
    r = rep['face_behind_pockets']; r2 = rep['face_rim_edge']
    log('face behind the liners: min %.2f (1%% %.2f, median %.2f) mm over %d samples (%d edge samples left out); '
        'rim zone (first %.1f mm below the rim): min %.2f (1%% %.2f) mm over %d samples'
        % (r['min'], r['p1'], r['median'], r['samples'], r['edge_samples'], RIM_ZONE, r2['min'], r2['p1'], r2['samples']))
    log('   thinnest (t, socket, angle, mm past the rim, mm below it): %s' % r['worst'])
    return rep


def make_liners(face, sockets, ctx, log=print):
    if os.environ.get('LINERS_DUMP'):
        dump(face, sockets, ctx, os.environ['LINERS_DUMP'])
        if os.environ.get('LINERS_DUMP_EXIT'):
            raise SystemExit('liners: inputs dumped')
    if os.environ.get('LINERS_OFF'):
        return face, {}
    face_t = to_tri(face)
    parts, bowls, cuts, walls, pockets, gaps = {}, {}, [], [], [], []
    for k in ('eyeL', 'eyeR', 'nasal'):
        B = Bowl(k, sockets[k]['prof'] if 'prof' in sockets[k] else sockets[k],
                 ctx['y_nose_base'] if k == 'nasal' else ctx['y_eye_base'])
        liner, pocket, cut, wall, gap = bowl_parts(B, face_t)
        parts[NAMES[k]] = liner; bowls[k] = (liner, B)
        cuts.append(cut); walls.append(wall); pockets.append(pocket); gaps.append(gap)
    cut = union(cuts)
    keep_out = union([ctx[n] for n in ('eye_clear', 'corridor', 'radar_clear', 'radar_path') if n in ctx] + [cut])
    wall = union(walls)
    if 'skin' in ctx:
        wall = wall ^ ctx['skin']
    wall = wall - keep_out
    new = union([face - cut, wall])
    new, dropped = largest(new)

    if dropped > 1e-3:
        log('liners: the face cut-back left %.3f cm3 of loose fragments, dropped' % (dropped / 1000))
    for k in parts:
        parts[k], _ = largest(parts[k])
    # the checks measure the geometry before the pinch fill (its 0.3 mm cubes
    # would read as 0.3 mm walls)
    new = new.simplify(0.01)        # the lofts are dense; this halves the face's triangles round the sockets
    chk_face, chk_parts = new, dict(parts)
    new = fix_pinches(new, 'face', log)
    for k in parts:
        parts[k] = fix_pinches(parts[k], k, log)
    DEBUG['wall'] = wall; DEBUG['cut'] = cut
    for k, m in parts.items():
        log('%s: %.2f cm3' % (k, vol(m)))
    log('face: %.2f -> %.2f cm3 with the liner pockets and the new wall (%.2f cm3)' % (vol(face), vol(new), vol(wall)))
    rep = dict(volumes_cm3={k: round(vol(m), 2) for k, m in parts.items()}, face_cm3=[round(vol(face), 2), round(vol(new), 2)],
               lip_width_mm={NAMES[k]: [round(float(B.lip_w.min()), 2), round(float(B.lip_w.max()), 2)] for k, (_, B) in bowls.items()})
    clash = {}
    for k, m in parts.items():
        for n in ('modules', 'bar', 'radar', 'corridor', 'radar_path'):
            if n in ctx:
                clash['%s/%s' % (k, n)] = round(vol(m ^ ctx[n]), 4)
        clash['%s/face' % k] = round(vol(m ^ new), 4)
    rep['overlap_cm3'] = clash
    bad = {k: v for k, v in clash.items() if v > 0.001}
    log('liner overlaps (cm3) with face, eye modules, bar, radar, eye-bar path, radar path: %s' % (bad or 'none'))
    if os.environ.get('LINERS_SAVE_DIR'):          # skull-frame copies, for render_png outside the build
        os.makedirs(os.environ['LINERS_SAVE_DIR'], exist_ok=True)
        for k, m in dict(face=new, **parts).items():
            to_tri(m).export(os.path.join(os.environ['LINERS_SAVE_DIR'], k + '.stl'))
    if not os.environ.get('LINERS_NOCHECK'):
        rep.update(run_checks(chk_face, chk_parts, {k: (chk_parts[NAMES[k]], B) for k, (_, B) in bowls.items()},
                              pockets, gaps, ctx, log))
    REPORT.clear(); REPORT.update(rep)
    import gc
    gc.collect()
    return new, parts


def fix_pinches(M, name, log, size=0.3):
    """Booleans of these smooth, finely sampled surfaces leave vertices a few
    microns apart, which merge when the mesh is written as float32 (an STL)
    and pinch edges. Fill each with a 0.3 mm cube (union only, so it never
    opens a hole; the bump stays inside the 0.3 mm gap)."""
    rng = np.random.default_rng(0)
    n0 = None
    for it in range(8):
        t = to_tri(M)
        u, c = np.unique(t.edges_sorted, axis=0, return_counts=True)
        bad = u[c != 2]
        if n0 is None:
            n0 = len(bad)
        if not len(bad):
            break
        pts = t.vertices[bad].mean(axis=1)
        M = union([M] + [mf.Manifold.cube([size] * 3, True).rotate(list(rng.uniform(0, 90, 3))).translate(list(p)) for p in pts])
    if n0:
        log('%s: %d pinch edges filled with %.1f mm cubes%s' % (name, n0, size, '' if not len(bad) else ' (%d left)' % len(bad)))
    return largest(M)[0]


def largest(M):
    bodies = sorted(M.decompose(), key=lambda m: -m.volume())
    return bodies[0], sum(b.volume() for b in bodies[1:])


def sight_check(face, parts, bowls, gaps, ctx, log, n=4000, seed=2):
    """Lines of sight from in front of the face into each socket: none may end
    on a surface of the gap behind a liner (deeper than the lip's underside).
    Rays aim at random points over the rim opening and come in at up to 45
    degrees off the socket axis; the first hit on the face, the liners, the
    screen modules, the eye bar or the radar is what is seen."""
    rng = np.random.default_rng(seed)
    scene = [face] + list(parts.values()) + [ctx[k] for k in ('modules', 'bar', 'radar') if k in ctx]
    out = {}
    for (k, (lm, B)), gp in zip(bowls.items(), gaps):
        R_ = float(B.r_rim.max()) + 8.0           # the scene round this socket only
        box = mf.Manifold.cube([2 * R_, 70.0, 2 * R_]).translate([B.c[0] - R_, float(B.y_rim.min()) - 45.0, B.c[1] - R_])
        ms = [to_tri(m ^ box) for m in scene]
        nf = np.cumsum([0] + [len(m.faces) for m in ms])
        mi = len(parts) + 1                                    # the screen modules' faces (seen through the aperture)
        mod_idx = {k: np.arange(nf[mi], nf[mi + 1]) if 'modules' in ctx else np.array([], int)}
        t = trimesh.util.concatenate([m for m in ms if len(m.faces)])
        j = rng.integers(0, B.N, n)
        r = rng.random(n) * (B.r_rim[j] + B.W[j] + GAP + 1.0)
        tgt = np.stack([B.c[0] + r * B.ct[j], B.L[np.searchsorted(RHO, 0.0), j], B.c[1] + r * B.st[j]], 1)
        a = np.radians(45.0) * np.sqrt(rng.random(n)); phi = rng.random(n) * 2 * np.pi
        dirs = np.stack([np.sin(a) * np.cos(phi), np.cos(a), np.sin(a) * np.sin(phi)], 1)
        org = tgt - dirs * 40.0
        loc, ri, ti = t.ray.intersects_location(org, dirs, multiple_hits=False)
        q = trimesh.proximity.ProximityQuery(to_tri(gp))
        _, dist, _ = q.on_surface(loc)
        d = loc - np.array([B.c[0], 0, B.c[1]])
        jj = np.round((np.arctan2(d[:, 2], d[:, 0]) % (2 * np.pi)) / (2 * np.pi / B.N)).astype(int) % B.N
        rho = np.hypot(d[:, 0], d[:, 2]) - B.r_rim[jj]
        ylb = np.array([np.interp(r_, RHO, B.ylb[:, i_]) for r_, i_ in zip(rho, jj)])
        L0 = B.L[np.searchsorted(RHO, 0.0), jj]
        seam = (dist < 0.03) & (loc[:, 1] > ylb + 0.1) & (rho > 0.5)   # down the 0.3 mm seam, past the lip's underside
        # past the liner into the skull: a hit behind the liner's back face that is
        # not the screen (eye), or on the inside of the face beyond the seam
        behind = (loc[:, 1] > B.y_base + 0.05) & (np.hypot(d[:, 0], d[:, 2]) > float(np.max(B.r_bot)) + 0.05)
        if not B.flat:
            behind &= ~np.isin(ti, mod_idx[k])
        out[NAMES[k]] = dict(rays=int(len(loc)), seam=int(seam.sum()),
                             seam_depth_max=round(float((loc[seam, 1] - L0[seam]).max()) if seam.any() else 0.0, 2),
                             past_liner=int(behind.sum()))
        DEBUG['seen_' + k] = loc[seam]
    log('lines of sight (of %d per socket): %s' % (n, out))
    return out


def failures():
    """Check failures for the build report (empty when all is well)."""
    r = REPORT; out = []
    out += ['liner overlap %s %.3f cm3' % (k, v) for k, v in r.get('overlap_cm3', {}).items() if v > 0.005]
    out += ['line of sight past %s into the skull (%d rays)' % (k, v['past_liner']) for k, v in r.get('sight', {}).items() if v['past_liner'] > 0]
    for k in NAMES.values():
        if k in r and r[k]['wall']['min'] < MIN_LINER_WALL:
            out.append('%s wall %.2f mm < %.1f' % (k, r[k]['wall']['min'], MIN_LINER_WALL))
    f = r.get('face_behind_pockets')
    if f and f['min'] < MIN_FACE_HARD:
        out.append('face behind the liners %.2f mm < %.1f' % (f['min'], MIN_FACE_HARD))
    return out


# rotation into print orientation: the liner's flat back face (round the aperture
# or the radar window) on the bed, the opening up
PRINT_ROT = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0]], float)


# ----------------------------------------------------------------------------- picture
def render_png(face, parts, path, scad, log=print):
    """Front and 3/4 views of the face with its liners fitted (black), and a 3/4
    view with the liners pulled 30 mm forward, side by side in one PNG."""
    import subprocess, tempfile
    from PIL import Image
    tmp = tempfile.mkdtemp(prefix='liners_')
    to_tri(face).export(os.path.join(tmp, 'face.stl'))
    for k, m in parts.items():
        to_tri(m).export(os.path.join(tmp, k + '.stl'))

    def scene(dy):
        s = 'color("ivory") import("face.stl");\n'
        s += '\n'.join('translate([0,%g,0]) color([0.09,0.09,0.09]) import("%s.stl");' % (dy, k) for k in parts)
        f = os.path.join(tmp, 'scene_%d.scad' % abs(int(dy)))
        with open(f, 'w') as fh:
            fh.write(s)
        return f
    views = [(scene(0), '0,0,-14,90,0,0,330'), (scene(0), '0,0,-14,78,0,328,340'), (scene(-30), '0,-15,-14,72,0,320,380')]
    pngs, procs = [], []
    for i, (f, cam) in enumerate(views):
        out = os.path.join(tmp, 'v%d.png' % i); pngs.append(out)
        procs.append(subprocess.Popen([scad, '-o', out, '--preview', '--imgsize=900,900', '--camera=' + cam,
                                       '--projection=o', '--colorscheme=Tomorrow', f],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    for p in procs:
        p.wait()
    ims = [Image.open(p) for p in pngs if os.path.exists(p)]
    if not ims:
        log('liners: OpenSCAD render failed')
        return
    canvas = Image.new('RGB', (sum(im.width for im in ims), max(im.height for im in ims)), 'white')
    x = 0
    for im in ims:
        canvas.paste(im, (x, 0)); x += im.width
    canvas.save(path)
    log('wrote %s' % path)


# ----------------------------------------------------------------------------- checks in a child process
def run_checks(face, parts, bowls, pockets, gaps, ctx, log):
    """The thickness and sight checks cast many rays on big meshes; they run
    in a child process so the memory they take goes back to the system before
    the build carries on."""
    import subprocess, sys, tempfile, json
    tmp = tempfile.mkdtemp(prefix='liners_check_')
    src = os.path.join(tmp, 'in.pkl'); dst = os.path.join(tmp, 'out.json')
    with open(src, 'wb') as f:
        pickle.dump(dict(face=_mesh(face), parts={k: _mesh(m) for k, m in parts.items()},
                         bowls={k: (_mesh(lm), B) for k, (lm, B) in bowls.items()},
                         pockets=[_mesh(m) for m in pockets], gaps=[_mesh(m) for m in gaps],
                         ctx={k: _mesh(ctx[k]) for k in ('modules', 'bar', 'radar') if k in ctx}), f)
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), '--check', src, dst],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env=dict(os.environ, PYTHONWARNINGS='ignore'))
    for line in p.stdout:
        if line.strip():
            log(line.rstrip())
    if p.wait() != 0 or not os.path.exists(dst):
        raise RuntimeError('liners: the check process failed')
    with open(dst) as f:
        return json.load(f)


def _check_main(src, dst):
    import json
    with open(src, 'rb') as f:
        d = pickle.load(f)
    face = _man(d['face'])
    parts = {k: _man(v) for k, v in d['parts'].items()}
    bowls = {k: (_man(v), B) for k, (v, B) in d['bowls'].items()}
    ctx = {k: _man(v) for k, v in d['ctx'].items()}
    log = lambda *a: print(*a, flush=True)
    rep = check_thickness(bowls, face, [_man(v) for v in d['pockets']], log)
    rep['sight'] = sight_check(face, parts, bowls, [_man(v) for v in d['gaps']], ctx, log)
    with open(dst, 'w') as f:
        json.dump(rep, f, default=lambda o: o.item() if hasattr(o, 'item') else str(o))


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 4 and sys.argv[1] == '--check':
        _check_main(sys.argv[2], sys.argv[3])
