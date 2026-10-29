# Uncanny Eyes artwork: licence and attribution

The eye styles `default`, `dragon`, `cat`, `goat`, `owl`, `newt`,
`terminator`, `nosclera`, `doe` and `nauga` use the artwork of **Uncanny
Eyes** by Phillip Burgess (Paint Your Dragon) for Adafruit Industries,
<https://github.com/adafruit/Uncanny_Eyes> (`uncannyEyes/graphics/`, checked at
commit `d2103e84aa33da9f6924885ebc06d880af8deeff`). The renderer
(`src/eye_render.h`) follows the same project's `drawEye()`.

The tables come from Bodmer's TFT_eSPI example
`examples/Generic/Animated_Eyes_2/data/` (<https://github.com/Bodmer/TFT_eSPI>,
checked at commit `16e37595040eac69cd628e4bffb56fc30cad6299`), which carries
the same artwork as flat arrays with iris ranges for this renderer. Its
`eye_functions.ino` keeps the upstream notice: "Written by Phil Burgess /
Paint Your Dragon for Adafruit Industries. MIT license."

Upstream licence: the Uncanny_Eyes repository has no LICENSE file; its sketch
(`uncannyEyes/uncannyEyes.ino`) states "Written by Phil Burgess / Paint Your
Dragon for Adafruit Industries. MIT license." The graphics headers and the
conversion images in `convert/` carry no separate notice or third-party
credit, so the artwork is treated as MIT under that notice.

| Style | Where | Source header |
|---|---|---|
| default | `src/eye_art/defaultEye.h` (flash) | `defaultEye.h`, unchanged |
| dragon | `src/eye_art/dragonEye.h` (flash) | `dragonEye.h`, unchanged |
| cat, goat, terminator | `data/uncanny/<style>.eye` (LittleFS) | `catEye.h`, `goatEye.h`, `terminatorEye.h` |
| newt, nosclera | `data/uncanny/<style>.eye` | `newtEye.h`, `noScleraEye.h`; iris range rescaled (see `tools/uncanny_sets.sh`) |
| owl, nauga, doe | `data/uncanny/<style>.eye` | `owlEye.h`, `naugaEye.h`, `doeEye.h`; lid tracking off, as upstream |

The `.eye` files are the same tables re-packed by `tools/uncanny_convert.py`
(non-symmetrical lids), a derived work under the same licence.

---

MIT License

Copyright (c) Phillip Burgess for Adafruit Industries

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
