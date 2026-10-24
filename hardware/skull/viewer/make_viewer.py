#!/usr/bin/env python3
"""Build the interactive 3D assembly viewer for the printable skull.

Reads the assembled-position meshes that build.py writes to cache/render/,
decimates the big shells, packs everything into one GLB (one named node per
part, per-part colours) and writes viewer/index.html with the GLB and the
part metadata (groups, explode offsets, jaw hinge) inlined, so the page works
straight from file:// with no server.

    hardware/.venv/bin/python hardware/skull/viewer/make_viewer.py [--open]
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
SKULL = os.path.dirname(HERE)
RENDER = os.path.join(SKULL, 'cache', 'render')
OUT = os.path.join(SKULL, 'out')

SHELL_MAX = 150_000    # triangle cap for the big shells (face, back)
PART_MAX = 60_000      # triangle cap for everything else
SHELLS = ('face', 'back', 'jaw')   # parts the x-ray toggle makes transparent

# Bone shades for printed parts; hardware stand-ins keep build.py's colours.
BONE = dict(face='#efe6cf', back='#e2d3b1', jaw='#d7c49c', stand='#b9ab8f', tray='#cdbf9f',
            servo_bracket='#c8b58d', joint_bracket='#bfa77a')
HW = dict(bar='#6b6f75', modules='#2a2d33', servo='#3f6fd8', horn='#d0303c', radar='#e04a2a',
          esp32='#1f9e94', paint='#1a1a1a', screens='#e3b41f')
LABELS = dict(face='Face', back='Cranium back', jaw='Jaw', stand='Stand', tray='Electronics tray',
              servo_bracket='Servo bracket', bar='Eye bar', modules='Eye LCD modules', servo='Jaw servo',
              horn='Servo horn', radar='Radar module', esp32='ESP32 + headers', paint='Socket paint',
              screens='LCD glass')

# Used when expl.scad has no offset for a part (mm, build.py coords: -Y forward, +Z up).
DEFAULT_EXPLODE = dict(face=(0, -90, 0), back=(0, 25, 0), jaw=(0, 0, -70), bar=(0, -45, 0),
                       modules=(0, -45, 0), radar=(0, -70, 0), servo=(40, 25, -40),
                       servo_bracket=(40, 25, -40), horn=(40, 25, -40), tray=(0, 70, 0),
                       esp32=(0, 70, 0), stand=(0, 0, -110),
                       paint=(0, -90, 0), screens=(0, -45, 0))   # paint rides on the face, glass on the modules


def parse_scad(path):
    """{part: (translate xyz or None, colour, jaw rotate info or None)} from an OpenSCAD scene."""
    res = {}
    if not os.path.exists(path):
        return res
    num = r'(-?[\d.eE+-]+)'
    vec = r'\[\s*%s\s*,\s*%s\s*,\s*%s\s*\]' % (num, num, num)
    for line in open(path).read().splitlines():
        m = re.search(r'import\("([^"]+)\.stl"\)', line)
        if not m:
            continue
        name = m.group(1)
        trs = [tuple(float(v) for v in t) for t in re.findall(r'translate\(' + vec + r'\)', line)]
        rot = re.search(r'rotate\(' + vec + r'\)', line)
        col = re.search(r'color\("([^"]+)"\)', line)
        res[name] = dict(translates=trs, rotate=tuple(float(v) for v in rot.groups()) if rot else None,
                         color=col.group(1) if col else None)
    return res


def hinge_info():
    """Jaw hinge (point on the X axis, open angle) from open.scad, else build_report.json."""
    o = parse_scad(os.path.join(RENDER, 'open.scad')).get('jaw')
    if o and o['rotate'] and o['translates']:
        p = o['translates'][0]
        return dict(point=[0.0, p[1], p[2]], axis=[1, 0, 0], open_deg=o['rotate'][0], source='open.scad')
    rep = os.path.join(OUT, 'build_report.json')
    if os.path.exists(rep):
        h = json.load(open(rep)).get('hinge')
        if h:
            return dict(point=[0.0, h[0], h[1]], axis=[1, 0, 0], open_deg=18.0, source='build_report.json')
    return None


def build_constants():
    """Jaw stop angles from build.py (read only; falls back to the current values)."""
    vals = dict(JAW_OPEN_DEG=18.0, JAW_STOP_MARGIN=2.0, JAW_CLOSE_STOP=-0.5)
    try:
        src = open(os.path.join(SKULL, 'build.py')).read()
        for k in vals:
            m = re.search(r'^%s\s*=\s*(-?[\d.]+)' % k, src, re.M)
            if m:
                vals[k] = float(m.group(1))
    except OSError:
        pass
    return vals


def decimate(mesh, cap):
    n = len(mesh.faces)
    if n <= cap:
        return mesh
    import fast_simplification
    v, f = fast_simplification.simplify(np.asarray(mesh.vertices, np.float32), np.asarray(mesh.faces, np.int64),
                                        target_reduction=1.0 - cap / n)
    return trimesh.Trimesh(v, f, process=True)


def base(name):
    return 'joint_bracket' if name.startswith('joint_bracket') else name


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--open', action='store_true', help='open the result in Google Chrome')
    a = ap.parse_args()

    stls = sorted(f[:-4] for f in os.listdir(RENDER) if f.endswith('.stl'))
    if not stls:
        sys.exit('no meshes in %s - run build.py first' % RENDER)
    printed = {f[:-4] for f in os.listdir(OUT) if f.endswith('.stl')} if os.path.isdir(OUT) else set(BONE)
    expl = parse_scad(os.path.join(RENDER, 'expl.scad'))
    hinge = hinge_info()

    scene = trimesh.Scene()
    parts = []
    for name in stls:
        m = trimesh.load(os.path.join(RENDER, name + '.stl'), force='mesh')
        n0 = len(m.faces)
        m = decimate(m, SHELL_MAX if n0 > SHELL_MAX else PART_MAX)
        is_printed = name in printed
        colour = (BONE if is_printed else HW).get(base(name)) or (expl.get(name) or {}).get('color') or '#ff8c00'
        rgba = list(trimesh.visual.color.hex_to_rgba(colour) / 255.0) if colour.startswith('#') else [1, .55, 0, 1]
        m.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            name=name, baseColorFactor=rgba, metallicFactor=0.0, roughnessFactor=0.8 if is_printed else 0.5))
        scene.add_geometry(m, node_name=name, geom_name=name)
        e = expl.get(name)
        off = list(e['translates'][0]) if e and e['translates'] else list(DEFAULT_EXPLODE.get(base(name), (0, 0, 0)))
        if base(name) == 'joint_bracket' and not (e and e['translates']):
            off = [0, -40, 0]
        label = LABELS.get(base(name), name.replace('_', ' '))
        if base(name) == 'joint_bracket':
            label = 'Joint bracket ' + name[len('joint_bracket_'):].replace('_', ' ')
        parts.append(dict(name=name, label=label, group='printed' if is_printed else 'hardware', color=colour,
                          explode=off, shell=name in SHELLS, flat=not is_printed or name not in SHELLS,
                          tris=len(m.faces), tris_src=n0))
        print('%-24s %7d -> %7d tris  explode %s' % (name, n0, len(m.faces), off))

    glb = scene.export(file_type='glb')
    with open(os.path.join(HERE, 'skull.glb'), 'wb') as f:
        f.write(glb)

    k = build_constants()
    meta = dict(parts=parts, hinge=hinge,
                jaw=dict(min=k['JAW_CLOSE_STOP'], max=k['JAW_OPEN_DEG'] + k['JAW_STOP_MARGIN'],
                         nominal=k['JAW_OPEN_DEG']),
                explode_source='expl.scad' if expl else 'defaults')
    tpl = open(os.path.join(HERE, 'template.html')).read()
    html = tpl.replace('/*__META__*/null', json.dumps(meta)).replace('__GLB_B64__', base64.b64encode(glb).decode())
    out = os.path.join(HERE, 'index.html')
    with open(out, 'w') as f:
        f.write(html)
    print('wrote %s (%.1f MB, GLB %.1f MB, hinge from %s)' % (
        out, len(html) / 1e6, len(glb) / 1e6, hinge['source'] if hinge else 'none'))
    if a.open:
        subprocess.call(['open', '-a', 'Google Chrome', out])


if __name__ == '__main__':
    main()
