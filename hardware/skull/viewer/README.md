# Skull assembly viewer

An interactive three.js view of the assembled skull, built from the
assembled-position meshes that `build.py` writes to `cache/render/`.

## Regenerate

```sh
cd hardware
.venv/bin/python skull/build.py                    # refreshes cache/render/*.stl and *.scad
.venv/bin/python skull/viewer/make_viewer.py --open
```

`make_viewer.py` takes a few seconds. It writes `viewer/skull.glb` (one named
node per part) and `viewer/index.html`, with the GLB inlined as base64. Open
`index.html` straight from disk; it needs no server. three.js 0.160.0 loads from
jsdelivr, so the page needs an internet connection. Both outputs are
git-ignored. `template.html` is the page source.

## What it reads

- `cache/render/*.stl`: every part in assembled position. The face and back
  shells are decimated to 150k triangles and everything else is capped at 60k.
- `cache/render/expl.scad`: explode offsets per part. Parts without one, such
  as the socket paint and the LCD glass, use the defaults in `make_viewer.py`.
- `cache/render/open.scad`: the jaw hinge point and its axis, which is X. If
  that is missing, the script falls back to `out/build_report.json` `hinge`.
- `build.py` constants `JAW_CLOSE_STOP`, `JAW_OPEN_DEG` and `JAW_STOP_MARGIN`
  set the jaw-slider range. The script only reads `build.py` and never imports
  or runs it.
- `out/*.stl`: a part is listed under "Printed parts" when it has a file here.
  Everything else goes under "Electronics / hardware".

## Controls

- Show or hide each part with its checkbox, per group, or with "Show all" and
  "Hide all".
- The explode slider runs from assembled (0) to the `expl.scad` offsets (100%).
- The jaw slider rotates the jaw about its hinge, between the closed and open
  stops.
- "X-ray shells" makes the face, back and jaw transparent. While it is on, a
  click passes through them.
- Click a part, or its name in the list, to highlight it and show its name.
- Drag to orbit, scroll to zoom, and right-drag or shift-drag to pan.
- The "+", "−" and "Fit" buttons (bottom left) and the + / − / 0 keys zoom in
  or out by 20%, or fit everything visible from the current angle.
- "Reset view" fits everything visible from the default three-quarter front
  angle. The view refits on window resize until you move the camera.
- You can set the starting state in the URL hash, for example
  `index.html#explode=1&jaw=18&xray=1&hide=stand&select=servo`.
  `#selftest=reset` moves the camera and then presses Reset view, which is
  handy for headless screenshots.
