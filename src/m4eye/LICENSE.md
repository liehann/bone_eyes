# M4 eye: licence and attribution

The renderer in this folder (`m4eye_render.h`, and the table/lid/config logic
in `m4eye.cpp` and `m4eye_config.cpp`) is a port of **M4_Eyes** by Phillip
Burgess for Adafruit Industries, from
<https://github.com/adafruit/Adafruit_Learning_System_Guides/tree/main/M4_Eyes>
(fetched at commit `01efc12c46083aaa925d1d945e17b1ec6868e261`, 2026-10-23).

Upstream licence: the M4_Eyes sources carry
`SPDX-FileCopyrightText: 2019 Phillip Burgess for Adafruit Industries` and
`SPDX-License-Identifier: MIT`; the repository's `LICENSE` is MIT, Copyright
(c) 2018 Adafruit Industries. The M4_Eyes README asks that this text be kept
with any redistribution: "MIT license, hardware by Limor "Ladyada" Fried, eye
code by Phil Burgess".

## Artwork

| Eye set | Where | Files | Licence / source |
|---|---|---|---|
| hazel | `assets/hazel.h` (built in), `data/eyes/hazel/` | iris, sclera, upper/lower lids (+ symmetrical lids) | Adafruit M4_Eyes, MIT (no separate artwork licence) |
| snake_green | `data/eyes/snake_green/` | iris, lids | Adafruit M4_Eyes, MIT (no separate artwork licence) |
| doom-red | `data/eyes/doom-red/` | iris, sclera, lids | Adafruit M4_Eyes, MIT (no separate artwork licence) |
| doom-spiral | `data/eyes/doom-spiral/` | spiral iris, lids | Adafruit M4_Eyes, MIT (no separate artwork licence) |
| skull | `data/eyes/skull/` | red iris, dark sclera | Adafruit M4_Eyes, MIT (no separate artwork licence) |
| demon | not committed | iris | `demon/config.eye` credits the iris to "Fire Seamless tile" by suicidecrew on DeviantArt (deviantart.com/suicidecrew/art/Fire-Seamless-tile-116721709). No licence is stated, so it is left out of this public repo; convert it locally if wanted (`tools/m4eye_sets.sh`). |

The upstream eye folders have no per-file licence or SPDX notes. They ship in
the MIT-licensed repository, and apart from the demon iris their configs
credit no third party, so they are treated as MIT, under the copyright notice
above.

Converted files are derived works: radii scaled from 240 to 160 px, lid
bitmaps reduced to 160-column tables, textures re-encoded as RGB565 by
`tools/m4eye_convert.py`.

---

MIT License

Copyright (c) 2018 Adafruit Industries
Copyright (c) 2019 Phillip Burgess for Adafruit Industries

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
