// Renders eye frames on the host with the firmware's renderer, for checking
// artwork/lid/gaze maths without hardware. Writes one PPM contact sheet.
//
//   c++ -std=c++17 -O2 -Itools/host_shim -Isrc tools/eye_preview.cpp \
//       src/eye_art/default_eye.cpp src/eye_art/dragon_eye.cpp -o /tmp/eye_preview
//   /tmp/eye_preview out.ppm
#include <stdio.h>

#include "../include/config.h"
#include "eye_render.h"

struct Pose {
  float x, y, lid, pupil;
};

int main(int argc, char** argv) {
  const char* path = argc > 1 ? argv[1] : "eyes.ppm";
  const Pose poses[] = {{0, 0, 0.72f, 0.45f},  {1, 0, 0.72f, 0.45f},  {-1, 0, 0.72f, 0.45f},
                        {0, 1, 0.72f, 0.45f},  {0, -1, 0.72f, 0.45f}, {0, 0, 1.0f, 0.9f},
                        {0, 0, 0.45f, 0.3f},   {0, 0, 0.2f, 0.5f},    {0, 0, 0.0f, 0.5f}};
  const EyeArt* arts[] = {&kDefaultEye, &kDragonEye};
  constexpr int P = sizeof(poses) / sizeof(poses[0]);
  constexpr int N = eye_render::kOut, G = 4;
  const int W = P * (N + G), H = 4 * (N + G);  // rows: default L/R, dragon L/R
  static uint8_t img[4 * (N + G)][P * (N + G)][3];
  uint16_t row[N];
  for (int ai = 0; ai < 2; ai++) {
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
            uint8_t* o = img[(ai * 2 + e) * (N + G) + y][pi * (N + G) + x];
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
  fwrite(img, 1, sizeof(img), f);
  fclose(f);
  printf("wrote %s (%dx%d): columns = centre, +x, -x, up, down, wide, goodbye, droopy, closed;\n"
         "rows = default L, default R, dragon L, dragon R (L = skull's left = viewer's right)\n", path, W, H);
}
