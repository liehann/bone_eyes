// Flames and smoke rising out of the eye opening, composited over any eye
// style. The normal eye stays where the lids are open; the black around it
// (lids, panel edge) shows a classic rising-heat fire simulation seeded from
// the opening, with smoke drifting up from the flame tips.
//
// Integer-only with a seeded xorshift PRNG, so the browser simulator
// (tools/eye_sim) produces identical frames. Buffers are 3 x 160x160 bytes per
// eye; the LCD backend puts them in PSRAM.
#pragma once
#include <stdint.h>

#include "eye_art/fire_tables.h"
#include "eye_art/eye_tint.h"
#include "eye_render.h"

namespace flame_overlay {

constexpr int N = eye_render::kOut;

// Per-mood: mean heat lost per pixel risen (x4; lower = taller flames), and
// heat injected at the opening.
struct MoodFlame {
  int coolQ4;
  int source;
};
constexpr MoodFlame kMoods[4] = {{22, 210}, {12, 250}, {15, 240}, {40, 170}};  // idle, alert, talking, goodbye

struct Buffers {
  uint8_t* heat;   // N*N
  uint8_t* smoke;  // N*N
  uint8_t* open;   // N*N, 1 where the eye is visible this frame
  uint32_t rng;
  uint32_t frame;
};

inline uint32_t next(uint32_t& x) {
  x ^= x << 13;
  x ^= x >> 17;
  x ^= x << 5;
  return x;
}

inline void reset(Buffers& b, uint32_t seed) {
  for (int i = 0; i < N * N; i++) b.heat[i] = b.smoke[i] = b.open[i] = 0;
  b.rng = seed ? seed : 1;
  b.frame = 0;
}

// Advance one frame. lids: this frame's lid thresholds (from eye_render or
// fire_render compute()), lidArt: the art whose lid maps define the opening.
// emitSmoke false: no new smoke (what's there drifts off).
inline void step(Buffers& b, const EyeArt& lidArt, const eye_render::Params& lids, int mood, bool emitSmoke = true) {
  const MoodFlame& m = kMoods[mood & 3];
  const int coolQ4 = m.coolQ4, source = m.source;
  const int S = lidArt.lidSize;
  // Local copies: the byte stores below may alias b.rng / lids, which would
  // force a reload and store per pixel.
  uint32_t rng = b.rng;
  const bool lidFlip = lids.lidFlip;
  const uint32_t uThr = lids.uThr, lThr = lids.lThr;
  const uint8_t* src = eye_render::srcMap(S);

  // 1. Opening mask for this frame.
  for (int y = 0; y < N; y++) {
    const uint8_t* up = lidArt.upper + src[y] * S;
    const uint8_t* lo = lidArt.lower + src[y] * S;
    uint8_t* o = b.open + y * N;
    for (int x = 0; x < N; x++) {
      const int lx = lidFlip ? S - 1 - src[x] : src[x];
      o[x] = !(lo[lx] <= lThr || up[lx] <= uThr);
    }
  }

  // 2. Fire rises: each pixel takes the pixel below (with sideways jitter)
  //    minus cooling. The cooling comes from a noise map that scrolls up with
  //    the flames, which is what breaks the fire into separate tongues.
  //    Top-down so row y+1 is still last frame's.
  b.frame++;
  for (int y = 0; y < N - 1; y++) {
    uint8_t* h = b.heat + y * N;
    const uint8_t* below = h + N;
    const uint8_t* cool = fire_tables::kNoise + ((y + b.frame) & 63) * fire_tables::kNoiseW;
    for (int x = 0; x < N; x++) {
      const uint32_t r = next(rng);
      int sx = x + (int)(r % 3) - 1;
      sx = sx < 0 ? 0 : sx >= N ? N - 1 : sx;
      // Mean cooling coolQ4/4 per pixel; noise spans ~0..2x that.
      const int c = (int)((cool[x] * cool[x] * (uint32_t)coolQ4) >> 15) + (int)((r >> 8) & 1);
      int v = below[sx] - c;
      h[x] = v < 0 ? 0 : (uint8_t)v;
    }
  }
  for (int x = 0; x < N; x++) b.heat[(N - 1) * N + x] = 0;

  // 3. The opening is the fuel: re-ignite it every frame. Flicker the source
  //    so the flame base isn't a solid band.
  uint8_t* const heat = b.heat;
  uint8_t* const smoke = b.smoke;
  const uint8_t* const open = b.open;
  for (int i = 0; i < N * N; i++) {
    if (open[i]) {
      const int v = source - (int)(next(rng) & 31);
      heat[i] = v < 0 ? 0 : (uint8_t)v;
    }
  }

  // 4. Smoke rises at half speed with a slow sway, fed by flame tips.
  if (b.frame & 1) {
    const int sway = (int)((b.frame >> 5) % 3) - 1;
    for (int y = 0; y < N - 1; y++) {
      uint8_t* s = b.smoke + y * N;
      const uint8_t* below = s + N;
      for (int x = 0; x < N; x++) {
        int sx = x + sway;
        sx = sx < 0 ? 0 : sx >= N ? N - 1 : sx;
        int v = below[sx] - (int)(next(rng) % 5);
        s[x] = v < 0 ? 0 : (uint8_t)v;
      }
    }
    for (int x = 0; x < N; x++) b.smoke[(N - 1) * N + x] = 0;
  }
  for (int i = 0; emitSmoke && i < N * N; i++) {
    const int h = heat[i];
    if (h > 20 && h < 60 && !open[i] && (next(rng) & 15) == 0) {
      const int v = smoke[i] + 70;
      smoke[i] = v > 120 ? 120 : (uint8_t)v;
    }
  }
  b.rng = rng;
}

// Composite over a rendered eye row (native-endian RGB565, in place).
inline void composite(const Buffers& b, int y, uint16_t* row) {
  const uint8_t* o = b.open + y * N;
  const uint8_t* h = b.heat + y * N;
  const uint8_t* s = b.smoke + y * N;
  const uint16_t* pal = eye_tint::active().table;  // fire palette
  if (!pal) pal = fire_tables::kPalette;           // orange
  for (int x = 0; x < N; x++) {
    if (o[x]) continue;  // the eye itself
    const uint16_t f = pal[h[x]];
    // Smoke: a dim grey added under the flame.
    const int g = s[x] >> 1;  // 0..60
    int r5 = (f >> 11) + (g >> 3), g6 = ((f >> 5) & 63) + (g >> 2), b5 = (f & 31) + (g >> 3);
    r5 = r5 > 31 ? 31 : r5;
    g6 = g6 > 63 ? 63 : g6;
    b5 = b5 > 31 ? 31 : b5;
    row[x] = (uint16_t)((r5 << 11) | (g6 << 5) | b5);
  }
}

}  // namespace flame_overlay
