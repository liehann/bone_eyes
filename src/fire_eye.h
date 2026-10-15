// The "fire" eye style as one effect: the burning iris (fire_render.h) plus
// smoke that its flame tips give off. The fire burns behind the lids too, so
// tips hidden by a lid still smoke, and that smoke drifts up over the lid.
// Smoke flows around the hot core of the iris instead of across it: rising
// smoke below the core is pushed sideways, so it splits round the sides and
// closes back in above.
//
// Integer-only with a seeded xorshift PRNG, mirrored in tools/eye_sim. Uses
// three 160x160 byte buffers per eye (the same allocation as flame_overlay).
#pragma once
#include <stdint.h>

#include "fire_render.h"

namespace fire_eye {

constexpr int N = eye_render::kOut;

struct Buffers {
  uint8_t* heat;   // fire heat, lids ignored
  uint8_t* smoke;
  uint8_t* open;   // 1 where the eye opening shows the fire
  uint32_t rng;
  uint32_t frame;
  int cx, cy, coreR;  // last frame's core disc, for composite()
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
  b.cx = b.cy = N / 2;
  b.coreR = 0;
}

// Per-mood smoke: emission chance out of 64 per flame-tip pixel, and amount.
constexpr int kEmit[4][2] = {{3, 110}, {3, 110}, {3, 110}, {6, 100}};  // idle, alert, talking, goodbye

inline void step(Buffers& b, const EyeArt& lidArt, const fire_render::Params& fp, int mood) {
  // 1. Fire heat everywhere (behind the lids too) and the opening mask.
  for (int y = 0; y < N; y++) {
    for (int x = 0; x < N; x++) {
      b.heat[y * N + x] = (uint8_t)fire_render::heat(fp, x, y);
      b.open[y * N + x] = !fire_render::lidCovered(lidArt, fp.lids, x, y);
    }
  }

  // 2. Smoke rises one pixel every other frame. Each pixel pulls from the row
  //    below; near the core it pulls from closer to the core's axis (smoke
  //    moves outward, around it), above the core from further out (the wake
  //    closes in).
  b.frame++;
  b.cx = fp.cx;
  b.cy = fp.cy;
  b.coreR = fp.pupilR + fp.len / 2;
  const int R = b.coreR;
  if (b.frame & 1) {
    for (int y = 0; y < N - 1; y++) {
      uint8_t* s = b.smoke + y * N;
      const uint8_t* below = s + N;
      const int dy = y - fp.cy;  // + is below the centre
      // Coherent sway: a noise row scrolling up with the smoke, sampled
      // coarsely in x, so neighbouring pixels drift together and wisps curl.
      const uint8_t* sway = fire_tables::kNoise + ((y + (b.frame >> 1)) & 63) * fire_tables::kNoiseW;
      for (int x = 0; x < N; x++) {
        const uint32_t r = next(b.rng);
        const int dx = x - fp.cx;
        const int adx = dx < 0 ? -dx : dx;
        const int side = dx < 0 ? -1 : 1;
        const int w = sway[(x >> 3) & 255];
        int sx = x + (w > 150 ? 1 : w < 106 ? -1 : 0);
        if (adx < R + 8 && dy > -R / 2) {
          sx = x - side;  // split around the core
          if (adx < R / 2 && (r & 8)) sx -= side;  // faster near the axis
        } else if (adx < R + 12 && dy <= -R / 2 && (r & 3) == 0) {
          sx = x + side;  // close in above it
        }
        if (sx < 1 || sx >= N - 1) {  // drifted off the panel
          s[x] = 0;
          continue;
        }
        // Light diffusion keeps the smoke soft instead of speckled.
        const int v = ((below[sx - 1] + 2 * below[sx] + below[sx + 1]) >> 2) - (int)(((r >> 9) & 3) == 0);
        s[x] = v < 0 ? 0 : (uint8_t)v;
      }
    }
    for (int x = 0; x < N; x++) b.smoke[(N - 1) * N + x] = 0;
  }

  // 3. Flame tips turn to smoke. Nothing survives inside the core disc.
  const int* e = kEmit[mood & 3];
  for (int y = 0; y < N; y++) {
    const int dy = y - fp.cy, ady = dy < 0 ? -dy : dy;
    for (int x = 0; x < N; x++) {
      const int i = y * N + x;
      const int dx = x - fp.cx, adx = dx < 0 ? -dx : dx;
      if (adx < fire_tables::kQuad && ady < fire_tables::kQuad &&
          fire_tables::kRadius[ady * fire_tables::kQuad + adx] < R) {
        b.smoke[i] = 0;
        continue;
      }
      const int h = b.heat[i];
      if (h > 25 && h < 60 && (int)(next(b.rng) & 63) < e[0]) {
        const int v = b.smoke[i] + e[1];
        b.smoke[i] = v > 160 ? 160 : (uint8_t)v;
      }
    }
  }
}

// One output row (native-endian RGB565). In the opening: the fire, with smoke
// only in the dark gaps between flames. Behind the lids: smoke only.
inline void row(const Buffers& b, int y, uint16_t* out) {
  for (int x = 0; x < N; x++) {
    const int i = y * N + x;
    const int h = b.open[i] ? b.heat[i] : 0;
    const uint16_t f = fire_tables::kPalette[h];
    int g = h < 40 ? b.smoke[i] * 3 / 4 : 0;  // 0..82, a dim warm grey
    if (h) g = g * (40 - h) / 40;
    const int r5 = (f >> 11) + (g >> 3), g6 = ((f >> 5) & 63) + ((g * 7 / 8) >> 2),
              b5 = (f & 31) + ((g * 3 / 4) >> 3);
    out[x] = (uint16_t)(((r5 > 31 ? 31 : r5) << 11) | ((g6 > 63 ? 63 : g6) << 5) | (b5 > 31 ? 31 : b5));
  }
}

}  // namespace fire_eye
