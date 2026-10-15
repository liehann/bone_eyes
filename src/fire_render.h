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
  return p;
}

inline void row(const EyeArt& lidArt, const Params& p, int oy, uint16_t* out) {
  using namespace fire_tables;
  const int S = lidArt.lidSize;
  const uint8_t* src = eye_render::srcMap(S);
  const int ly = src[oy];
  const uint8_t* upperRow = lidArt.upper + ly * S;
  const uint8_t* lowerRow = lidArt.lower + ly * S;
  const int uy = p.cy - oy;  // up is positive
  const int ay = uy < 0 ? -uy : uy;
  for (int ox = 0; ox < eye_render::kOut; ox++) {
    const int lx = src[ox];
    const int lidX = p.lids.lidFlip ? S - 1 - lx : lx;
    if (lowerRow[lidX] <= p.lids.lThr || upperRow[lidX] <= p.lids.uThr) {
      out[ox] = 0;
      continue;
    }
    const int dx = ox - p.cx;
    const int ax = dx < 0 ? -dx : dx;
    if (ax >= kQuad || ay >= kQuad) {
      out[ox] = 0;
      continue;
    }
    const int r = kRadius[ay * kQuad + ax];
    if (r < p.pupilR) {
      out[ox] = 0;  // the void
      continue;
    }
    const int a = kAngle[ay * kQuad + ax];
    int ang;  // 0..255 counter-clockwise from +x, 64 = straight up
    if (dx >= 0) ang = uy >= 0 ? a : (256 - a) & 255;
    else ang = uy >= 0 ? 128 - a : 128 + a;

    const int d = r - p.pupilR;
    const int n1 = kNoise[((d - p.s1) & 63) * kNoiseW + ((ang + p.rot) & 255)];
    const int n2 = kNoise[((d * 2 - p.s2) & 63) * kNoiseW + ((ang * 2 + 97 - p.rot) & 255)];
    const int n = (n1 * 5 + n2 * 3) >> 3;
    int len = p.len + kUpBias[ang];
    if (len < 4) len = 4;
    int heat = p.base + ((n - 128) * 3) / 2 - (d * 255) / len;
    if (d < 4) heat += (4 - d) * 20;  // white-hot rim on the pupil
    heat = heat < 0 ? 0 : heat > 255 ? 255 : heat;
    out[ox] = kPalette[heat];
  }
}

}  // namespace fire_render
