// Dumps the firmware's eye art tables (same objects the ESP32 links) and a
// checksum per test pose from the firmware renderer, for build.py.
//   dump_art <outdir>   -> <outdir>/<name>.bin + JSON metadata on stdout
#include <stdio.h>
#include <string>

#include "eye_render.h"

static void put(FILE* f, const void* p, size_t n) { fwrite(p, 1, n, f); }  // host is little endian

// Poses shared with eye_render.test.js.
static const float kPoses[][5] = {{0, 0, 0.72f, 0.45f, 0}, {1, 0, 0.72f, 0.45f, 1},  {-0.6f, 0.4f, 1.0f, 0.9f, 0},
                                  {0.3f, -1, 0.45f, 0.3f, 1}, {0, 0, 0.2f, 0.5f, 0}};

int main(int argc, char** argv) {
  std::string dir = argc > 1 ? argv[1] : ".";
  const EyeArt* arts[] = {&kDefaultEye, &kDragonEye};
  printf("[");
  for (int i = 0; i < 2; i++) {
    const EyeArt& a = *arts[i];
    FILE* f = fopen((dir + "/" + a.name + ".bin").c_str(), "wb");
    put(f, a.sclera, a.scleraW * a.scleraH * 2);
    put(f, a.iris, a.irisMapW * a.irisMapH * 2);
    put(f, a.upper, a.lidSize * a.lidSize);
    put(f, a.lower, a.lidSize * a.lidSize);
    put(f, a.polar, a.irisW * a.irisH * 2);
    fclose(f);
    printf("%s{\"name\":\"%s\",\"scleraW\":%d,\"scleraH\":%d,\"irisMapW\":%d,\"irisMapH\":%d,\"lidSize\":%d,"
           "\"irisW\":%d,\"irisH\":%d,\"irisMin\":%d,\"irisMax\":%d,\"checksums\":[",
           i ? "," : "", a.name, a.scleraW, a.scleraH, a.irisMapW, a.irisMapH, a.lidSize, a.irisW, a.irisH,
           a.irisMin, a.irisMax);
    for (size_t k = 0; k < sizeof(kPoses) / sizeof(kPoses[0]); k++) {
      const float* q = kPoses[k];
      int track = 128;
      eye_render::Params p{};
      for (int n = 0; n < 5; n++) p = eye_render::compute(a, q[0], q[1], q[2], q[3], q[4] != 0, track);
      uint32_t h = 2166136261u;  // FNV-1a over all pixels
      uint16_t row[eye_render::kOut];
      for (int y = 0; y < eye_render::kOut; y++) {
        eye_render::row(a, p, y, row);
        for (int x = 0; x < eye_render::kOut; x++) h = (h ^ row[x]) * 16777619u;
      }
      printf("%s%u", k ? "," : "", h);
    }
    printf("]}");
  }
  printf("]\n");
}
