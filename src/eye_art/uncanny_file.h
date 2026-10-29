// Uncanny Eyes artwork as one file (data/uncanny/<name>.eye, written by
// tools/uncanny_convert.py): the same tables the compiled-in default/dragon
// headers hold, little-endian, in this order after a 28-byte header:
//
//   "UEYE", u16 version 1, u16 flags (bit 0: no lid tracking),
//   u16 scleraW, scleraH, irisMapW, irisMapH, lidSize, irisW, irisH,
//       irisMin, irisMax, reserved
//   u16 sclera[scleraH*scleraW], u16 iris[irisMapH*irisMapW],
//   u8 upper[lidSize^2], u8 lower[lidSize^2], u16 polar[irisH*irisW]
//
// parse() points an EyeArt into the loaded buffer (no copy). Shared by the
// firmware loader (uncanny_store.cpp) and tools/eye_preview.cpp.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "eye_art.h"

namespace uncanny_file {

constexpr size_t kHeader = 28;

inline uint16_t u16(const uint8_t* p) { return (uint16_t)(p[0] | (p[1] << 8)); }

// buf must be 2-byte aligned and outlive `a`. False if it isn't a valid file.
inline bool parse(const uint8_t* buf, size_t n, const char* name, EyeArt& a) {
  if (n < kHeader || memcmp(buf, "UEYE", 4) || u16(buf + 4) != 1 || ((uintptr_t)buf & 1)) return false;
  const uint16_t flags = u16(buf + 6);
  const uint8_t* h = buf + 8;
  const int sw = u16(h), sh = u16(h + 2), mw = u16(h + 4), mh = u16(h + 6), S = u16(h + 8), iw = u16(h + 10),
            ih = u16(h + 12);
  if (S != 128 || sw < S || sh < S || !mw || !mh || !iw || !ih || iw > sw || ih > sh) return false;
  const size_t need = kHeader + 2u * sw * sh + 2u * mw * mh + 2u * S * S + 2u * iw * ih;
  if (n < need) return false;
  const uint8_t* p = buf + kHeader;
  a = {};
  a.name = name;
  a.sclera = (const uint16_t*)p;
  a.scleraW = sw;
  a.scleraH = sh;
  p += 2u * sw * sh;
  a.iris = (const uint16_t*)p;
  a.irisMapW = mw;
  a.irisMapH = mh;
  p += 2u * mw * mh;
  a.upper = p;
  a.lower = p + S * S;
  a.lidSize = S;
  p += 2u * S * S;
  a.polar = (const uint16_t*)p;
  a.irisW = iw;
  a.irisH = ih;
  a.irisMin = u16(h + 14);
  a.irisMax = u16(h + 16);
  a.noTracking = flags & 1;
  return true;
}

}  // namespace uncanny_file
