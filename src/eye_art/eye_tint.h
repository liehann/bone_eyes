// Colour controls for the Uncanny Eyes styles and the fire palettes. All of
// it runs when a setting changes, never per pixel per frame:
//
// - Tint: hue rotation, saturation and a multiply colour, folded into one
//   3x3 fixed-point matrix (CSS filter hue-rotate()/saturate() maths). It is
//   applied once to every texel of the iris and sclera textures into a
//   tinted copy (src/eyes_lcd.cpp), so drawing a tinted eye costs the same as
//   drawing the original.
// - Fire palette: the 256-entry heat -> RGB565 table, rebuilt as a channel
//   swap / scale of the orange original.
//
// Hardware-independent (host tools include it too).
#pragma once
#include <math.h>
#include <stdint.h>

#include "fire_tables.h"

namespace eye_tint {

struct Tint {
  int hue;       // degrees, -180..180
  int sat;       // %, 0..200 (100 = unchanged)
  uint32_t rgb;  // 0xRRGGBB multiply, 0xFFFFFF = unchanged
  bool neutral() const { return hue % 360 == 0 && sat == 100 && (rgb & 0xFFFFFF) == 0xFFFFFF; }
  bool operator==(const Tint& o) const { return hue == o.hue && sat == o.sat && rgb == o.rgb; }
  bool operator!=(const Tint& o) const { return !(*this == o); }
};

struct Matrix {
  int32_t m[9];  // 1.0 = 4096
};

inline Matrix matrix(const Tint& t) {
  const float a = t.hue * 3.14159265f / 180.0f, c = cosf(a), s = sinf(a), k = t.sat / 100.0f;
  const float h[9] = {0.213f + c * 0.787f - s * 0.213f, 0.715f - c * 0.715f - s * 0.715f, 0.072f - c * 0.072f + s * 0.928f,
                      0.213f - c * 0.213f + s * 0.143f, 0.715f + c * 0.285f + s * 0.140f, 0.072f - c * 0.072f - s * 0.283f,
                      0.213f - c * 0.213f - s * 0.787f, 0.715f - c * 0.715f + s * 0.715f, 0.072f + c * 0.928f + s * 0.072f};
  const float sm[9] = {0.213f + 0.787f * k, 0.715f - 0.715f * k, 0.072f - 0.072f * k,
                       0.213f - 0.213f * k, 0.715f + 0.285f * k, 0.072f - 0.072f * k,
                       0.213f - 0.213f * k, 0.715f - 0.715f * k, 0.072f + 0.928f * k};
  const float mul[3] = {((t.rgb >> 16) & 255) / 255.0f, ((t.rgb >> 8) & 255) / 255.0f, (t.rgb & 255) / 255.0f};
  Matrix out;
  for (int r = 0; r < 3; r++)
    for (int col = 0; col < 3; col++) {
      float v = 0;
      for (int i = 0; i < 3; i++) v += sm[r * 3 + i] * h[i * 3 + col];  // saturate after hue
      out.m[r * 3 + col] = (int32_t)lroundf(v * mul[r] * 4096.0f);
    }
  return out;
}

// One native-endian RGB565 pixel through the matrix.
inline uint16_t apply(const Matrix& M, uint16_t c) {
  const int r = ((c >> 11) & 31) * 255 / 31, g = ((c >> 5) & 63) * 255 / 63, b = (c & 31) * 255 / 31;
  int o[3];
  for (int i = 0; i < 3; i++) {
    const int v = (M.m[i * 3] * r + M.m[i * 3 + 1] * g + M.m[i * 3 + 2] * b + 2048) >> 12;
    o[i] = v < 0 ? 0 : v > 255 ? 255 : v;
  }
  return (uint16_t)(((o[0] & 0xF8) << 8) | ((o[1] & 0xFC) << 3) | (o[2] >> 3));
}

inline void applyAll(const Matrix& M, const uint16_t* src, uint16_t* dst, int n) {
  for (int i = 0; i < n; i++) dst[i] = apply(M, src[i]);
}

// --- fire palettes ---

enum Palette { kOrange, kRed, kBlue, kGreen, kPurple, kWhite, kNumPalettes };
constexpr const char* kPaletteNames[kNumPalettes] = {"orange", "red", "blue", "green", "purple", "white"};

// palette p of the orange fire_tables::kPalette, into out[256].
inline void buildPalette(int p, uint16_t* out) {
  for (int i = 0; i < 256; i++) {
    const uint16_t c = fire_tables::kPalette[i];
    const int r = ((c >> 11) & 31) * 255 / 31, g = ((c >> 5) & 63) * 255 / 63, b = (c & 31) * 255 / 31;
    int o[3];
    switch (p) {
      case kRed: o[0] = r, o[1] = g * 2 / 5, o[2] = b * 2 / 5; break;  // deep red, still white-hot at the core
      case kBlue: o[0] = b, o[1] = g * 4 / 5, o[2] = r; break;         // red and blue swapped: gas flame
      case kGreen: o[0] = g * 3 / 5, o[1] = r, o[2] = b; break;        // red and green swapped
      case kPurple: o[0] = r * 4 / 5, o[1] = b, o[2] = g + (r - g) / 3; break;  // magenta-violet
      case kWhite: {  // ghostly: brightness only, a touch of blue
        const int y = (r * 54 + g * 183 + b * 19) >> 8;
        o[0] = y * 7 / 8, o[1] = y * 15 / 16, o[2] = y;
        break;
      }
      default: o[0] = r, o[1] = g, o[2] = b;
    }
    for (int& v : o) v = v < 0 ? 0 : v > 255 ? 255 : v;
    out[i] = (uint16_t)(((o[0] & 0xF8) << 8) | ((o[1] & 0xFC) << 3) | (o[2] >> 3));
  }
}

// The palette the fire renderers read (fire_eye, flame_overlay). Set between
// frames by the LCD backend; nullptr = orange, fire_tables::kPalette itself.
struct ActivePalette {
  const uint16_t* table = nullptr;
  int which = kOrange;
};
inline ActivePalette& active() {
  static ActivePalette a;
  return a;
}
// Switch palettes; buf is 256 entries of fast (internal) RAM that holds
// non-orange palettes.
inline void setPalette(int p, uint16_t* buf) {
  ActivePalette& a = active();
  if (p == a.which) return;
  if (p <= kOrange || p >= kNumPalettes) {
    a.table = nullptr;
    a.which = kOrange;
    return;
  }
  a.table = nullptr;  // never point at a half-built table
  buildPalette(p, buf);
  a.table = buf;
  a.which = p;
}

}  // namespace eye_tint
