// Renders eye frames on the host with the firmware's renderer, for checking
// artwork/lid/gaze maths without hardware. Writes one PPM contact sheet.
//
//   c++ -std=c++17 -O2 -Itools/host_shim -Isrc tools/eye_preview.cpp \
//       src/eye_art/default_eye.cpp src/eye_art/dragon_eye.cpp -o /tmp/eye_preview
//   /tmp/eye_preview out.ppm [data/uncanny/cat.eye ...] [--tint ih,is,it,sh,ss,st]
//
// Rows: default L/R, dragon L/R, then L/R for each .eye file given.
// --tint: iris hue, sat %, tint (hex rrggbb), sclera hue, sat %, tint, as the
// iris_hue ... sclera_tint settings (e.g. --tint 120,100,ffffff,0,100,ffc0c0).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <vector>

#include "../include/config.h"
#include "eye_art/eye_tint.h"
#include "eye_art/uncanny_file.h"
#include "eye_render.h"

struct Pose {
  float x, y, lid, pupil;
};

// Tinted copy of a's textures (leaks; it's a one-shot tool).
static const EyeArt* tinted(const EyeArt* a, const eye_tint::Tint& ti, const eye_tint::Tint& ts) {
  EyeArt* o = new EyeArt(*a);
  if (!ti.neutral()) {
    uint16_t* b = new uint16_t[a->irisMapW * a->irisMapH];
    eye_tint::applyAll(eye_tint::matrix(ti), a->iris, b, a->irisMapW * a->irisMapH);
    o->iris = b;
  }
  if (!ts.neutral()) {
    uint16_t* b = new uint16_t[a->scleraW * a->scleraH];
    eye_tint::applyAll(eye_tint::matrix(ts), a->sclera, b, a->scleraW * a->scleraH);
    o->sclera = b;
  }
  return o;
}

int main(int argc, char** argv) {
  const char* path = argc > 1 ? argv[1] : "eyes.ppm";
  std::vector<const EyeArt*> arts = {&kDefaultEye, &kDragonEye};
  eye_tint::Tint ti{0, 100, 0xFFFFFF}, ts{0, 100, 0xFFFFFF};
  for (int i = 2; i < argc; i++) {
    if (!strcmp(argv[i], "--tint") && i + 1 < argc) {
      unsigned a, b;
      if (sscanf(argv[++i], "%d,%d,%x,%d,%d,%x", &ti.hue, &ti.sat, &a, &ts.hue, &ts.sat, &b) != 6) {
        fprintf(stderr, "--tint ih,is,it,sh,ss,st\n");
        return 1;
      }
      ti.rgb = a;
      ts.rgb = b;
      continue;
    }
    FILE* f = fopen(argv[i], "rb");
    if (!f) return perror(argv[i]), 1;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t* buf = (uint8_t*)malloc(n);
    if (fread(buf, 1, n, f) != (size_t)n) return perror(argv[i]), 1;
    fclose(f);
    EyeArt* a = new EyeArt;
    if (!uncanny_file::parse(buf, n, argv[i], *a)) {
      fprintf(stderr, "%s: not an eye file\n", argv[i]);
      return 1;
    }
    arts.push_back(a);
  }
  for (auto& a : arts) a = tinted(a, ti, ts);

  const Pose poses[] = {{0, 0, 0.72f, 0.45f},  {1, 0, 0.72f, 0.45f},  {-1, 0, 0.72f, 0.45f},
                        {0, 1, 0.72f, 0.45f},  {0, -1, 0.72f, 0.45f}, {0, 0, 1.0f, 0.9f},
                        {0, 0, 0.45f, 0.3f},   {0, 0, 0.2f, 0.5f},    {0, 0, 0.0f, 0.5f}};
  constexpr int P = sizeof(poses) / sizeof(poses[0]);
  constexpr int N = eye_render::kOut, G = 4;
  const int rows = 2 * (int)arts.size();
  const int W = P * (N + G), H = rows * (N + G);
  std::vector<uint8_t> img((size_t)W * H * 3, 0);
  uint16_t row[N];
  for (size_t ai = 0; ai < arts.size(); ai++) {
    for (int e = 0; e < 2; e++) {
      for (int pi = 0; pi < P; pi++) {
        int track = 128;
        eye_render::Params p{};
        // Let the lid smoothing settle like a held pose would.
        for (int i = 0; i < 20; i++)
          p = eye_render::compute(*arts[ai], poses[pi].x, poses[pi].y, poses[pi].lid, poses[pi].pupil,
                                  e == 0 ? EYE_L_LID_FLIP : EYE_R_LID_FLIP, track);
        for (int y = 0; y < N; y++) {
          eye_render::row(*arts[ai], p, y, row);
          for (int x = 0; x < N; x++) {
            uint16_t c = row[x];
            uint8_t* o = &img[(((ai * 2 + e) * (N + G) + y) * (size_t)W + pi * (N + G) + x) * 3];
            o[0] = ((c >> 11) & 31) * 255 / 31;
            o[1] = ((c >> 5) & 63) * 255 / 63;
            o[2] = (c & 31) * 255 / 31;
          }
        }
      }
    }
  }
  FILE* f = fopen(path, "wb");
  fprintf(f, "P6 %d %d 255\n", W, H);
  fwrite(img.data(), 1, img.size(), f);
  fclose(f);
  printf("wrote %s (%dx%d): columns = centre, +x, -x, up, down, wide, goodbye, droopy, closed;\n"
         "rows = L and R (L = skull's left = viewer's right) for default, dragon",
         path, W, H);
  for (size_t i = 2; i < arts.size(); i++) printf(", %s", arts[i]->name);
  printf("\n");
}
