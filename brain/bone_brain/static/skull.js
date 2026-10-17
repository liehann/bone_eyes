// Skull preview: the firmware's eye renderer (tools/eye_sim/eye_core.js, the
// pixel-identical JS port) drawing both LCD eyes into the sockets, plus a jaw
// that follows the brain's jaw level. Driven by window.Skull.* from index.html.
(function () {
  const W = 400, H = 470;
  const SOCKETS = [{ cx: 138, cy: 188 }, { cx: 262, cy: 188 }];  // viewer's left, right
  const SOCKET_R = 64, EYE_R = 52, JAW_TRAVEL = 46;

  const host = document.getElementById('skullView');
  host.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" class="skull-svg" aria-label="skull preview">
      <defs>
        <radialGradient id="bone" cx="50%" cy="35%" r="70%">
          <stop offset="0" stop-color="#efe6d6"/><stop offset=".7" stop-color="#d6cab4"/><stop offset="1" stop-color="#a8997f"/>
        </radialGradient>
        <linearGradient id="jawBone" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#dcd0ba"/><stop offset="1" stop-color="#a4957c"/>
        </linearGradient>
      </defs>
      <!-- mouth cavity, revealed as the jaw drops -->
      <path d="M128 322 h144 v70 q-72 18 -144 0z" fill="#0b0807"/>
      <g id="jawGroup">
        <path d="M92 300 Q92 392 150 428 Q200 452 250 428 Q308 392 308 300 L286 300 Q284 330 268 334 L132 334 Q116 330 114 300 Z"
              fill="url(#jawBone)" stroke="#7d705c" stroke-width="2"/>
        <g fill="#f2ead9" stroke="#8a7f70" stroke-width="1.5">
          ${Array.from({ length: 10 }, (_, i) => `<rect x="${134 + i * 13.2}" y="330" width="12" height="22" rx="3"/>`).join('')}
        </g>
      </g>
      <path d="M200 18 C92 18 36 96 36 192 C36 248 58 288 96 308 L100 330 Q200 344 300 330 L304 308 C342 288 364 248 364 192 C364 96 308 18 200 18 Z"
            fill="url(#bone)" stroke="#7d705c" stroke-width="2.5"/>
      <path d="M78 248 Q100 268 118 262 M322 248 Q300 268 282 262" stroke="#9c8e76" stroke-width="2" fill="none"/>
      ${SOCKETS.map(s => `<circle cx="${s.cx}" cy="${s.cy}" r="${SOCKET_R}" fill="#0b0807" stroke="#8a7d68" stroke-width="3"/>`).join('')}
      <path d="M200 236 L183 278 Q200 290 217 278 Z" fill="#1a1411"/>
      <g fill="#f2ead9" stroke="#8a7f70" stroke-width="1.5">
        ${Array.from({ length: 10 }, (_, i) => `<rect x="${134 + i * 13.2}" y="304" width="12" height="26" rx="3"/>`).join('')}
      </g>
    </svg>
    ${SOCKETS.map((s, i) => `<canvas class="eye-cv" id="eyeCv${i}" width="160" height="160"
       style="left:${(s.cx - EYE_R) / W * 100}%;top:${(s.cy - EYE_R) / H * 100}%;width:${2 * EYE_R / W * 100}%"></canvas>`).join('')}
    <div class="skull-note" id="skullNote"></div>`;
  host.style.aspectRatio = `${W} / ${H}`;
  const jawGroup = document.getElementById('jawGroup');
  const note = document.getElementById('skullNote');

  let jawTarget = 0, jaw = 0, mood = 'idle', present = false, style = 'fire', ready = false;

  window.Skull = {
    setJaw(v) { jawTarget = Math.max(0, Math.min(1, v)); },
    setState(state) {
      mood = { idle: 'idle', 'warming up': 'idle', greeting: 'alert', listening: 'alert', thinking: 'alert',
               speaking: 'talking', goodbye: 'goodbye' }[state] || 'idle';
    },
    setPresent(p) { present = p; },
    setStyle(s) { if (['fire', 'default', 'dragon'].includes(s)) style = s; },
    blink() { if (ctl) ctl.blinkReq = true; },
  };

  // Jaw: the servo can't move instantly; ease toward the target like it would.
  function stepJaw() {
    jaw += (jawTarget - jaw) * 0.45;
    jawGroup.setAttribute('transform', `translate(0 ${(jaw * JAW_TRAVEL).toFixed(1)})`);
  }

  let ctl = null;
  if (!window.EyeCore) {
    note.textContent = 'Eye renderer not loaded';
  } else {
    fetch('/eye_art.json').then(r => {
      if (!r.ok) throw new Error('eye art missing: run tools/eye_sim/build.py');
      return r.json();
    }).then(start).catch(e => { note.textContent = String(e.message || e); });
  }

  function b64(data) {
    const bin = atob(data), u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return u8;
  }

  function start(data) {
    const { compute, row, Controller, OUT, FireState, fireCompute, MOOD_INDEX, FireEye } = EyeCore;
    const arts = {};
    data.arts.forEach(m => {
      const u8 = b64(m.data);
      let o = 0;
      const take = (T, n) => { const v = new T(u8.buffer, o, n); o += n * T.BYTES_PER_ELEMENT; return v; };
      arts[m.name] = Object.assign({}, m, {
        sclera: take(Uint16Array, m.scleraW * m.scleraH), iris: take(Uint16Array, m.irisMapW * m.irisMapH),
        upper: take(Uint8Array, m.lidSize * m.lidSize), lower: take(Uint8Array, m.lidSize * m.lidSize),
        polar: take(Uint16Array, m.irisW * m.irisH),
      });
    });
    const F = data.fire, u8 = b64(F.data);
    let o = 0;
    const take = (T, n) => { const v = new T(u8.buffer, o, n); o += n * T.BYTES_PER_ELEMENT; return v; };
    const q2 = F.quad * F.quad;
    const fireT = Object.assign({}, F, {
      radius: take(Uint8Array, q2), angle: take(Uint8Array, q2), upBias: take(Int8Array, 256),
      noise: take(Uint8Array, F.noiseW * F.noiseH), palette: take(Uint16Array, 256),
    });
    const lut = new Uint32Array(65536);
    for (let c = 0; c < 65536; c++) {
      const r = ((c >> 11) & 31) * 255 / 31 | 0, g = ((c >> 5) & 63) * 255 / 63 | 0, b = (c & 31) * 255 / 31 | 0;
      lut[c] = 0xff000000 | (b << 16) | (g << 8) | r;
    }
    // Firmware: eye "L" is the skull's own left = viewer's right (lid flip false);
    // "R" = viewer's left (lid flip true).
    const eyes = [
      { cv: document.getElementById('eyeCv1'), flip: false, seed: 0x9E3779B9 },
      { cv: document.getElementById('eyeCv0'), flip: true, seed: 0x9E3779BA },
    ];
    eyes.forEach(e => {
      e.ctx = e.cv.getContext('2d');
      e.img = e.ctx.createImageData(OUT, OUT);
      e.px = new Uint32Array(e.img.data.buffer);
      e.track = { u: 128 };
      e.fire = new FireState();
      e.fireEye = new FireEye(e.seed);
      e.style = style;
    });
    const rowBuf = new Uint16Array(OUT);
    function draw(e, st, now) {
      if (e.style !== style) {  // firmware resets the effect buffers on a style change
        e.style = style;
        e.fireEye = new FireEye(e.seed);
      }
      const fire = style === 'fire';
      const art = style === 'dragon' ? arts.dragon : arts.default;
      const m = MOOD_INDEX[st.mood];
      let p;
      if (fire) {
        const fp = fireCompute(art, st.gazeX, st.gazeY, st.lid, st.pupil, e.flip, e.track, m, Math.floor(now) >>> 0, e.fire);
        e.fireEye.step(art, fp, m, fireT);
      } else {
        p = compute(art, st.gazeX, st.gazeY, st.lid, st.pupil, e.flip, e.track);
      }
      for (let y = 0; y < OUT; y++) {
        if (fire) e.fireEye.row(fireT, y, rowBuf);
        else row(art, p, y, rowBuf);
        const base = y * OUT;
        for (let x = 0; x < OUT; x++) e.px[base + x] = lut[rowBuf[x]];
      }
      e.ctx.putImageData(e.img, 0, 0);
    }
    ctl = new Controller(performance.now());
    ready = true;
    let last = 0;
    function loop(now) {
      requestAnimationFrame(loop);
      stepJaw();
      if (now - last < 1000 / 30) return;  // ~what the ESP32 manages
      last = now;
      ctl.mood = mood;
      if (present) ctl.lookAt(0, -0.15, 100, now);  // look at the visitor, slightly down
      const s = ctl.step(now);
      draw(eyes[0], s.left, now);
      draw(eyes[1], s.right, now);
    }
    requestAnimationFrame(loop);
  }
  // Jaw still animates if the eyes can't load.
  (function jawOnly() { if (!ready) { stepJaw(); requestAnimationFrame(jawOnly); } })();
})();
