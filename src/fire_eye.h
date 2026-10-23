// The "fire" eye style as one effect: the burning iris (fire_render.h) plus
// smoke that its flame tips give off. The fire burns behind the lids too, so
// tips hidden by a lid still smoke, and that smoke drifts up over the lid.
// Smoke flows around the hot core of the iris instead of across it: rising
// smoke below the core is pushed sideways, so it splits round the sides and
// closes back in above.
//
// Integer-only with a seeded xorshift PRNG, mirrored in tools/eye_sim. Only
// the smoke is a buffer (160x160 bytes per eye): the fire is evaluated per
// pixel, in row() for the opening and in step() for the few pixels that try
// to emit smoke.
#pragma once
#include <stdint.h>

#include "fire_render.h"

namespace fire_eye {

constexpr int N = eye_render::kOut;

struct Buffers {
  uint8_t* smoke;  // N*N
  uint32_t rng;
  uint32_t frame;
  fire_render::Params fp;  // last step()'s fire, for row()
  const EyeArt* lidArt;
};

inline uint32_t next(uint32_t& x) {
  x ^= x << 13;
  x ^= x >> 17;
  x ^= x << 5;
  return x;
}

// Per-mood smoke: emission chance out of 64 per flame-tip pixel, and amount.
constexpr int kEmit[4][2] = {{3, 110}, {3, 110}, {3, 110}, {6, 100}};  // idle, alert, talking, goodbye

// Emission is a Bernoulli trial per pixel with p = kEmit[m][0] / 64. Instead
// of a roll per pixel, step from one emitting pixel to the next by a
// geometric gap: gapTable(m)[u] for a uniform byte u is the number of pixels
// skipped, P(gap = k) = (1 - p)^k p (to 1/256 resolution). Integer-only so the
// simulator builds the same table.
inline const uint8_t* gapTable(int mood) {
  static uint8_t gap[4][256];
  static bool built[4];
  mood &= 3;
  if (!built[mood]) {
    const uint32_t keep = 64 - kEmit[mood][0];
    for (int u = 0; u < 256; u++) {
      const uint32_t uf = (uint32_t)(2 * u + 1) << 15;  // (u + 0.5) / 256 in 1/2^24
      uint32_t surv = (keep << 24) / 64;                 // (1 - p)^(k + 1), k = 0
      int k = 0;
      while (k < 255 && surv >= uf) {
        surv = surv * keep / 64;
        k++;
      }
      gap[mood][u] = (uint8_t)k;
    }
    built[mood] = true;
  }
  return gap[mood];
}

inline void reset(Buffers& b, uint32_t seed) {
  for (int i = 0; i < N * N; i++) b.smoke[i] = 0;
  b.rng = seed ? seed : 1;
  b.frame = 0;
  b.fp = {};
  b.lidArt = nullptr;
  for (int m = 0; m < 4; m++) gapTable(m);  // build before two cores share them
}

// Half-width of the core disc (radius < R) on a row ady from the centre: the
// disc covers |dx| < coreHalfWidth. kRadius grows with |dx|, so scan out.
inline int coreHalfWidth(int ady, int R) {
  using namespace fire_tables;
  if (ady >= kQuad) return 0;
  const uint8_t* rr = kRadius + ady * kQuad;
  int w = 0;
  while (w < kQuad && rr[w] < R) w++;
  return w;
}

inline void step(Buffers& b, const EyeArt& lidArt, const fire_render::Params& fp, int mood) {
  b.fp = fp;
  b.lidArt = &lidArt;

  // 1. Smoke rises one pixel every other frame: the top half of the rows on
  //    odd frames, the bottom half on even ones, so every frame costs the
  //    same. Rows go top-down, so each pulls from the row below before that
  //    row moves. Each pixel pulls from the row below; near the core it pulls
  //    from closer to the core's axis (smoke moves outward, around it), above
  //    the core from further out (the wake closes in).
  b.frame++;
  // Locals, not b.rng / fp.*: the byte stores below may alias them, which
  // would force a reload and store per pixel.
  uint32_t rng = b.rng;
  const int cx = fp.cx, cy = fp.cy;
  const int R = fp.pupilR + fp.len / 2;  // core disc radius
  const uint32_t cycle = (b.frame - 1) >> 1;
  const bool topHalf = b.frame & 1;
  uint8_t blur[N];  // the row below, lightly diffused (keeps the smoke soft)
  for (int y = topHalf ? 0 : N / 2; y < (topHalf ? N / 2 : N - 1); y++) {
    uint8_t* s = b.smoke + y * N;
    const uint8_t* below = s + N;
    for (int x = 1; x < N - 1; x++) blur[x] = (uint8_t)((below[x - 1] + 2 * below[x] + below[x + 1]) >> 2);
    const int dy = y - cy;  // + is below the centre
    const bool beside = dy > -R / 2;  // beside/below the core, else above it
    const int band = beside ? R + 8 : R + 12;
    // Coherent sway: a noise row scrolling up with the smoke, sampled
    // coarsely in x, so neighbouring pixels drift together and wisps curl.
    const uint8_t* sway = fire_tables::kNoise + ((y + cycle) & 63) * fire_tables::kNoiseW;
    uint32_t r2 = 0;
    for (int x = 0; x < N; x++) {
      if (!(x & 1)) r2 = next(rng);
      const uint32_t r = (x & 1) ? r2 >> 16 : r2;  // 16 random bits per pixel
      const int dx = x - cx;
      const int adx = dx < 0 ? -dx : dx;
      const int side = dx < 0 ? -1 : 1;
      const int w = sway[x >> 3];
      int sx = x + (w > 150 ? 1 : w < 106 ? -1 : 0);
      if (adx < band) {
        if (beside) {
          sx = x - side;  // split around the core
          if (adx < R / 2 && (r & 8)) sx -= side;  // faster near the axis
        } else if ((r & 3) == 0) {
          sx = x + side;  // close in above it
        }
      }
      if (sx < 1 || sx >= N - 1) {  // drifted off the panel
        s[x] = 0;
        continue;
      }
      const int v = blur[sx] - (int)(((r >> 9) & 3) == 0);
      s[x] = v < 0 ? 0 : (uint8_t)v;
    }
  }
  if (!topHalf)
    for (int x = 0; x < N; x++) b.smoke[(N - 1) * N + x] = 0;

  // 2. Nothing survives inside the core disc.
  for (int y = 0; y < N; y++) {
    const int dy = y - cy;
    const int w = coreHalfWidth(dy < 0 ? -dy : dy, R);
    const int x0 = cx - w + 1 < 0 ? 0 : cx - w + 1, x1 = cx + w > N ? N : cx + w;  // core spans [x0, x1)
    for (int x = x0; x < x1; x++) b.smoke[y * N + x] = 0;
  }

  // 3. Flame tips (heat 26..59, lids ignored) turn to smoke: the emitting
  //    pixels, gap by gap, skipping the core.
  const uint8_t* gap = gapTable(mood);
  const int e1 = kEmit[mood & 3][1];
  for (int i = gap[next(rng) & 255]; i < N * N; i += 1 + gap[next(rng) & 255]) {
    const int y = i / N, x = i - y * N;
    const int dx = x - cx, dy = y - cy;
    const int adx = dx < 0 ? -dx : dx, ady = dy < 0 ? -dy : dy;
    if (adx < fire_tables::kQuad && ady < fire_tables::kQuad &&
        fire_tables::kRadius[ady * fire_tables::kQuad + adx] < R)
      continue;
    const int h = fire_render::heat(fp, x, y);
    if (h > 25 && h < 60) {
      const int v = b.smoke[i] + e1;
      b.smoke[i] = v > 160 ? 160 : (uint8_t)v;
    }
  }
  b.rng = rng;
}

// One output row (native-endian RGB565). In the opening: the fire, with smoke
// only in the dark gaps between flames. Behind the lids: smoke only.
inline void row(const Buffers& b, int y, uint16_t* out) {
  const EyeArt& a = *b.lidArt;
  const fire_render::Params& fp = b.fp;
  const int S = a.lidSize;
  const uint8_t* src = eye_render::srcMap(S);
  const uint8_t* up = a.upper + src[y] * S;
  const uint8_t* lo = a.lower + src[y] * S;
  const uint8_t* sm = b.smoke + y * N;
  const uint32_t uThr = fp.lids.uThr, lThr = fp.lids.lThr;
  // Fire heat in the opening (0 behind the lids). Only the span from the
  // first to the last open pixel is evaluated.
  uint8_t open[N], heat[N];
  int x0 = N, x1 = 0;
  for (int x = 0; x < N; x++) {
    const int lx = fp.lids.lidFlip ? S - 1 - src[x] : src[x];
    open[x] = !(lo[lx] <= lThr || up[lx] <= uThr);
    if (open[x]) {
      if (x < x0) x0 = x;
      x1 = x + 1;
    }
  }
  fire_render::heatSpan(fp, y, x0, x1, heat);
  for (int x = x0; x < x1; x++)
    if (!open[x]) heat[x] = 0;
  for (int x = 0; x < N; x++) {
    const int h = x >= x0 && x < x1 ? heat[x] : 0;
    const uint16_t f = fire_tables::kPalette[h];
    int g = h < 40 ? sm[x] * 3 / 4 : 0;  // 0..82, a dim warm grey
    if (h) g = g * (40 - h) / 40;
    const int r5 = (f >> 11) + (g >> 3), g6 = ((f >> 5) & 63) + ((g * 7 / 8) >> 2),
              b5 = (f & 31) + ((g * 3 / 4) >> 3);
    out[x] = (uint16_t)(((r5 > 31 ? 31 : r5) << 11) | ((g6 > 63 ? 63 : g6) << 5) | (b5 > 31 ? 31 : b5));
  }
}

}  // namespace fire_eye
