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

  const api = { OUT, compute, row, Controller, MOOD };
  if (typeof module !== 'undefined') module.exports = api;
  else root.EyeCore = api;
})(this);
