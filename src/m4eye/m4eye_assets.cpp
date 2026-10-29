#include "m4eye_assets.h"

#include "assets/hazel.h"

namespace m4eye {

const EyeSet kEyeSets[] = {
    {"hazel", m4eye_asset_hazel::kConfig, m4eye_asset_hazel::kIris, m4eye_asset_hazel::kIrisW,
     m4eye_asset_hazel::kIrisH, m4eye_asset_hazel::kSclera, m4eye_asset_hazel::kScleraW, m4eye_asset_hazel::kScleraH,
     m4eye_asset_hazel::kLidSets, m4eye_asset_hazel::kLidNames, m4eye_asset_hazel::kLids},
};
const int kNumEyeSets = sizeof(kEyeSets) / sizeof(kEyeSets[0]);

}  // namespace m4eye
