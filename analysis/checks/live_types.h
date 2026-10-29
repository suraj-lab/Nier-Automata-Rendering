#pragma once
// Plain data shared by the game-thread capture and the Remix worker. No D3D11 or Remix dependency, so the
// worker side can be compiled and tested natively.
#include <cstdint>
#include <string>
#include <vector>
#include "light_convert.h"

namespace live_capture {

struct Vertex {
    float position[3];
    float normal[3];
    float texcoord[2];
    std::uint32_t color;
};

// Geometry the worker does not have yet (first sight, or a buffer it depends on was rewritten).
struct Upload {
    std::uint64_t geometry = 0;
    std::vector<Vertex> vertices;      // one per distinct referenced vertex
    std::vector<std::uint32_t> indices;// the draw's index list, remapped into `vertices`
    std::vector<std::uint32_t> bones;  // 4 per vertex, only when skinned
    std::vector<float> weights;        // 4 per vertex, only when skinned
    std::uint32_t texture = 0;         // 0 = no material
    bool skinned = false;
    bool blended = false;              // classic alpha blend (src alpha / inv src alpha): foliage, hair, grilles
    bool sky = false;                  // background shell / sky dome: submitted with the SKY category, not as world
    int alpha_op = 7;                  // the pixel shader's alpha test as Remix AlphaTestType (7 = kAlways: none)
    std::uint8_t alpha_ref = 0;        // ... and its 8-bit reference (alpha_test.h)
};
struct Item {                          // one draw call this frame
    std::uint64_t geometry = 0;
    std::uint32_t texture = 0;
    bool blended = false;              // the game drew it with alpha blending (a cutout in Remix terms), never translucency: Remix has no per-draw blend
    bool sky = false;                  // the game's sky dome: instance gets REMIXAPI_INSTANCE_CATEGORY_BIT_SKY
    unsigned first = 0, count = 1;     // range in Frame::transforms
    unsigned first_bone = 0, bone_count = 0;  // range in Frame::bones; 0 = not skinned
};
struct TextureFile { std::uint32_t id = 0; std::wstring path; };
// One game light (point, PS slot 20, or spot, slot 22): see light_convert.h for the layouts and the Remix conversion.
using Light = light_convert::Light;
using Sun = light_convert::Sun;
// The game's HUD: alpha-blended sprites drawn into the final image after the 3D scene. Captured separately because
// they are not world geometry (the render-target filter drops them) but they must come back on top of the Remix image.
struct UiVertex {
    float position[3];   // local space; `world` below maps it into clip space, as the game's own shader does
    float texcoord[2];
};
struct UiDraw {
    unsigned first = 0, count = 0;   // range in Frame::ui
    float world[12];                 // CB11 as 3x4 row-major, straight from the game
    std::uint32_t texture = 0;       // 0 = untextured
};
struct Frame {
    std::vector<Item> items;
    std::vector<Light> lights;  // the game's point-light array for this frame, in bind order
    Sun sun;                    // verified scene PS CB2 sun, when has_sun
    bool has_sun = false;
    std::vector<float> transforms;     // 12 floats per instance: 3x4 row-major world matrix
    std::vector<float> bones;          // 12 floats per bone: 3x4 row-major, straight from the CB11 palette
    unsigned draws = 0, skinned = 0, skipped = 0, skipped_untransformed = 0, skipped_sky = 0;
    unsigned sky = 0;                  // background shells submitted with the SKY category
    unsigned rebuilt_identical = 0;    // rewrites whose decoded content matched the mesh already uploaded
    unsigned small_viewport = 0;       // draws into a viewport < 25% of the frame max (diagnostic only)
    unsigned blended = 0;              // draws the game alpha-blended: submitted as cutout geometry
    // Why the light arrays were or were not read this frame (bits): 1 t20 bound, 2 t20 view is a buffer, 4 t20 stride 48,
    // 8 t20 bytes read; 16 t22 bound, 32 t22 view is a buffer, 64 t22 stride 80, 128 t22 bytes read. 0 = no scene draw
    // had the point-light array bound. Logged as light_state= so a run can never report lights=0 without a reason.
    unsigned light_state = 0;
    unsigned untextured = 0;           // draws submitted with no material: texture not captured, or capture failed
    float max_viewport = 0.f;
    // Render-target filter: the scene is whatever the game draws most into, among targets smaller than the
    // final image. Shadow atlases, bloom chains and post passes are other targets and are not the scene.
    unsigned skipped_pass = 0;         // draws into a target that is not the scene target
    unsigned alpha_tested = 0;         // draws whose pixel shader discards: submitted with an alpha-test material
    unsigned skipped_prepass = 0;      // depth pre-pass draws (layout without any surface attribute): a duplicate of a later draw
    unsigned scene_w = 0, scene_h = 0;// the target the scene was rendered into, as chosen from the last frame
    unsigned target_picks = 0;         // frames where a scene target was chosen at all
    unsigned target_fallbacks = 0;     // frames where the choice left nothing to draw: filter latched off
    std::uint64_t sequence = 0;
    bool valid() const { return !items.empty(); }
};

}  // namespace live_capture
