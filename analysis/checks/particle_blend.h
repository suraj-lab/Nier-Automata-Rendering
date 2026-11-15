#pragma once
// E1.6 (PLAN_2026-11-14): an effect quad submitted as a Remix PARTICLE instance carrying the game's own blend state
// (remixapi_InstanceInfoBlendEXT). Two facts, both read from the runtime source kept in this repository, drive this file:
//  - the EXT's factor/op fields are cast straight to VkBlendFactor / VkBlendOp, not into D3D11's numbering
//    (runtime/remix-source/0ba9973fd856e29fe9cf8dd2f2bc754bcbb2037a/rtx_remix_api.cpp:861-867), and D3D11 numbers the
//    same states differently (D3D11 ONE is 2, VK_BLEND_FACTOR_ONE is 1; D3D11 DEST_COLOR is 9, VK's is 4);
//  - the runtime enables blending only for the (op, src, dst) combinations it recognises and draws everything else as an
//    opaque alias (runtime/src/dxvk-remix/src/dxvk/rtx_render/rtx_instance_manager.cpp:771-860). A state it does not
//    know must be refused before submission, not sent and quietly turned solid.
// Plain C++ with no D3D11 or Remix dependency: the game thread decides eligibility and the worker fills the struct, from
// this one table.
#include <cstdint>
namespace particle_blend {
// D3D11_RENDER_TARGET_BLEND_DESC, in the numbering D3D11 reports from GetDesc.
struct State {
    bool enable = false;              // BlendEnable
    bool alpha_to_coverage = false;   // AlphaToCoverageEnable: coverage, not a blend
    unsigned src = 0, dst = 0, op = 0;                     // SrcBlend, DestBlend, BlendOp
    unsigned src_alpha = 0, dst_alpha = 0, op_alpha = 0;   // SrcBlendAlpha, DestBlendAlpha, BlendOpAlpha
    unsigned write_mask = 0;                               // RenderTargetWriteMask
};
// remixapi_InstanceInfoBlendEXT, in the runtime's numbering (VkBlendFactor, VkBlendOp, VkColorComponentFlags).
struct Mapped {
    bool ok = false;
    std::uint32_t enable_blending = 0;
    std::uint32_t src_color = 0, dst_color = 0, color_op = 0;
    std::uint32_t src_alpha = 0, dst_alpha = 0, alpha_op = 0;
    std::uint32_t write_mask = 0;
};
inline constexpr std::uint32_t kUnmappable = 0xffffffffu;
// D3D11_BLEND -> VkBlendFactor. BlendFactor/InvBlendFactor are refused: they need the blend constant as well, and this
// path sends none (the EXT's tFactor stays 0).
inline std::uint32_t factor(unsigned d3d) {
    switch (d3d) {
        case 1: return 0;    // ZERO
        case 2: return 1;    // ONE
        case 3: return 2;    // SRC_COLOR
        case 4: return 3;    // INV_SRC_COLOR -> ONE_MINUS_SRC_COLOR
        case 9: return 4;    // DEST_COLOR
        case 10: return 5;   // INV_DEST_COLOR -> ONE_MINUS_DST_COLOR
        case 5: return 6;    // SRC_ALPHA
        case 6: return 7;    // INV_SRC_ALPHA -> ONE_MINUS_SRC_ALPHA
        case 7: return 8;    // DEST_ALPHA
        case 8: return 9;    // INV_DEST_ALPHA -> ONE_MINUS_DST_ALPHA
        case 11: return 14;  // SRC_ALPHA_SAT -> SRC_ALPHA_SATURATE
        case 16: return 15;  // SRC1_COLOR
        case 17: return 16;  // INV_SRC1_COLOR -> ONE_MINUS_SRC1_COLOR
        case 18: return 17;  // SRC1_ALPHA
        case 19: return 18;  // INV_SRC1_ALPHA -> ONE_MINUS_SRC1_ALPHA
        default: return kUnmappable;
    }
}
// The colour-factor pairs the runtime turns into a real blend (rtx_instance_manager.cpp:771-860), as {src, dst} in VK
// numbering. ONE/ZERO is its "opaque alias" -- blending is switched off there -- so it is deliberately absent.
inline bool blendable(std::uint32_t src, std::uint32_t dst) {
    static constexpr std::uint32_t pairs[][2] = {
        {6, 7}, {7, 6},   // alpha, inverted alpha
        {6, 1}, {7, 1},   // emissive alpha, inverted emissive alpha
        {1, 6},           // reverse emissive alpha
        {1, 7},           // premultiplied alpha
        {2, 3}, {3, 2},   // colour, inverted colour
        {2, 1}, {3, 1},   // emissive colour, inverted emissive colour
        {1, 2},           // reverse emissive colour
        {1, 3},           // emissive colour
        {1, 1},           // additive: the E1.6 case (ONE/ONE -> BlendType::kEmissive)
        {4, 0}, {0, 2},   // multiplicative
        {4, 2},           // double multiplicative
    };
    for (const auto& p : pairs)
        if (p[0] == src && p[1] == dst) return true;
    return false;
}
// One draw's state -> the EXT struct's fields, or ok = false so the caller leaves the draw out and counts the refusal.
inline Mapped map(const State& s) {
    Mapped out;
    constexpr unsigned kD3D11BlendOpAdd = 1;   // VK_BLEND_OP_ADD is 0: the runtime disables blending for every other op
    if (!s.enable || s.alpha_to_coverage || s.op != kD3D11BlendOpAdd || s.op_alpha != kD3D11BlendOpAdd) return out;
    if (s.write_mask == 0) return out;   // nothing would be visible
    out.src_color = factor(s.src);
    out.dst_color = factor(s.dst);
    out.src_alpha = factor(s.src_alpha);
    out.dst_alpha = factor(s.dst_alpha);
    if (out.src_color == kUnmappable || out.dst_color == kUnmappable || out.src_alpha == kUnmappable ||
        out.dst_alpha == kUnmappable || !blendable(out.src_color, out.dst_color))
        return out;
    // ONE / ONE_MINUS_SRC_ALPHA is premultiplied alpha only with an alpha state that says so (or with alpha writes off).
    // Without that the runtime reads the same colour pair as its inverted reverse-emissive blend
    // (rtx_instance_manager.cpp:794-812), which is a different look from the one the game asked for.
    if (out.src_color == 1 && out.dst_color == 7 &&
        !((out.src_alpha == 1 && out.dst_alpha == 7) || (s.write_mask & 0x8u) == 0))
        return out;
    out.enable_blending = 1;
    out.color_op = 0;   // VK_BLEND_OP_ADD
    out.alpha_op = 0;
    out.write_mask = s.write_mask & 0xfu;   // D3D11_COLOR_WRITE_ENABLE and VkColorComponentFlags number the bits alike
    out.ok = true;
    return out;
}
}  // namespace particle_blend
