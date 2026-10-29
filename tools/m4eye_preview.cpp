// Host preview of the M4 eye renderer (src/m4eye): a PPM contact sheet of
// poses for both eyes, one pair of rows per JSON config patch (tints are
// applied by the firmware glue, so they don't show here). Eye set: the
// compiled-in hazel, or a LittleFS folder (data/eyes/<name>).
//
//   c++ -std=c++17 -O2 -Isrc tools/m4eye_preview.cpp src/m4eye/m4eye_config.cpp -o /tmp/m4eye_preview
//   /tmp/m4eye_preview out.ppm [data/eyes/<name> | -] ['{"slitPupilRadius":30}' ...]
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <string>
#include <vector>

#include "m4eye/assets/hazel.h"
#include "m4eye/m4eye_config.h"
#include "m4eye/m4eye_render.h"

using namespace m4eye;

struct Pose {
  float x, y, lid, pupil;
};

static uint16_t be565(const Rgb& c) {
  const uint16_t v = ((c.r & 0xF8) << 8) | ((c.g & 0xFC) << 3) | (c.b >> 3);
  return (v >> 8) | (v << 8);
}

static std::vector<uint8_t> slurp(const std::string& p) {
  std::vector<uint8_t> v;
  FILE* f = fopen(p.c_str(), "rb");
  if (!f) return v;
  uint8_t buf[4096];
  size_t n;
  while ((n = fread(buf, 1, sizeof buf, f)) > 0) v.insert(v.end(), buf, buf + n);
  fclose(f);
  return v;
}

struct Set {
  std::string json;
  std::vector<uint16_t> iris, sclera;
  int irisW = 1, irisH = 1, scleraW = 1, scleraH = 1;
  std::vector<Lids> lids;  // [0] = own
};

static bool tex(const std::string& p, std::vector<uint16_t>& px, int& w, int& h) {
  std::vector<uint8_t> v = slurp(p);
  if (v.size() < 4) return false;
  w = v[0] | v[1] << 8;
  h = v[2] | v[3] << 8;
  px.resize((size_t)w * h);
  memcpy(px.data(), v.data() + 4, px.size() * 2);
  return true;
}

int main(int argc, char** argv) {
  namespace A = m4eye_asset_hazel;
  const char* path = argc > 1 ? argv[1] : "m4eye.ppm";
  Set set;
  if (argc > 2 && strcmp(argv[2], "-")) {
    const std::string d = argv[2];
    std::vector<uint8_t> j = slurp(d + "/config.json");
    set.json.assign(j.begin(), j.end());
    tex(d + "/iris.565", set.iris, set.irisW, set.irisH);
    tex(d + "/sclera.565", set.sclera, set.scleraW, set.scleraH);
    std::vector<uint8_t> l = slurp(d + "/lids.bin");
    if (l.size() == sizeof(Lids)) set.lids.push_back(*(Lids*)l.data());
  } else {
    set.json = A::kConfig;
    set.iris.assign(A::kIris, A::kIris + A::kIrisW * A::kIrisH);
    set.sclera.assign(A::kSclera, A::kSclera + A::kScleraW * A::kScleraH);
    set.irisW = A::kIrisW, set.irisH = A::kIrisH, set.scleraW = A::kScleraW, set.scleraH = A::kScleraH;
    set.lids.push_back(*(const Lids*)A::kLids[0]);
    set.lids.push_back(*(const Lids*)A::kLids[1]);
  }
  argc--, argv++;  // the remaining args are patches, as before
  const Pose poses[] = {{0, 0, 0.72f, 0.45f}, {1, 0, 0.72f, 0.45f}, {-1, 0, 0.72f, 0.45f}, {0, 1, 0.72f, 0.45f},
                        {0, -1, 0.72f, 0.45f}, {0, 0, 1.0f, 0.9f},  {0, 0, 1.0f, 0.0f},   {0, 0, 0.3f, 0.5f},
                        {0, 0, 0.0f, 0.5f}};
  constexpr int P = sizeof(poses) / sizeof(poses[0]), N = kSize, G = 4;
  const int variants = argc > 2 ? argc - 2 : 1;
  const int W = P * (N + G), H = variants * 2 * (N + G);
  uint8_t* img = (uint8_t*)calloc((size_t)W * H, 3);
  static uint16_t row[N];
  for (int vi = 0; vi < variants; vi++) {
    Config c;
    fromJson(set.json.c_str(), c);
    if (argc > 2 && !fromJson(argv[2 + vi], c)) fprintf(stderr, "bad json %s\n", argv[2 + vi]);
    Model m;
    m.t.eyeRadius = c.eyeRadius;
    m.t.irisRadius = c.irisRadius;
    m.t.slitPupilRadius = c.slitPupilRadius;
    m.t.mapRadius = mapRadiusFor(c.eyeRadius, c.coverage);
    uint8_t* mem = (uint8_t*)malloc(kDisplaceBytes + polarBytes(m.t.mapRadius));
    m.t.displace = mem;
    m.t.polarAngle = mem + kDisplaceBytes;
    m.t.polarDist = (int8_t*)(m.t.polarAngle + m.t.mapRadius * m.t.mapRadius);
    buildTables(m.t);
    const uint16_t irisFlat = be565(c.irisColor), scleraFlat = be565(c.scleraColor);
    m.iris = set.iris.empty() ? Texture{&irisFlat, 1, 1} : Texture{set.iris.data(), (uint16_t)set.irisW, (uint16_t)set.irisH};
    m.sclera = set.sclera.empty() ? Texture{&scleraFlat, 1, 1}
                                  : Texture{set.sclera.data(), (uint16_t)set.scleraW, (uint16_t)set.scleraH};
    const size_t lidSet = !strcmp(c.lids, "hazel-symmetrical") ? 1 : 0;
    m.lids = strcmp(c.lids, "none") && lidSet < set.lids.size() ? &set.lids[lidSet] : nullptr;
    m.pupilColor = be565(c.pupilColor);
    m.backColor = be565(c.backColor);
    m.eyelidColor = be565(c.eyelidColor);
    for (int e = 0; e < 2; e++) {
      Look l;
      l.pupilMin = c.pupilMin;
      l.pupilMax = c.pupilMax;
      l.tracking = c.tracking;
      l.squint = c.squint;
      l.gazeRange = c.gazeRange;
      l.lidFlip = (e == 0) != c.lidMirror;  // as m4eye.cpp
      l.irisSpin = c.irisSpin[e];
      l.irisMirror = c.irisMirror[e];
      for (int pi = 0; pi < P; pi++) {
        Anim a;
        Frame f;
        for (int i = 0; i < 20; i++) compute(m, l, poses[pi].x, poses[pi].y, poses[pi].lid, poses[pi].pupil, pi * 1000, a, f);
        for (int y = 0; y < N; y++) {
          m4eye::row(m, f, y, row);
          for (int x = 0; x < N; x++) {
            uint16_t v = (row[x] >> 8) | (row[x] << 8);
            const float dx = x + 0.5f - N / 2, dy = y + 0.5f - N / 2;
            if (dx * dx + dy * dy > (N / 2) * (N / 2)) v = 0x4208;  // outside the round panel
            uint8_t* o = img + 3 * ((size_t)((vi * 2 + e) * (N + G) + y) * W + pi * (N + G) + x);
            o[0] = ((v >> 11) & 31) * 255 / 31;
            o[1] = ((v >> 5) & 63) * 255 / 63;
            o[2] = (v & 31) * 255 / 31;
          }
        }
      }
    }
    free(mem);
  }
  FILE* fo = fopen(path, "wb");
  fprintf(fo, "P6 %d %d 255\n", W, H);
  fwrite(img, 3, (size_t)W * H, fo);
  fclose(fo);
  printf("wrote %s (%dx%d): per variant rows L, R; poses: centre, +x, -x, up, down, wide+dilated, wide+pinpoint, "
         "lid 0.3, closed\n",
         path, W, H);
  return 0;
}
