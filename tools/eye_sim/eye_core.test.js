// node eye_core.test.js <artdir>   (artdir from dump_art; build.py runs this)
// Renders the dump_art test poses in JS and compares FNV-1a checksums with the
// firmware renderer's.
const fs = require('fs');
const path = require('path');
const { compute, row, OUT, FireState, fireCompute, fireRow, Flames } = require('./eye_core.js');

const dir = process.argv[2];
const meta = JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf8'));
const poses = [[0, 0, 0.72, 0.45, 0], [1, 0, 0.72, 0.45, 1], [-0.6, 0.4, 1.0, 0.9, 0],
               [0.3, -1, 0.45, 0.3, 1], [0, 0, 0.2, 0.5, 0]];

function load(m) {
  const buf = fs.readFileSync(path.join(dir, m.name + '.bin'));
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length);
  let o = 0;
  const take = (Type, n) => { const v = new Type(ab, o, n); o += n * Type.BYTES_PER_ELEMENT; return v; };
  return Object.assign({}, m, {
    sclera: take(Uint16Array, m.scleraW * m.scleraH),
    iris: take(Uint16Array, m.irisMapW * m.irisMapH),
    upper: take(Uint8Array, m.lidSize * m.lidSize),
    lower: take(Uint8Array, m.lidSize * m.lidSize),
    polar: take(Uint16Array, m.irisW * m.irisH),
  });
}

let failed = 0;
const loaded = {};
for (const m of meta) {
  const a = load(m);
  loaded[m.name] = a;
  poses.forEach((q, k) => {
    const track = { u: 128 };
    let p;
    for (let i = 0; i < 5; i++) p = compute(a, q[0], q[1], q[2], q[3], !!q[4], track);
    let h = 2166136261 >>> 0;
    const out = new Uint16Array(OUT);
    for (let y = 0; y < OUT; y++) {
      row(a, p, y, out);
      for (let x = 0; x < OUT; x++) h = Math.imul(h ^ out[x], 16777619) >>> 0;
    }
    const ok = h === m.checksums[k];
    if (!ok) failed++;
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${m.name} pose ${k}: js ${h} c++ ${m.checksums[k]}`);
  });
}
function loadFire() {
  const fm = JSON.parse(fs.readFileSync(path.join(dir, 'fire.json'), 'utf8'));
  const buf = fs.readFileSync(path.join(dir, 'fire.bin'));
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length);
  let o = 0;
  const take = (Type, n) => { const v = new Type(ab, o, n); o += n * Type.BYTES_PER_ELEMENT; return v; };
  const q2 = fm.quad * fm.quad;
  return Object.assign(fm, {
    radius: take(Uint8Array, q2), angle: take(Uint8Array, q2), upBias: take(Int8Array, 256),
    noise: take(Uint8Array, fm.noiseW * fm.noiseH), palette: take(Uint16Array, 256),
  });
}
// Uint16Array needs 2-byte alignment: q2*2 + 256 + 16384 is even, so it is.
const fire = loadFire();
poses.forEach((q, k) => {
  const st = new FireState();
  const track = { u: 128 };
  let p;
  for (let n = 0, t = 1000; n < 40; n++, t += 17 + (n * 7) % 23)
    p = fireCompute(loaded.default, q[0], q[1], q[2], q[3], !!q[4], track, k, t, st);
  let h = 2166136261 >>> 0;
  const out = new Uint16Array(OUT);
  for (let y = 0; y < OUT; y++) {
    fireRow(loaded.default, fire, p, y, out);
    for (let x = 0; x < OUT; x++) h = Math.imul(h ^ out[x], 16777619) >>> 0;
  }
  const ok = h === fire.checksums[k];
  if (!ok) failed++;
  console.log(`${ok ? 'ok  ' : 'FAIL'} fire pose ${k}: js ${h} c++ ${fire.checksums[k]}`);
});
poses.forEach((q, k) => {
  const a = k & 1 ? loaded.dragon : loaded.default;
  const fl = new Flames(12345 + k);
  const track = { u: 128 };
  let p;
  for (let n = 0; n < 50; n++) {
    p = compute(a, q[0], q[1], q[2], q[3], !!q[4], track);
    fl.step(a, p, k, fire);
  }
  let h = 2166136261 >>> 0;
  const out = new Uint16Array(OUT);
  for (let y = 0; y < OUT; y++) {
    row(a, p, y, out);
    fl.composite(fire, y, out);
    for (let x = 0; x < OUT; x++) h = Math.imul(h ^ out[x], 16777619) >>> 0;
  }
  const ok = h === fire.flameChecksums[k];
  if (!ok) failed++;
  console.log(`${ok ? 'ok  ' : 'FAIL'} flames pose ${k}: js ${h} c++ ${fire.flameChecksums[k]}`);
});
process.exit(failed ? 1 : 0);
