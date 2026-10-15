// NeoPixel backup eyes (milestone 8). Placeholder so the backend switch links.
#include "eyes.h"

namespace {

class PixelEyes : public EyeBackend {
 public:
  const char* name() const override { return "pixel"; }
  bool begin() override {
    Serial.println("eyes: NeoPixel backend not implemented yet (milestone 8)");
    return true;
  }
  void draw(const EyeState&, const EyeState&) override { delay(33); }
};

}  // namespace

EyeBackend* makePixelEyes() {
  static PixelEyes instance;
  return &instance;
}
