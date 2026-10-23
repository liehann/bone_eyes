// "Eyes of fire": a black pupil with flames streaming out of it, clipped by
// the normal eyelids. Integer-only per pixel on tables from
// tools/gen_fire_tables.py, so the browser simulator (tools/eye_sim) renders
// identical pixels. Shared by the LCD backend and host tools.
#pragma once
#include <stdint.h>

#include "eye_art/fire_tables.h"
#include "eye_render.h"

namespace fire_render {

// Per-mood targets, indexed by Mood (idle, alert, talking, goodbye).
struct MoodFire {
  int len;    // flame length (px) before noise
  int speed;  // outward flow, px/s
  int base;   // heat at the pupil edge, 0..255
};
constexpr MoodFire kMoods[4] = {{72, 45, 185}, {115, 95, 235}, {100, 80, 225}, {40, 20, 150}};

// Per-eye animation state.
struct State {
  uint32_t lastMs = 0;
  uint32_t flowMilli = 0;  // outward scroll, 1/1000 px
  int len = 72 * 16, speed = 45, base = 185 * 16;  // len/base in 1/16 units, eased
};

struct Params {
  int cx, cy;     // pupil centre on the panel
  int pupilR;
  int len, base;  // eased flame length (px) and base heat
  int s1, s2;     // radial scroll for the two noise octaves
  int rot;        // slow angular drift
  eye_render::Params lids;
  // Per angle: ceil(255 * 65536 / len), len that angle's flame length, so
  // (d * fall[ang]) >> 16 == d * 255 / len exactly for d < 256, 4 <= len < 256
  // (exhaustively checked); a multiply instead of a divide per pixel.
  uint32_t fall[256];
};

inline Params compute(const EyeArt& lidArt, float gazeX, float gazeY, float lid, float pupil, bool lidFlip,
                      int& uTrack, int mood, uint32_t nowMs, State& s) {
  auto clampf = [](float v, float lo, float hi) { return v < lo ? lo : v > hi ? hi : v; };
  Params p;
  // Lid thresholds exactly as the normal eye computes them.
  p.lids = eye_render::compute(lidArt, gazeX, gazeY, lid, pupil, lidFlip, uTrack);

  // +x gaze (skull's right) moves the pupil to the viewer's left; +y moves it up.
  p.cx = eye_render::kOut / 2 - (int)(clampf(gazeX, -1, 1) * 30.0f);
  p.cy = eye_render::kOut / 2 - (int)(clampf(gazeY, -1, 1) * 30.0f);
  p.pupilR = 8 + (int)(clampf(pupil, 0, 1) * 10.0f);

  // Ease toward the mood's flame so mood changes flare/die down smoothly.
  const MoodFire& m = kMoods[mood & 3];
  uint32_t dt = s.lastMs ? nowMs - s.lastMs : 0;
  if (dt > 200) dt = 200;
  s.lastMs = nowMs;
  s.len += (m.len * 16 - s.len) / 8;
  s.base += (m.base * 16 - s.base) / 8;
  s.speed += (m.speed - s.speed) / 4;
  // Wrap at a common period of all three scrolls below (no jumps, no overflow).
  s.flowMilli = (s.flowMilli + dt * (uint32_t)s.speed) % 2048000u;
  p.len = s.len / 16;
  p.base = s.base / 16;
  p.s1 = (int)(s.flowMilli / 1000);
  p.s2 = (int)(s.flowMilli * 3 / 2000);
  p.rot = (int)(s.flowMilli / 8000);
  for (int a = 0; a < 256; a++) {
    int len = p.len + fire_tables::kUpBias[a];
    if (len < 4) len = 4;
    p.fall[a] = (255u * 65536u + (uint32_t)len - 1) / (uint32_t)len;
  }
  return p;
}

// Heat 0..255 of a fire pixel d px out from the pupil edge at angle ang.
inline int shade(const Params& p, int d, int ang) {
  using namespace fire_tables;
  const int n1 = kNoise[((d - p.s1) & 63) * kNoiseW + ((ang + p.rot) & 255)];
  const int n2 = kNoise[((d * 2 - p.s2) & 63) * kNoiseW + ((ang * 2 + 97 - p.rot) & 255)];
  const int n = (n1 * 5 + n2 * 3) >> 3;
  int h = p.base + ((n - 128) * 3) / 2 - (int)(((uint32_t)d * p.fall[ang]) >> 16);
  if (d < 4) h += (4 - d) * 20;  // white-hot rim on the pupil
  return h < 0 ? 0 : h > 255 ? 255 : h;
}

// Heat 0..255 at a panel pixel, ignoring the lids. 0 in the pupil.
inline int heat(const Params& p, int ox, int oy) {
  using namespace fire_tables;
  const int uy = p.cy - oy;  // up is positive
  const int ay = uy < 0 ? -uy : uy;
  const int dx = ox - p.cx;
  const int ax = dx < 0 ? -dx : dx;
  if (ax >= kQuad || ay >= kQuad) return 0;
  const int r = kRadius[ay * kQuad + ax];
  if (r < p.pupilR) return 0;  // the void
  const int a = kAngle[ay * kQuad + ax];
  int ang;  // 0..255 counter-clockwise from +x, 64 = straight up
  if (dx >= 0) ang = uy >= 0 ? a : (256 - a) & 255;
  else ang = uy >= 0 ? 128 - a : 128 + a;
  return shade(p, r - p.pupilR, ang);
}

// heat() for out[x], x in [x0, x1) on row oy, with the per-pixel quadrant
// logic hoisted out of the loop.
inline void heatSpan(const Params& p, int oy, int x0, int x1, uint8_t* out) {
  using namespace fire_tables;
  const int uy = p.cy - oy;
  const int ay = uy < 0 ? -uy : uy;
  if (ay >= kQuad) {
    for (int x = x0; x < x1; x++) out[x] = 0;
    return;
  }
  const uint8_t* rr = kRadius + ay * kQuad;
  const uint8_t* ra = kAngle + ay * kQuad;
  // Angle = (off + sgn * quadrant angle) & 255 on each side of the centre.
  for (int side = 0; side < 2; side++) {
    const int lo = side ? (x0 > p.cx ? x0 : p.cx) : x0;  // right: dx >= 0
    const int hi = side ? x1 : (x1 < p.cx ? x1 : p.cx);  // left: dx < 0
    const int off = side ? 0 : 128;
    const int sgn = (side ? 1 : -1) * (uy >= 0 ? 1 : -1);
    for (int x = lo; x < hi; x++) {
      const int ax = side ? x - p.cx : p.cx - x;
      if (ax >= kQuad) {
        out[x] = 0;
        continue;
      }
      const int r = rr[ax];
      out[x] = r < p.pupilR ? 0 : (uint8_t)shade(p, r - p.pupilR, (off + sgn * ra[ax]) & 255);
    }
  }
}

inline bool lidCovered(const EyeArt& lidArt, const eye_render::Params& lids, int ox, int oy) {
  const int S = lidArt.lidSize;
  const uint8_t* src = eye_render::srcMap(S);
  const int ly = src[oy], lx = lids.lidFlip ? S - 1 - src[ox] : src[ox];
  return lidArt.lower[ly * S + lx] <= lids.lThr || lidArt.upper[ly * S + lx] <= lids.uThr;
}

inline void row(const EyeArt& lidArt, const Params& p, int oy, uint16_t* out) {
  for (int ox = 0; ox < eye_render::kOut; ox++)
    out[ox] = lidCovered(lidArt, p.lids, ox, oy) ? 0 : fire_tables::kPalette[heat(p, ox, oy)];
}

}  // namespace fire_render
