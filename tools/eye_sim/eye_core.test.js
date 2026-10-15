// node eye_core.test.js <artdir>   (artdir from dump_art; build.py runs this)
// Renders the dump_art test poses in JS and compares FNV-1a checksums with the
// firmware renderer's.
const fs = require('fs');
const path = require('path');
const { compute, row, OUT } = require('./eye_core.js');

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
for (const m of meta) {
  const a = load(m);
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
process.exit(failed ? 1 : 0);
