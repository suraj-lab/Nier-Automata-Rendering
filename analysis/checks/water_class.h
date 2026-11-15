#pragma once
// W3 step 2 (PLAN_2026-11-14): which draws are the pond's water, decided from the game's own shader declaration and the
// draw's own blend/alpha state. Nothing here guesses an appearance: a classified draw keeps today's material and gains
// the runtime's translucent extension; whether that looks like water is W3 step 3/4's measurement.
//
// Why the declaration, and not a shader name or a parameter value: ps_550347550280 / ps_550347548488 are the names one
// capture gave those two shaders, and a pointer-based name is not a durable identity. What the pond and desert captures
// (runtime/laptop-play-20261114, 625 shaders) measure is:
//  - of the 31 shaders the two frames draw, exactly those two declare `g_TranslucentParam` in their DXBC RDEF. Six
//    hundred and twenty-five blobs are in the capture and 7 declare it: the two drawn ones plus five variants of the same
//    shaders that these frames never draw, each of which also declares g_RefractParam, g_WaterFogParam or g_WetParam1.
//    So the name marks the water *family*, and the state below narrows it to a surface; the camp capture is not read;
//  - every one of their 20 draws is alpha-blended with SRC_ALPHA / INV_SRC_ALPHA, op ADD (blend state 5, 6, 1);
//  - the seven other blended shaders of the same captures -- the post/effect passes that declare g_EffectPixelCommonBuffers,
//    550292875656, and the surface shaders 550339515912 / 550337747400 -- declare no `g_TranslucentParam`. Blending alone
//    is glass, wet rock and light shafts as much as water;
//  - `g_WaterFogParam` alone cannot be the test: only ps_550347548488 declares it, and the largest translucent surface of
//    the capture (16,848 indices, the recon's best water candidate, not a confirmed identification) belongs to the shader
//    that does not. The camp capture is not read by this gate: WATER-related declarations are recorded there too.
// So the shared declaration is necessary and the state narrows it. The refusals below are the classes the plan names as
// negatives: a hair or foliage card that discards, a skinned draw, an effect shader, the sky, a depth pass, and a draw
// with no captured albedo (nothing to make translucent).
// Plain C++17, no D3D11 or Remix dependency: the game thread classifies, the worker builds the material from that answer.
// Gate: checks/test_live_water.py (its part 1 re-reads the captured shaders this table comes from).
#include <cstdint>
namespace water_class {
struct Draw {
    bool blend_enabled = false;        // BlendEnable
    bool alpha_to_coverage = false;    // AlphaToCoverageEnable: coverage, not alpha blending (never sent to the capture,
                                       // so a draw that reports it is refused rather than assumed water)
    unsigned src = 0, dst = 0, op = 0; // SrcBlend, DestBlend, BlendOp as D3D11 reports them
    bool translucent_declared = false; // the pixel shader's RDEF declares g_TranslucentParam
    bool alpha_test = false;           // the shader discards: a card, not a sheet
    bool skinned = false;              // bones move it: hair, cloth, a character
    bool sky = false, effect = false, depth_only = false;
    std::uint32_t albedo = 0;          // 0 = no captured albedo texture for this draw
};
enum Reason : unsigned {
    kWater = 0,
    kNotBlended,
    kBlendNotAlpha,
    kNoTranslucentDecl,
    kAlphaTested,
    kSkinned,
    kSky,
    kEffect,
    kDepthOnly,
    kNoAlbedo,
    kReasonCount,
};
// The first rule a draw fails, in the order the classes are counted. A declaration never overrides a refusal: that is
// the "classify all blends as water" mutation, and every rule below is checked before it is even looked at.
inline unsigned why(const Draw& d) {
    constexpr unsigned kD3D11BlendOpAdd = 1, kD3D11BlendSrcAlpha = 5, kD3D11BlendInvSrcAlpha = 6;
    if (!d.blend_enabled) return kNotBlended;
    if (d.alpha_to_coverage || d.op != kD3D11BlendOpAdd || d.src != kD3D11BlendSrcAlpha || d.dst != kD3D11BlendInvSrcAlpha)
        return kBlendNotAlpha;
    if (d.alpha_test) return kAlphaTested;
    if (d.skinned) return kSkinned;
    if (d.sky) return kSky;
    if (d.effect) return kEffect;
    if (d.depth_only) return kDepthOnly;
    if (!d.albedo) return kNoAlbedo;
    if (!d.translucent_declared) return kNoTranslucentDecl;
    return kWater;
}
inline bool water(const Draw& d) { return why(d) == kWater; }
}  // namespace water_class
