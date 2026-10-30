#!/usr/bin/env python3
"""Build the v2 mock-up viewer: viewer/index.html, one self-contained page
(three.js is inlined from three.min.js next to this file, geometry is base64 raw
arrays), so it works from file:// with no network.

Reads proto/out/*.stl and proto/out/meta.json (run proto/mockup.py first).

    hardware/.venv/bin/python hardware/skull_v2/viewer/make_viewer.py [--open]
"""
import argparse, base64, json, os, subprocess
import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'proto', 'out')

GROUPS = [('shells', 'Shells and liners'), ('chassis', 'Chassis and brackets'),
          ('hardware', 'Hardware'), ('jaw', 'Jaw')]


def pack(arr):
    return base64.b64encode(np.ascontiguousarray(arr).tobytes()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--open', action='store_true')
    a = ap.parse_args()
    meta = json.load(open(os.path.join(OUT, 'meta.json')))
    for p in meta['parts']:
        m = trimesh.load(os.path.join(OUT, p['name'] + '.stl'), force='mesh')
        m.merge_vertices()
        p['pos'] = pack(m.vertices.astype(np.float32))
        p['idx'] = pack(m.faces.astype(np.uint32))
    meta['groups'] = GROUPS
    three = open(os.path.join(HERE, 'three.min.js')).read().replace('</script', '<\\/script')
    html = TEMPLATE.replace('/*__THREE__*/', three).replace('/*__META__*/null', json.dumps(meta))
    path = os.path.join(HERE, 'index.html')
    open(path, 'w').write(html)
    print('wrote %s (%.1f MB)' % (path, len(html) / 1e6))
    if a.open:
        subprocess.call(['open', path])


TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Skull v2 mock-up</title>
<style>
:root{--bg:#111317;--fg:#e6e6e6;--dim:#8a919c;--acc:#e8c27a;--line:#2c313a}
html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font:13px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow:hidden}
body{display:flex}
#panel{flex:none;width:270px;height:100%;overflow:auto;background:#16191e;border-right:1px solid var(--line);padding:10px 12px;box-sizing:border-box}
#view{position:relative;flex:1;min-width:0}
canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
h1{font-size:14px;margin:0 0 6px}
h2{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);margin:12px 0 4px;display:flex;justify-content:space-between}
h2 button{font-size:10px;padding:1px 6px}
label{display:flex;align-items:center;gap:6px;padding:1px 0;cursor:pointer}
.sw{width:10px;height:10px;border-radius:2px;border:1px solid #0006;flex:none}
button{background:#2a2f38;color:var(--fg);border:1px solid #3a404b;border-radius:4px;padding:3px 8px;cursor:pointer;font:inherit}
button:hover{background:#353b46}
.row{display:flex;gap:5px;flex-wrap:wrap;margin:5px 0}
.ctl{margin:7px 0}.ctl div{display:flex;justify-content:space-between;color:var(--dim)}
input[type=range]{width:100%;accent-color:var(--acc)}
#step{position:absolute;left:50%;top:12px;transform:translateX(-50%);background:#1b1e24ee;border:1px solid var(--line);border-radius:8px;padding:6px 14px;max-width:70%;text-align:center}
#step b{color:var(--acc)}
#tip{position:absolute;right:12px;bottom:10px;color:var(--dim);font-size:11px}
@media(max-width:700px){body{flex-direction:column}#panel{width:100%;height:auto;max-height:42%;border-right:0;border-bottom:1px solid var(--line)}}
</style></head><body>
<div id="panel">
<h1>Skull v2 mock-up</h1>
<div style="color:var(--dim)">Rough layout only. Not printable geometry.</div>
<h2>View</h2>
<div class="row" id="views"></div>
<div class="ctl"><div><span>Shell opacity</span><span id="opv">100%</span></div><input id="op" type="range" min="0.05" max="1" step="0.01" value="1"></div>
<label><input type="checkbox" id="cut"> Cut at x = 0 (see inside)</label>
<div class="ctl"><div><span>Explode</span><span id="exv">0%</span></div><input id="ex" type="range" min="0" max="1" step="0.01" value="0"></div>
<div class="ctl"><div><span>Assembly step</span><span id="stv"></span></div><input id="st" type="range" min="1" step="1"></div>
<div class="row"><button id="stprev">&lt; Prev</button><button id="stnext">Next &gt;</button><button id="stall">All</button></div>
<h2>Extras</h2>
<label><input type="checkbox" id="x_wires" checked><span class="sw" style="background:#ff9f1c"></span>Wires</label>
<label><input type="checkbox" id="x_screws" checked><span class="sw" style="background:#ff2fb4"></span>Screws</label>
<label><input type="checkbox" id="x_seam" checked><span class="sw" style="background:#ff2020"></span>Seam band (y = 100)</label>
<div id="parts"></div>
</div>
<div id="view"><canvas id="c"></canvas><div id="step"></div><div id="tip">drag: orbit &middot; right-drag: pan &middot; wheel: zoom</div></div>
<script>/*__THREE__*/</script>
<script>
const META = /*__META__*/null;
const T = THREE, STEPS = META.steps, NS = STEPS.length;
const b64 = s => { const b = atob(s), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u.buffer; };
const canvas = document.getElementById('c');
const renderer = new T.WebGLRenderer({canvas, antialias:true, preserveDrawingBuffer:true});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setClearColor(0x111317);
renderer.localClippingEnabled = true;
const scene = new T.Scene();
const camera = new T.PerspectiveCamera(28, 1, 5, 4000); camera.up.set(0,0,1);
scene.add(new T.HemisphereLight(0xffffff, 0x555560, 0.75));
const head = new T.DirectionalLight(0xffffff, 0.85); scene.add(head);
const clip = new T.Plane(new T.Vector3(-1,0,0), 0);   // keeps x <= 0 when active
const items = [];   // {obj, step, group, name, ex:Vector3, kind}

META.parts.forEach(p => {
  const g = new T.BufferGeometry();
  g.setAttribute('position', new T.BufferAttribute(new Float32Array(b64(p.pos)), 3));
  g.setIndex(new T.BufferAttribute(new Uint32Array(b64(p.idx)), 1));
  if (!p.flat) g.computeVertexNormals();
  const mat = new T.MeshStandardMaterial({color:p.color, roughness:0.75, metalness:0.0, flatShading:p.flat,
    side: T.DoubleSide, transparent:false});
  const m = new T.Mesh(g, mat);
  scene.add(m);
  items.push({obj:m, step:p.step, group:p.group, name:p.name, label:p.label, color:p.color, ex:new T.Vector3(...p.explode), kind:'part', shell:p.shell, on:true});
});
META.lines.forEach(l => {
  const pts = l.pts.map(q => new T.Vector3(...q));
  const path = new T.CurvePath();
  for (let i = 0; i < pts.length - 1; i++) path.add(new T.LineCurve3(pts[i], pts[i+1]));
  const seg = Math.max(4, (pts.length - 1) * (pts.length > 8 ? 1 : 4));
  const g = new T.TubeGeometry(path, seg, l.r, 6, false);
  const mat = new T.MeshStandardMaterial({color:l.color, roughness:0.5, emissive:l.color, emissiveIntensity:0.25});
  const m = new T.Mesh(g, mat); scene.add(m);
  items.push({obj:m, step:l.step, group:l.group, name:l.id, ex:new T.Vector3(...l.explode), kind:'line', on:true});
});

// ---- UI
const $ = id => document.getElementById(id);
const partsDiv = $('parts');
META.groups.forEach(([gid, gl]) => {
  const list = items.filter(i => i.kind === 'part' && i.group === gid);
  if (!list.length) return;
  const h = document.createElement('h2'); h.innerHTML = '<span>' + gl + '</span>'; partsDiv.appendChild(h);
  list.forEach(i => {
    const lab = document.createElement('label');
    lab.innerHTML = '<input type="checkbox" checked><span class="sw" style="background:' + i.color + '"></span>' + i.label;
    lab.querySelector('input').onchange = e => { i.on = e.target.checked; update(); };
    i.cb = lab.querySelector('input'); partsDiv.appendChild(lab);
  });
});
const ex = $('ex'), op = $('op'), st = $('st');
st.max = NS; st.value = NS;
['x_wires','x_screws','x_seam','cut'].forEach(id => $(id).onchange = update);
ex.oninput = op.oninput = st.oninput = update;
$('stprev').onclick = () => { st.value = Math.max(1, +st.value - 1); update(); };
$('stnext').onclick = () => { st.value = Math.min(NS, +st.value + 1); update(); };
$('stall').onclick = () => { st.value = NS; update(); };

function update() {
  const e = +ex.value, o = +op.value, s = +st.value, cut = $('cut').checked;
  $('exv').textContent = Math.round(e*100) + '%'; $('opv').textContent = Math.round(o*100) + '%';
  $('stv').textContent = s + ' / ' + NS;
  $('step').innerHTML = s === NS ? '<b>Step ' + NS + ' / ' + NS + '</b> ' + STEPS[NS-1] : '<b>Step ' + s + ' / ' + NS + '</b> ' + STEPS[s-1];
  items.forEach(i => {
    let vis = i.step <= s;
    if (i.kind === 'part') vis = vis && i.on;
    else if (i.group === 'wires') vis = vis && $('x_wires').checked;
    else if (i.group === 'screws') vis = vis && $('x_screws').checked;
    else if (i.group === 'seam') vis = vis && $('x_seam').checked;
    i.obj.visible = vis;
    const sc = i.group === 'seam' ? 0 : e;
    i.obj.position.copy(i.ex).multiplyScalar(sc);
    const m = i.obj.material;
    m.clippingPlanes = cut && i.group !== 'seam' ? [clip] : [];
    if (i.shell) { m.transparent = o < 0.999; m.opacity = o; m.depthWrite = o >= 0.999; }
    if (i.name === 'liners') { m.transparent = o < 0.999; m.opacity = Math.max(o, 0.35); m.depthWrite = o >= 0.999; }
  });
  draw();
}

// ---- orbit camera, Z up
const tgt = new T.Vector3(0, 45, -20);
let th = -Math.PI/2, ph = Math.PI/2, dist = 650;
function place() {
  ph = Math.min(Math.PI - 0.002, Math.max(0.002, ph));
  camera.position.set(tgt.x + dist*Math.sin(ph)*Math.cos(th), tgt.y + dist*Math.sin(ph)*Math.sin(th), tgt.z + dist*Math.cos(ph));
  camera.lookAt(tgt);
  head.position.copy(camera.position).add(new T.Vector3(150, -100, 250));
}
function draw() { place(); renderer.render(scene, camera); }
const VIEWS = {Front:[-90,90,650], Back:[90,90,650], 'Left (+X)':[0,90,650], 'Right (-X)':[180,90,650], Top:[-90,0,650], Bottom:[-90,180,650], '3/4':[-50,68,700], 'Under 3/4':[-40,115,700]};
Object.entries(VIEWS).forEach(([n,[a,b,d]]) => {
  const bt = document.createElement('button'); bt.textContent = n;
  bt.onclick = () => { th = a*Math.PI/180; ph = b*Math.PI/180; dist = d; tgt.set(0,45,-20); draw(); };
  $('views').appendChild(bt);
});
let drag = null;
canvas.addEventListener('contextmenu', e => e.preventDefault());
canvas.addEventListener('pointerdown', e => { drag = {x:e.clientX, y:e.clientY, pan:e.button === 2 || e.shiftKey}; canvas.setPointerCapture(e.pointerId); });
canvas.addEventListener('pointerup', () => drag = null);
canvas.addEventListener('pointermove', e => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag.x = e.clientX; drag.y = e.clientY;
  if (drag.pan) {
    const k = dist * 0.0016, right = new T.Vector3().crossVectors(camera.getWorldDirection(new T.Vector3()), camera.up).normalize();
    const up = new T.Vector3().crossVectors(right, camera.getWorldDirection(new T.Vector3())).normalize();
    tgt.addScaledVector(right, -dx*k).addScaledVector(up, dy*k);
  } else { th -= dx*0.007; ph -= dy*0.007; }
  draw();
});
canvas.addEventListener('wheel', e => { e.preventDefault(); dist = Math.min(2500, Math.max(60, dist*Math.exp(e.deltaY*0.001))); draw(); }, {passive:false});
function resize() {
  const v = $('view'); renderer.setSize(v.clientWidth, v.clientHeight, false);
  camera.aspect = v.clientWidth / v.clientHeight; camera.updateProjectionMatrix(); draw();
}
addEventListener('resize', resize);
resize(); update();
// URL hash for scripted views, e.g. #view=Front&step=14&op=0.3&ex=0.5
(function(){ const h = new URLSearchParams(location.hash.slice(1));
  if (h.has('step')) st.value = h.get('step'); if (h.has('op')) op.value = h.get('op'); if (h.has('ex')) ex.value = h.get('ex');
  if (h.get('cut')) $('cut').checked = true;
  update(); if (h.has('view')) [...$('views').children].find(b => b.textContent === h.get('view')).click(); })();
</script></body></html>
'''

if __name__ == '__main__':
    main()
