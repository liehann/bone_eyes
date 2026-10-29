// Hardware-independent Uncanny Eyes row renderer, shared by the LCD backend
// and the host-side preview (tools/eye_preview.cpp).
#pragma once
#include <stdint.h>
#include <string.h>

#include "eye_art/eye_art.h"

namespace eye_render {

constexpr int kOut = 160;  // panel size

struct Params {
  int scleraX0, scleraY0;  // sclera window origin
  uint32_t uThr, lThr;     // lid thresholds (0 open .. 254 closed)
  uint32_t iScale;         // iris scale
  bool lidFlip;
};

// gazeX/gazeY -1..1 (+x = skull's right = viewer's left, +y = up), lid 0
// closed .. 0.75 normal .. 1 wide, pupil 0..1. uTrack is per-eye smoothing
// state for the lid-follows-pupil effect (start at 128).
inline Params compute(const EyeArt& a, float gazeX, float gazeY, float lid, float pupil, bool lidFlip,
                      int& uTrack) {
  auto clampf = [](float v, float lo, float hi) { return v < lo ? lo : v > hi ? hi : v; };
  auto clampi = [](int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; };
  const int S = a.lidSize;
  Params p;
  // A bigger window offset moves the iris up/left on screen.
  int rangeX = a.scleraW - S, rangeY = a.scleraH - S;
  p.scleraX0 = clampi((int)((clampf(gazeX, -1, 1) + 1) * 0.5f * rangeX), 0, rangeX);
  p.scleraY0 = clampi((int)((clampf(gazeY, -1, 1) + 1) * 0.5f * rangeY), 0, rangeY);

  // Upper lid tracks the pupil: sample the lid map just above the pupil and
  // average both sides (Uncanny Eyes' TRACKING), then smooth.
  int sx = clampi(a.scleraW / 2 - p.scleraX0 / 2, 0, S - 1);
  int sy = a.scleraH / 2 - (p.scleraY0 + a.irisH / 4);
  int n = 0;
  if (sy >= 0) {
    sy = clampi(sy, 0, S - 1);
    n = (a.upper[sy * S + sx] + a.upper[sy * S + (S - 1 - sx)]) / 2;
  }
  uTrack = (uTrack * 3 + n) / 4;
  float uT = uTrack, lT = 254 - uTrack;
  if (a.noTracking) uT = lT = 0;  // upstream without TRACKING: lids fully open unless blinking
  if (lid >= 0.75f) {
    float w = 1 - clampf((lid - 0.75f) / 0.25f, 0, 1);
    uT *= w;
    lT *= w;
  } else {
    float c = clampf(lid, 0, 1) / 0.75f;
    uT = 254 - (254 - uT) * c;
    lT = 254 - (254 - lT) * c;
  }
  p.uThr = (uint32_t)uT;
  p.lThr = (uint32_t)lT;
  p.iScale = a.irisMin + (uint32_t)(clampf(pupil, 0, 1) * (a.irisMax - a.irisMin));
  p.lidFlip = lidFlip;
  return p;
}

// Output pixel -> artwork pixel (nearest neighbour upscale).
inline const uint8_t* srcMap(int S) {
  static uint8_t map[kOut];
  static int built = 0;
  if (built != S) {
    for (int i = 0; i < kOut; i++) map[i] = i * S / kOut;
    built = S;
  }
  return map;
}

// Render output row `oy` as native-endian RGB565.
inline void row(const EyeArt& a, const Params& p, int oy, uint16_t* out) {
  const int S = a.lidSize;
  const uint8_t* src = srcMap(S);
  const int y = src[oy];
  const int scleraY = p.scleraY0 + y;
  const int irisY = scleraY - (a.scleraH - a.irisH) / 2;
  const int irisOffX = (a.scleraW - a.irisW) / 2;
  const uint8_t* upperRow = a.upper + y * S;
  const uint8_t* lowerRow = a.lower + y * S;
  const uint16_t* scleraRow = a.sclera + scleraY * a.scleraW;
  const bool irisRow = irisY >= 0 && irisY < a.irisH;
  for (int ox = 0; ox < kOut; ox++) {
    const int x = src[ox];
    const int lidX = p.lidFlip ? S - 1 - x : x;
    uint32_t c;
    if (lowerRow[lidX] <= p.lThr || upperRow[lidX] <= p.uThr) {
      c = 0;
    } else {
      const int scleraX = p.scleraX0 + x;
      const int irisX = scleraX - irisOffX;
      if (!irisRow || irisX < 0 || irisX >= a.irisW) {
        c = scleraRow[scleraX];
      } else {
        c = a.polar[irisY * a.irisW + irisX];
        uint32_t d = (p.iScale * (c & 0x7F)) / 128;
        if (d < (uint32_t)a.irisMapH) {
          c = a.iris[d * a.irisMapW + (a.irisMapW * (c >> 7)) / 512];
        } else {
          c = scleraRow[scleraX];
        }
      }
    }
    out[ox] = (uint16_t)c;
  }
}

// True when output row oy samples the same artwork row as oy - 1.
inline bool repeatsPrevious(int S, int oy) { return oy > 0 && srcMap(S)[oy] == srcMap(S)[oy - 1]; }

}  // namespace eye_render
