#!/usr/bin/env python3
"""Build the browser eye simulator (tools/eye_sim/eye_sim.html).

Compiles dump_art.cpp against the firmware's eye art + renderer, verifies the
JS port (eye_core.js) renders identical pixels, then inlines the art tables
and scripts into sim.template.html.
"""
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

here = Path(__file__).resolve().parent
repo = here.parents[1]

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    exe = tmp / "dump_art"
    subprocess.run(["c++", "-std=c++17", "-O2", f"-I{repo}/tools/host_shim", f"-I{repo}/src",
                    str(here / "dump_art.cpp"), str(repo / "src/eye_art/default_eye.cpp"),
                    str(repo / "src/eye_art/dragon_eye.cpp"), "-o", str(exe)], check=True)
    meta = json.loads(subprocess.run([str(exe), str(tmp)], check=True, capture_output=True, text=True).stdout)
    (tmp / "meta.json").write_text(json.dumps(meta))
    if subprocess.run(["node", str(here / "eye_core.test.js"), str(tmp)]).returncode:
        sys.exit("JS renderer differs from firmware renderer; not building")
    for m in meta:
        m["data"] = base64.b64encode((tmp / f"{m['name']}.bin").read_bytes()).decode()
        del m["checksums"]
    fire = json.loads((tmp / "fire.json").read_text())
    fire = {k: fire[k] for k in ("quad", "noiseW", "noiseH")}
    fire["data"] = base64.b64encode((tmp / "fire.bin").read_bytes()).decode()

html = (here / "sim.template.html").read_text()
html = html.replace("/*EYE_CORE*/", (here / "eye_core.js").read_text())
html = html.replace("/*ART_DATA*/[]", json.dumps(meta))
html = html.replace("/*FIRE_DATA*/{}", json.dumps(fire))
out = here / "eye_sim.html"
out.write_text(html)
print(f"wrote {out} ({out.stat().st_size // 1024} KiB)")
