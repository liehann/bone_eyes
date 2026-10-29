// Port of the Adafruit M4_Eyes renderer (Phillip Burgess, MIT; see
// LICENSE.md) to one 160x160 panel. Hardware-independent: the firmware glue
// (m4eye.cpp) and the host preview (tools/m4eye_preview.cpp) both use it.
//
// Same maths as M4_Eyes.ino / tablegen.cpp:
//  - a quarter-screen displacement map fakes the eyeball's curvature;
//  - a quarter polar map (angle, signed distance) turns the displaced point
//    into iris or sclera texture coordinates; slit pupils reshape the iris
//    part of the distance map;
//  - eyelids are per-column open/closed extents from 1-bit bitmaps.
// Differences: rendered row-major (top to bottom) instead of column-major,
// output is a big-endian RGB565 row, eyelid extents are per frame per
// column, pixels outside the round panel's visible circle are skipped.
#pragma once
#include <math.h>
#include <stdint.h>
#include <string.h>

namespace m4eye {

constexpr int kSize = 160;
constexpr int kHalf = kSize / 2;

// Polar + displacement tables. Built by buildTables(), memory supplied by
// the caller (internal RAM or PSRAM, see m4eye.cpp).
struct Tables {
  uint8_t* displace = nullptr;  // kHalf * kHalf, 255 = outside the eye
  uint8_t* polarAngle = nullptr;  // mapRadius^2, 0..255 per quadrant
  int8_t* polarDist = nullptr;    // mapRadius^2: >=0 sclera, -1..-127 iris, -128 off map
  int mapRadius = 0;
  int eyeRadius = 0, irisRadius = 0, slitPupilRadius = 0;
};

struct Texture {
  const uint16_t* data;  // big-endian RGB565, w * h
  uint16_t w, h;
};

// One eyelid set: per screen column (x left to right), y counted upward
// from the bottom row.
struct Lids {
  uint8_t upperOpen[kSize], upperClosed[kSize], lowerOpen[kSize], lowerClosed[kSize];
};

// Everything the per-pixel loop reads, for one eye. Shared by both eyes
// except where noted in Frame.
struct Model {
  Tables t;
  Texture iris = {nullptr, 1, 1}, sclera = {nullptr, 1, 1};
  const Lids* lids = nullptr;  // nullptr = no lids (round eye)
  uint16_t pupilColor = 0, backColor = 0, eyelidColor = 0;  // big-endian
};

// Per eye, per frame. Computed by compute() on the core that simulates the
// eye; read by both cores while rendering.
struct Frame {
  int xPos, yPos;          // window origin over the polar map
  int iPupilFactor;        // iris.h * 256 / pupilFactor
  uint16_t irisAngle, scleraAngle;  // 0..1023
  uint16_t irisMirror, scleraMirror;  // 0 or 1023
  uint8_t y1[kSize], y2[kSize];  // open span per column: rows y1..y2 (from bottom)
};

// Per-eye animation state carried between frames.
struct Anim {
  float upperLid = 1, lowerLid = 1;  // smoothed lid factors (1 = open)
  // Own blink (M4_Eyes timing), only when Params::blinkRate > 0.
  uint8_t blinkState = 0;  // 0 none, 1 closing, 2 opening
  uint32_t blinkStartMs = 0, blinkDurMs = 0, nextBlinkMs = 0;
  uint32_t lastIrisSpinMs = 0;
};

// Per-frame inputs that don't come from the eye animator.
struct Look {
  float pupilMin = 0.2f, pupilMax = 0.55f;  // pupil size range, fraction of the iris
  float squint = 0.5f;    // upper lid tracking offset (M4 "squint")
  bool tracking = true;   // lids follow the pupil
  float gazeRange = 0.9f; // fraction of the largest travel that keeps the map on screen
  float irisSpin = 0, scleraSpin = 0;  // RPM
  int irisAngle = 0, scleraAngle = 0;  // 0..1023 start angle
  bool irisMirror = false, scleraMirror = false;
  bool lidFlip = false;   // mirror the lid art left-right (per eye)
  float blinkRate = 0;    // own blinks per minute (0 = only the animator's)
};

// ---------------------------------------------------------------------------
// Tables (tablegen.cpp)

inline int mapRadiusFor(int eyeRadius, float coverage) { return (int)(eyeRadius * (float)M_PI * coverage + 0.5f); }
inline size_t polarBytes(int mapRadius) { return (size_t)mapRadius * mapRadius * 2; }
constexpr size_t kDisplaceBytes = kHalf * kHalf;

inline float screen2map(const Tables& t, int in) {
  return atan2f((float)in, sqrtf((float)(t.eyeRadius * t.eyeRadius - in * in))) / (float)M_PI_2 * t.mapRadius;
}
inline float map2screen(const Tables& t, float in) {
  return sinf(in / (float)t.mapRadius) * (float)M_PI_2 * t.eyeRadius;
}

inline void calcDisplacement(Tables& t) {
  const float r2 = (float)(t.eyeRadius * t.eyeRadius);
  uint8_t* p = t.displace;
  for (int y = 0; y < kHalf; y++) {
    float dy = y + 0.5f;
    dy *= dy;
    for (int x = 0; x < kHalf; x++) {
      float dx = x + 0.5f;
      const float d2 = dx * dx + dy;
      if (d2 <= r2) {
        const float d = sqrtf(d2), h = sqrtf(r2 - d2);
        const float pa = atan2f(d, h) / (float)M_PI_2 * t.mapRadius;
        dx /= d;
        *p++ = (uint8_t)(int)(dx * pa) - x;
      } else {
        *p++ = 255;
      }
    }
  }
}

inline void calcMap(Tables& t) {
  const int R = t.mapRadius;
  const float R2 = (float)R * R;
  const float iRad = screen2map(t, t.irisRadius), iRad2 = iRad * iRad;
  uint8_t* ap = t.polarAngle;
  int8_t* dp = t.polarDist;
  for (int y = 0; y < R; y++) {
    const float dy = y + 0.5f, dy2 = dy * dy;
    for (int x = 0; x < R; x++) {
      const float dx = x + 0.5f, d2 = dx * dx + dy2;
      if (d2 > R2) {
        *ap++ = 0;
        *dp++ = -128;
        continue;
      }
      float angle = atan2f(dy, dx);
      angle = (float)M_PI_2 - angle;
      angle *= 512.0f / (float)M_PI;
      *ap++ = (uint8_t)angle;
      const float d = sqrtf(d2);
      if (d2 > iRad2) {
        *dp++ = (int8_t)((R - d) / (R - iRad) * 127.0f);
      } else {
        *dp++ = (int8_t)((int8_t)((iRad - d) / iRad * -127.0f) - 1);
      }
    }
  }
  if (t.slitPupilRadius <= 0) return;
  // Slit pupil: re-solve the iris part of the distance map so the pupil
  // opens from a vertical slit (M4_Eyes' iterative circle fit).
  const float slit = screen2map(t, t.slitPupilRadius);
  for (int y = 0; y < R; y++) {
    const float dy = y + 0.5f, dy2 = dy * dy;
    for (int x = 0; x < R; x++) {
      const float xp = x + 0.5f;
      if (xp * xp + dy2 > iRad2) continue;
      for (int i = 126; i >= 0; i--) {
        const float ratio = i / 128.0f;
        const float y1 = iRad - (iRad - slit) * ratio;
        const float x2 = iRad * (1.0f - ratio);
        const float xc = (x2 * x2 - y1 * y1) / (2 * x2);
        const float rx = x2 - xc, r2 = rx * rx;
        const float ddx = xp - xc;
        if (ddx * ddx + dy2 <= r2) {
          t.polarDist[y * R + x] = (int8_t)(-1 - i);
          break;
        }
      }
    }
  }
}

// t.displace/polarAngle/polarDist must already hold kDisplaceBytes and
// polarBytes(mapRadius) bytes (polarDist = polarAngle + mapRadius^2).
inline void buildTables(Tables& t) {
  calcDisplacement(t);
  calcMap(t);
}

// ---------------------------------------------------------------------------
// Per frame (M4_Eyes.ino loop(), first column)

// gazeX/gazeY -1..1 (+x = skull's right = viewer's left, +y = up). lid:
// bone_eyes convention, 0 closed .. 0.75 normal .. 1 wide (blinks included).
// pupil 0..1 maps onto look.pupilMin..pupilMax.
inline void compute(const Model& m, const Look& look, float gazeX, float gazeY, float lid, float pupil,
                    uint32_t nowMs, Anim& a, Frame& f) {
  auto clampf = [](float v, float lo, float hi) { return v < lo ? lo : v > hi ? hi : v; };
  const Tables& t = m.t;
  const int R = t.mapRadius;

  // Gaze: keep within the unit circle so diagonals don't run off the map.
  float gx = clampf(gazeX, -1, 1), gy = clampf(gazeY, -1, 1);
  const float g2 = gx * gx + gy * gy;
  if (g2 > 1) {
    const float s = 1 / sqrtf(g2);
    gx *= s;
    gy *= s;
  }
  const float r = ((float)R * 2 - kSize * (float)M_PI_2) * clampf(look.gazeRange, 0, 1);
  const float eyeX = R + gx * r;  // larger = iris further left on screen
  const float eyeY = R - gy * r;  // larger = iris further down
  f.xPos = (int)(eyeX - kSize / 2.0f);
  f.yPos = (int)(eyeY - kSize / 2.0f);

  // Pupil.
  float pMin = clampf(look.pupilMin, 0, 1), pMax = clampf(look.pupilMax, 0, 1);
  if (pMin > pMax) {
    const float s = pMin;
    pMin = pMax;
    pMax = s;
  }
  float pf = 1.0f - (pMin + clampf(pupil, 0, 1) * (pMax - pMin));  // M4 "irisValue"
  if (pf < 0.01f) pf = 0.01f;
  f.iPupilFactor = (int)((float)m.iris.h * 256 * (1.0f / pf));

  // Spin.
  const float mins = nowMs / 60000.0f;
  f.irisAngle = (uint16_t)((int)((1023 - (look.irisAngle & 1023)) - look.irisSpin * 1024.0f * mins + 0.5f) & 1023);
  f.scleraAngle =
      (uint16_t)((int)((1023 - (look.scleraAngle & 1023)) - look.scleraSpin * 1024.0f * mins + 0.5f) & 1023);
  f.irisMirror = look.irisMirror ? 1023 : 0;
  f.scleraMirror = look.scleraMirror ? 1023 : 0;

  // Own blinks.
  float blink = 0;
  if (look.blinkRate > 0) {
    if (!a.nextBlinkMs) a.nextBlinkMs = nowMs + 1000;
    if (!a.blinkState && (int32_t)(nowMs - a.nextBlinkMs) >= 0) {
      a.blinkState = 1;
      a.blinkStartMs = nowMs;
      a.blinkDurMs = 36 + (nowMs * 2654435761u >> 27);  // 36..67 ms, cheap pseudo-random
      const float mean = 60000.0f / look.blinkRate;
      a.nextBlinkMs = nowMs + (uint32_t)(mean * (0.5f + ((nowMs * 40503u >> 8) & 255) / 255.0f));
    }
    if (a.blinkState) {
      const uint32_t e = nowMs - a.blinkStartMs;
      if (e >= a.blinkDurMs) {
        if (++a.blinkState > 2) {
          a.blinkState = 0;
        } else {
          a.blinkDurMs *= 2;  // opening is half the speed
          a.blinkStartMs = nowMs;
          blink = 1;
        }
      } else {
        blink = (float)e / a.blinkDurMs;
        if (a.blinkState == 2) blink = 1 - blink;
      }
    }
  } else {
    a.blinkState = 0;
  }

  // Lids. Tracking: the upper lid sits just above the pupil.
  float uq = 1, lq = 1;
  if (m.lids && look.tracking) {
    const Lids& L = *m.lids;
    int ix = (int)map2screen(t, R - eyeX) + kHalf;
    int iy = (int)map2screen(t, R - eyeY) + kHalf;
    iy += (int)(t.irisRadius * clampf(1 - look.squint, 0, 1));
    if (look.lidFlip) ix = kSize - 1 - ix;
    ix = ix < 0 ? 0 : ix >= kSize ? kSize - 1 : ix;
    if (iy > L.upperOpen[ix]) uq = 1;
    else if (iy < L.upperClosed[ix]) uq = 0;
    else uq = (float)(iy - L.upperClosed[ix]) / (float)(L.upperOpen[ix] - L.upperClosed[ix]);
    lq = 1 - uq;
  }
  // Wide-eyed moods (lid > 0.75) pull the lids out of tracking.
  if (lid > 0.75f) {
    const float w = clampf((lid - 0.75f) / 0.25f, 0, 1);
    uq += (1 - uq) * w;
    lq += (1 - lq) * w;
  }
  a.upperLid = a.upperLid * 0.6f + uq * 0.4f;
  a.lowerLid = a.lowerLid * 0.6f + lq * 0.4f;
  const float open = clampf(lid / 0.75f, 0, 1) * (1 - blink);
  const float uf = open * a.upperLid, lf = open * a.lowerLid;

  if (!m.lids) {
    // Round eye: no lid art, but blinks/closing still sweep a straight lid.
    const int c = (int)((1 - open) * kHalf + 0.5f);
    for (int x = 0; x < kSize; x++) {
      f.y1[x] = (uint8_t)c;
      f.y2[x] = (uint8_t)(kSize - 1 - c);
    }
    return;
  }
  const Lids& L = *m.lids;
  for (int x = 0; x < kSize; x++) {
    const int lx = look.lidFlip ? kSize - 1 - x : x;
    int y1 = L.lowerClosed[lx] + (int)(0.5f + lf * (float)((int)L.lowerOpen[lx] - (int)L.lowerClosed[lx]));
    int y2 = L.upperClosed[lx] + (int)(0.5f + uf * (float)((int)L.upperOpen[lx] - (int)L.upperClosed[lx]));
    y1 = y1 < 0 ? 0 : y1 > kSize - 1 ? kSize - 1 : y1;
    y2 = y2 < 0 ? 0 : y2 > kSize - 1 ? kSize - 1 : y2;
    if (y1 >= y2) {  // closed: empty span
      y1 = kSize - 1;
      y2 = 0;
    }
    f.y1[x] = (uint8_t)y1;
    f.y2[x] = (uint8_t)y2;
  }
}

// ---------------------------------------------------------------------------
// Per pixel (M4_Eyes.ino loop(), per column)

// Visible half-width of each row on the round panel (pixels beyond it are
// never seen). Built once.
inline const uint8_t* visibleSpan() {
  static uint8_t span[kSize];
  static bool built = false;
  if (!built) {
    for (int y = 0; y < kSize; y++) {
      const float dy = y + 0.5f - kHalf;
      const float w = sqrtf((float)(kHalf * kHalf) - dy * dy);
      int s = (int)(w + 1.5f);  // a pixel of margin
      span[y] = (uint8_t)(s > kHalf ? kHalf : s);
    }
    built = true;
  }
  return span;
}

// Render output row oy (0 = top) as big-endian RGB565.
inline void row(const Model& m, const Frame& f, int oy, uint16_t* out) {
  const Tables& t = m.t;
  const int R = t.mapRadius, D = R * 2;
  const uint8_t* disp = t.displace;
  const uint8_t* pa = t.polarAngle;
  const int8_t* pd = t.polarDist;
  const uint16_t lidC = m.eyelidColor, backC = m.backColor, pupilC = m.pupilColor;
  const uint16_t* irisD = m.iris.data;
  const uint16_t* sclD = m.sclera.data;
  const int irisW = m.iris.w, irisH = m.iris.h, sclW = m.sclera.w, sclH = m.sclera.h;
  const int iPF = f.iPupilFactor;

  const int y = kSize - 1 - oy;  // M4 space: y up from the bottom
  const int doff = y < kHalf ? kHalf - 1 - y : y - kHalf;
  const int ysgn = y < kHalf ? -1 : 1;
  const int yy = f.yPos + y;
  const int vis = visibleSpan()[oy];
  const int x0 = kHalf - vis, x1 = kHalf + vis;

  for (int x = 0; x < x0; x++) out[x] = lidC;
  for (int x = x1; x < kSize; x++) out[x] = lidC;
  const uint8_t* dRow = disp + doff * kHalf;  // dx = dRow[xi]; dy = disp[xi * kHalf + doff]
  for (int x = x0; x < x1; x++) {
    if (y < f.y1[x] || y > f.y2[x]) {
      out[x] = lidC;
      continue;
    }
    int xi, xsgn;
    if (x < kHalf) xi = kHalf - 1 - x, xsgn = -1;
    else xi = x - kHalf, xsgn = 1;
    const int dxr = dRow[xi];
    if (dxr == 255) {
      out[x] = lidC;
      continue;
    }
    int mx = f.xPos + x + xsgn * dxr;
    int my = yy + ysgn * disp[xi * kHalf + doff];
    if ((unsigned)mx >= (unsigned)D || (unsigned)my >= (unsigned)D) {
      out[x] = backC;
      continue;
    }
    int angle, dist;
    if (my >= R) {
      if (mx >= R) {  // quadrant 1
        mx -= R;
        my -= R;
        const int o = my * R + mx;
        angle = pa[o];
        dist = pd[o];
      } else {  // quadrant 2
        mx = R - 1 - mx;
        my -= R;
        angle = pa[mx * R + my] + 768;
        dist = pd[my * R + mx];
      }
    } else {
      if (mx < R) {  // quadrant 3
        mx = R - 1 - mx;
        my = R - 1 - my;
        const int o = my * R + mx;
        angle = pa[o] + 512;
        dist = pd[o];
      } else {  // quadrant 4
        mx -= R;
        my = R - 1 - my;
        angle = pa[mx * R + my] + 256;
        dist = pd[my * R + mx];
      }
    }
    uint16_t c;
    if (dist >= 0) {  // sclera
      angle = ((angle + f.scleraAngle) & 1023) ^ f.scleraMirror;
      const int tx = (angle * sclW) >> 10, ty = (dist * sclH) >> 7;
      c = sclD[ty * sclW + tx];
    } else if (dist > -128) {  // iris or pupil
      const int ty = (-dist * iPF) >> 15;
      if (ty >= irisH) {
        c = pupilC;
      } else {
        angle = ((angle + f.irisAngle) & 1023) ^ f.irisMirror;
        const int tx = (angle * irisW) >> 10;
        c = irisD[ty * irisW + tx];
      }
    } else {
      c = backC;  // back of the eye
    }
    out[x] = c;
  }
}

}  // namespace m4eye
