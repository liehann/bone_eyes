// JS port of src/eye_render.h (renderer) and the eye task in src/eyes.cpp
// (controller). Keep in step with those files; eye_core.test.js checks the
// renderer against the C++ output pixel-for-pixel.
// float32 maths (Math.fround) mirrors the C++ `float` arithmetic exactly.

(function (root) {
  const f = Math.fround;
  const OUT = 160;

  function clampf(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
  function clampi(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

  // art: {scleraW, scleraH, irisMapW, irisMapH, lidSize, irisW, irisH,
  //       irisMin, irisMax, sclera: Uint16Array, iris: Uint16Array,
  //       upper: Uint8Array, lower: Uint8Array, polar: Uint16Array}
  // track: {u: 128} per-eye lid smoothing state.
  function compute(a, gazeX, gazeY, lid, pupil, lidFlip, track) {
    const S = a.lidSize;
    const rangeX = a.scleraW - S, rangeY = a.scleraH - S;
    const p = {};
    p.scleraX0 = clampi(Math.trunc(f(f(f(clampf(f(gazeX), -1, 1) + 1) * f(0.5)) * rangeX)), 0, rangeX);
    p.scleraY0 = clampi(Math.trunc(f(f(f(clampf(f(gazeY), -1, 1) + 1) * f(0.5)) * rangeY)), 0, rangeY);

    const sx = clampi(Math.trunc(a.scleraW / 2) - Math.trunc(p.scleraX0 / 2), 0, S - 1);
    let sy = Math.trunc(a.scleraH / 2) - (p.scleraY0 + Math.trunc(a.irisH / 4));
    let n = 0;
    if (sy >= 0) {
      sy = clampi(sy, 0, S - 1);
      n = Math.trunc((a.upper[sy * S + sx] + a.upper[sy * S + (S - 1 - sx)]) / 2);
    }
    track.u = Math.trunc((track.u * 3 + n) / 4);
    let uT = f(track.u), lT = f(254 - track.u);
    lid = f(lid);
    if (lid >= f(0.75)) {
      const w = f(1 - clampf(f(f(lid - f(0.75)) / f(0.25)), 0, 1));
      uT = f(uT * w);
      lT = f(lT * w);
    } else {
      const c = f(clampf(lid, 0, 1) / f(0.75));
      uT = f(254 - f(f(254 - uT) * c));
      lT = f(254 - f(f(254 - lT) * c));
    }
    p.uThr = Math.trunc(uT);
    p.lThr = Math.trunc(lT);
    p.iScale = a.irisMin + Math.trunc(f(clampf(f(pupil), 0, 1) * (a.irisMax - a.irisMin)));
    p.lidFlip = lidFlip;
    return p;
  }

  const srcMaps = {};
  function srcMap(S) {
    if (!srcMaps[S]) {
      const m = new Uint8Array(OUT);
      for (let i = 0; i < OUT; i++) m[i] = Math.trunc(i * S / OUT);
      srcMaps[S] = m;
    }
    return srcMaps[S];
  }

  // Render output row oy as RGB565 into out (Uint16Array(160)).
  function row(a, p, oy, out) {
    const S = a.lidSize;
    const src = srcMap(S);
    const y = src[oy];
    const scleraY = p.scleraY0 + y;
    const irisY = scleraY - Math.trunc((a.scleraH - a.irisH) / 2);
    const irisOffX = Math.trunc((a.scleraW - a.irisW) / 2);
    const lidBase = y * S, scleraBase = scleraY * a.scleraW;
    const irisRow = irisY >= 0 && irisY < a.irisH;
    for (let ox = 0; ox < OUT; ox++) {
      const x = src[ox];
      const lidX = p.lidFlip ? S - 1 - x : x;
      let c;
      if (a.lower[lidBase + lidX] <= p.lThr || a.upper[lidBase + lidX] <= p.uThr) {
        c = 0;
      } else {
        const scleraX = p.scleraX0 + x;
        const irisX = scleraX - irisOffX;
        if (!irisRow || irisX < 0 || irisX >= a.irisW) {
          c = a.sclera[scleraBase + scleraX];
        } else {
          c = a.polar[irisY * a.irisW + irisX];
          const d = Math.trunc((p.iScale * (c & 0x7f)) / 128);
          if (d < a.irisMapH) {
            c = a.iris[d * a.irisMapW + Math.trunc((a.irisMapW * (c >> 7)) / 512)];
          } else {
            c = a.sclera[scleraBase + scleraX];
          }
        }
      }
      out[ox] = c;
    }
  }


  // --- fire: port of src/fire_render.h. tables = {quad, noiseW, radius,
  // angle, upBias (Int8Array), noise, palette (Uint16Array)} ---
  const FIRE_MOODS = [[72, 45, 185], [115, 95, 235], [100, 80, 225], [40, 20, 150]];
  const MOOD_INDEX = { idle: 0, alert: 1, talking: 2, goodbye: 3 };

  function FireState() { this.lastMs = 0; this.flowMilli = 0; this.len = 72 * 16; this.speed = 45; this.base = 185 * 16; }

  function fireCompute(lidArt, gazeX, gazeY, lid, pupil, lidFlip, track, mood, nowMs, s) {
    const p = {};
    p.lids = compute(lidArt, gazeX, gazeY, lid, pupil, lidFlip, track);
    p.cx = (OUT >> 1) - Math.trunc(f(clampf(f(gazeX), -1, 1) * f(30)));
    p.cy = (OUT >> 1) - Math.trunc(f(clampf(f(gazeY), -1, 1) * f(30)));
    p.pupilR = 8 + Math.trunc(f(clampf(f(pupil), 0, 1) * f(10)));
    const m = FIRE_MOODS[mood & 3];
    let dt = s.lastMs ? (nowMs - s.lastMs) >>> 0 : 0;
    if (dt > 200) dt = 200;
    s.lastMs = nowMs;
    s.len += Math.trunc((m[0] * 16 - s.len) / 8);
    s.base += Math.trunc((m[2] * 16 - s.base) / 8);
    s.speed += Math.trunc((m[1] - s.speed) / 4);
    s.flowMilli = (s.flowMilli + dt * s.speed) % 2048000;
    p.len = Math.trunc(s.len / 16);
    p.base = Math.trunc(s.base / 16);
    p.s1 = Math.trunc(s.flowMilli / 1000);
    p.s2 = Math.trunc(s.flowMilli * 3 / 2000);
    p.rot = Math.trunc(s.flowMilli / 8000);
    return p;
  }

  function fireRow(lidArt, t, p, oy, out) {
    const S = lidArt.lidSize, Q = t.quad, NW = t.noiseW;
    const src = srcMap(S);
    const lidBase = src[oy] * S;
    const uy = p.cy - oy, ay = uy < 0 ? -uy : uy;
    const L = p.lids;
    for (let ox = 0; ox < OUT; ox++) {
      const lx = src[ox];
      const lidX = L.lidFlip ? S - 1 - lx : lx;
      if (lidArt.lower[lidBase + lidX] <= L.lThr || lidArt.upper[lidBase + lidX] <= L.uThr) { out[ox] = 0; continue; }
      const dx = ox - p.cx, ax = dx < 0 ? -dx : dx;
      if (ax >= Q || ay >= Q) { out[ox] = 0; continue; }
      const r = t.radius[ay * Q + ax];
      if (r < p.pupilR) { out[ox] = 0; continue; }
      const a = t.angle[ay * Q + ax];
      let ang;
      if (dx >= 0) ang = uy >= 0 ? a : (256 - a) & 255;
      else ang = uy >= 0 ? 128 - a : 128 + a;
      const d = r - p.pupilR;
      const n1 = t.noise[((d - p.s1) & 63) * NW + ((ang + p.rot) & 255)];
      const n2 = t.noise[((d * 2 - p.s2) & 63) * NW + ((ang * 2 + 97 - p.rot) & 255)];
      const n = (n1 * 5 + n2 * 3) >> 3;
      let len = p.len + t.upBias[ang];
      if (len < 4) len = 4;
      let heat = p.base + Math.trunc(((n - 128) * 3) / 2) - Math.trunc((d * 255) / len);
      if (d < 4) heat += (4 - d) * 20;
      heat = heat < 0 ? 0 : heat > 255 ? 255 : heat;
      out[ox] = t.palette[heat];
    }
  }

  // --- flames + smoke overlay: port of src/flame_overlay.h ---
  const FLAME_MOODS = [[22, 210], [12, 250], [15, 240], [40, 170]];

  function Flames(seed) {
    this.heat = new Uint8Array(OUT * OUT);
    this.smoke = new Uint8Array(OUT * OUT);
    this.open = new Uint8Array(OUT * OUT);
    this.rng = (seed >>> 0) || 1;
    this.frame = 0;
  }
  Flames.prototype.next = function () {
    let x = this.rng;
    x = (x ^ (x << 13)) >>> 0;
    x = (x ^ (x >>> 17)) >>> 0;
    x = (x ^ (x << 5)) >>> 0;
    this.rng = x;
    return x;
  };
  Flames.prototype.step = function (lidArt, lids, mood, t) {
    const N = OUT, m = FLAME_MOODS[mood & 3], S = lidArt.lidSize, src = srcMap(S);
    const heat = this.heat, smoke = this.smoke, open = this.open;
    for (let y = 0; y < N; y++) {
      const ub = src[y] * S;
      for (let x = 0; x < N; x++) {
        const lx = lids.lidFlip ? S - 1 - src[x] : src[x];
        open[y * N + x] = (lidArt.lower[ub + lx] <= lids.lThr || lidArt.upper[ub + lx] <= lids.uThr) ? 0 : 1;
      }
    }
    this.frame = (this.frame + 1) >>> 0;
    for (let y = 0; y < N - 1; y++) {
      const hb = y * N, bb = hb + N, cb = ((y + this.frame) & 63) * t.noiseW;
      for (let x = 0; x < N; x++) {
        const r = this.next();
        let sx = x + (r % 3) - 1;
        sx = sx < 0 ? 0 : sx >= N ? N - 1 : sx;
        const cv = t.noise[cb + x];
        const c = ((cv * cv * m[0]) >>> 15) + ((r >>> 8) & 1);
        const v = heat[bb + sx] - c;
        heat[hb + x] = v < 0 ? 0 : v;
      }
    }
    for (let x = 0; x < N; x++) heat[(N - 1) * N + x] = 0;
    for (let i = 0; i < N * N; i++) {
      if (open[i]) {
        const v = m[1] - (this.next() & 31);
        heat[i] = v < 0 ? 0 : v;
      }
    }
    if (this.frame & 1) {
      const sway = (Math.floor(this.frame / 32) % 3) - 1;
      for (let y = 0; y < N - 1; y++) {
        const sb = y * N, bb = sb + N;
        for (let x = 0; x < N; x++) {
          let sx = x + sway;
          sx = sx < 0 ? 0 : sx >= N ? N - 1 : sx;
          const v = smoke[bb + sx] - (this.next() % 5);
          smoke[sb + x] = v < 0 ? 0 : v;
        }
      }
      for (let x = 0; x < N; x++) smoke[(N - 1) * N + x] = 0;
    }
    for (let i = 0; i < N * N; i++) {
      const h = heat[i];
      if (h > 20 && h < 60 && !open[i] && (this.next() & 15) === 0) {
        const v = smoke[i] + 70;
        smoke[i] = v > 120 ? 120 : v;
      }
    }
  };
  Flames.prototype.composite = function (t, y, row) {
    const N = OUT, base = y * N;
    for (let x = 0; x < N; x++) {
      const i = base + x;
      if (this.open[i]) continue;
      const fc = t.palette[this.heat[i]];
      const g = this.smoke[i] >> 1;
      let r5 = (fc >> 11) + (g >> 3), g6 = ((fc >> 5) & 63) + (g >> 2), b5 = (fc & 31) + (g >> 3);
      if (r5 > 31) r5 = 31;
      if (g6 > 63) g6 = 63;
      if (b5 > 31) b5 = 31;
      row[x] = (r5 << 11) | (g6 << 5) | b5;
    }
  };

  // --- fire eye (fire iris + its smoke): port of src/fire_eye.h ---
  const FIRE_EMIT = [[3, 110], [3, 110], [3, 110], [6, 100]];

  function fireHeat(t, p, ox, oy) {
    const Q = t.quad, NW = t.noiseW;
    const uy = p.cy - oy, ay = uy < 0 ? -uy : uy;
    const dx = ox - p.cx, ax = dx < 0 ? -dx : dx;
    if (ax >= Q || ay >= Q) return 0;
    const r = t.radius[ay * Q + ax];
    if (r < p.pupilR) return 0;
    const a = t.angle[ay * Q + ax];
    let ang;
    if (dx >= 0) ang = uy >= 0 ? a : (256 - a) & 255;
    else ang = uy >= 0 ? 128 - a : 128 + a;
    const d = r - p.pupilR;
    const n1 = t.noise[((d - p.s1) & 63) * NW + ((ang + p.rot) & 255)];
    const n2 = t.noise[((d * 2 - p.s2) & 63) * NW + ((ang * 2 + 97 - p.rot) & 255)];
    const n = (n1 * 5 + n2 * 3) >> 3;
    let len = p.len + t.upBias[ang];
    if (len < 4) len = 4;
    let h = p.base + Math.trunc(((n - 128) * 3) / 2) - Math.trunc((d * 255) / len);
    if (d < 4) h += (4 - d) * 20;
    return h < 0 ? 0 : h > 255 ? 255 : h;
  }

  function lidCovered(lidArt, L, ox, oy) {
    const S = lidArt.lidSize, src = srcMap(S);
    const ly = src[oy], lx = L.lidFlip ? S - 1 - src[ox] : src[ox];
    return lidArt.lower[ly * S + lx] <= L.lThr || lidArt.upper[ly * S + lx] <= L.uThr;
  }

  function FireEye(seed) {
    Flames.call(this, seed);
    this.cx = this.cy = OUT >> 1;
    this.coreR = 0;
  }
  FireEye.prototype.next = function () { return Flames.prototype.next.call(this); };
  FireEye.prototype.step = function (lidArt, fp, mood, t) {
    const N = OUT, heat = this.heat, smoke = this.smoke, open = this.open;
    for (let y = 0; y < N; y++) {
      for (let x = 0; x < N; x++) {
        heat[y * N + x] = fireHeat(t, fp, x, y);
        open[y * N + x] = lidCovered(lidArt, fp.lids, x, y) ? 0 : 1;
      }
    }
    this.frame = (this.frame + 1) >>> 0;
    this.cx = fp.cx; this.cy = fp.cy;
    this.coreR = fp.pupilR + Math.trunc(fp.len / 2);
    const R = this.coreR;
    if (this.frame & 1) {
      for (let y = 0; y < N - 1; y++) {
        const sb = y * N, bb = sb + N, dy = y - fp.cy;
        const swayB = ((y + (this.frame >>> 1)) & 63) * t.noiseW;
        for (let x = 0; x < N; x++) {
          const r = this.next();
          const dx = x - fp.cx, adx = dx < 0 ? -dx : dx, side = dx < 0 ? -1 : 1;
          const w = t.noise[swayB + ((x >> 3) & 255)];
          let sx = x + (w > 150 ? 1 : w < 106 ? -1 : 0);
          if (adx < R + 8 && dy > Math.trunc(-R / 2)) {
            sx = x - side;
            if (adx < Math.trunc(R / 2) && (r & 8)) sx -= side;
          } else if (adx < R + 12 && dy <= Math.trunc(-R / 2) && (r & 3) === 0) {
            sx = x + side;
          }
          if (sx < 1 || sx >= N - 1) { smoke[sb + x] = 0; continue; }
          const v = ((smoke[bb + sx - 1] + 2 * smoke[bb + sx] + smoke[bb + sx + 1]) >> 2) - (((r >>> 9) & 3) === 0 ? 1 : 0);
          smoke[sb + x] = v < 0 ? 0 : v;
        }
      }
      for (let x = 0; x < N; x++) smoke[(N - 1) * N + x] = 0;
    }
    const e = FIRE_EMIT[mood & 3], Q = t.quad;
    for (let y = 0; y < N; y++) {
      const dy = y - fp.cy, ady = dy < 0 ? -dy : dy;
      for (let x = 0; x < N; x++) {
        const i = y * N + x;
        const dx = x - fp.cx, adx = dx < 0 ? -dx : dx;
        if (adx < Q && ady < Q && t.radius[ady * Q + adx] < R) { smoke[i] = 0; continue; }
        const h = heat[i];
        if (h > 25 && h < 60 && (this.next() & 63) < e[0]) {
          const v = smoke[i] + e[1];
          smoke[i] = v > 160 ? 160 : v;
        }
      }
    }
  };
  FireEye.prototype.row = function (t, y, out) {
    const N = OUT;
    for (let x = 0; x < N; x++) {
      const i = y * N + x;
      const h = this.open[i] ? this.heat[i] : 0;
      const f = t.palette[h];
      let g = h < 40 ? Math.trunc(this.smoke[i] * 3 / 4) : 0;
      if (h) g = Math.trunc(g * (40 - h) / 40);
      const r5 = (f >> 11) + (g >> 3), g6 = ((f >> 5) & 63) + (Math.trunc(g * 7 / 8) >> 2),
            b5 = (f & 31) + (Math.trunc(g * 3 / 4) >> 3);
      out[x] = ((r5 > 31 ? 31 : r5) << 11) | ((g6 > 63 ? 63 : g6) << 5) | (b5 > 31 ? 31 : b5);
    }
  };

  // --- controller: port of eyeTask() in src/eyes.cpp ---
  const MOOD = {
    idle: { lid: 0.72, pupil: 0.45 },
    alert: { lid: 1.0, pupil: 0.85 },
    talking: { lid: 0.9, pupil: 0.7 },
    goodbye: { lid: 0.45, pupil: 0.3 },
  };
  const TRACK_TIMEOUT_MS = 1000, BLINK_MS = 160;

  function frand(lo, hi) { return lo + (hi - lo) * Math.random(); }
  function approach(cur, target, dt, tau) { return cur + (target - cur) * (1 - Math.exp(-dt / tau)); }

  function Controller(nowMs) {
    this.mood = 'idle';
    this.target = null;   // {x, y, cm, ms}
    this.held = null;     // {x, y}
    this.blinkReq = false;
    this.gx = 0; this.gy = 0; this.sx = 0; this.sy = 0;
    this.lid = 0.75; this.pupil = 0.5; this.verge = 0;
    this.nextSaccade = 0; this.nextBlink = nowMs + 2000; this.blinkStart = 0;
    this.last = nowMs;
  }
  Controller.prototype.lookAt = function (x, y, cm, nowMs) {
    this.target = { x: clampf(x, -1, 1), y: clampf(y, -1, 1), cm: cm || 0, ms: nowMs };
  };
  Controller.prototype.step = function (now) {
    const dt = (now - this.last) / 1000;
    this.last = now;
    const tracking = this.target && now - this.target.ms < TRACK_TIMEOUT_MS;
    let tx, ty, tau;
    if (this.held) {
      tx = this.held.x; ty = this.held.y; tau = 0.05;
    } else if (tracking) {
      tx = this.target.x; ty = this.target.y; tau = 0.08;
    } else {
      if (now >= this.nextSaccade) {
        const r = Math.random() < 0.2 ? 0.9 : 0.45;
        this.sx = frand(-r, r);
        this.sy = frand(-r, r) * 0.6;
        this.nextSaccade = now + frand(400, this.mood === 'idle' ? 3000 : 1200);
      }
      tx = this.sx; ty = this.sy; tau = 0.03;
    }
    this.gx = approach(this.gx, tx, dt, tau);
    this.gy = approach(this.gy, ty, dt, tau);
    const wantVerge = tracking && this.target.cm > 0 ? clampf(30 / this.target.cm, 0, 0.25) : 0;
    this.verge = approach(this.verge, wantVerge, dt, 0.2);

    const m = MOOD[this.mood];
    this.lid = approach(this.lid, m.lid, dt, 0.15);
    this.pupil = approach(this.pupil, m.pupil, dt, 0.3);

    if (this.blinkReq || now >= this.nextBlink) {
      this.blinkReq = false;
      this.blinkStart = now;
      this.nextBlink = now + frand(2000, 6000);
    }
    let blinkLid = this.lid;
    if (this.blinkStart && now - this.blinkStart < BLINK_MS) {
      const p = (now - this.blinkStart) / BLINK_MS;
      blinkLid = this.lid * Math.abs(1 - 2 * p);
    }
    const base = { gazeY: this.gy, lid: blinkLid, pupil: this.pupil, mood: this.mood };
    return {
      left: Object.assign({ gazeX: clampf(this.gx + this.verge, -1, 1) }, base),
      right: Object.assign({ gazeX: clampf(this.gx - this.verge, -1, 1) }, base),
      tracking: !!tracking,
    };
  };

  const api = { OUT, compute, row, Controller, MOOD, FireState, fireCompute, fireRow, MOOD_INDEX, Flames, FireEye };
  if (typeof module !== 'undefined') module.exports = api;
  else root.EyeCore = api;
})(this);
