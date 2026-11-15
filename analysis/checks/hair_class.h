#pragma once
// W5 step 1 (PLAN_2026-11-14): which draws are the character's hair, decided from the game's own shader declaration,
// the one scalar that shader branches on, and the draw's own state. Nothing here claims an appearance: a classified draw
// keeps its albedo, normal, metal and roughness and gains the runtime's anisotropy scalar.
//
// Why the declaration plus a value, and not a shader name: ps_1838410752 (camp) and ps_550297348744 (pond, desert) are
// the names three captures gave the family, and a ps_hash is not a durable identity (one code appears under 45 keys in
// runtime/delegation/ps_fnv.txt). What the pond and desert captures (runtime/laptop-play-20261114, 625 pixel shaders)
// measure, re-read by the gate:
//  - 46 of the 625 blobs declare `g_AnisoParam1` and `g_AnisoParam2`, always together, always in one `PSParamBuffer1`
//    at byte offsets 96 and 112. Disassembling the drawn hair shader shows only two of those registers read:
//    `lt r0.x, l(0), cb1[6].x` (an alternate sign path) and `lt r0.y, l(0), cb1[7].x` with
//    `div r18.xy, cb1[7].yzyy, r13.w` (the anisotropic lobe); 96/16 = 6, 112/16 = 7, and the same struct's
//    `g_AlbedoColor` at 48 is read as `cb1[3]` at that site, which is what ties the member offsets to the register.
//    So `g_AnisoParam2.x` is the flag the shader itself branches on -- a declaration alone proves nothing;
//  - of the two aniso families the frames draw, only one declares `g_SecondarySpecParam` (the two-lobe set the recon
//    names as hair) and only that one takes the lobe: its draws carry 1, 1, 0 at offset 112, the other family 0 on
//    every draw. Both are skinned with the same layout, neither is blended (blend_enable 0, depth_write 0);
//  - the alpha test separates them: the hair shader discards, the other does not. The albedo supports that split but is
//    not what the rule keys on (replay/execution-2026-11-14/w5_hair_census.py decodes the t0 DDS of every drawn aniso
//    family: 22.3% of the hair family's texels are fully transparent in the pond and desert captures, 59.7% in the camp
//    capture, against 0.0% for the other family).
// The refusals below are the negatives the plan names: the other aniso family (which the recon calls cloth/velvet; no
// measurement here identifies it as cloth), skin and foliage (no declaration, or no bones). What is NOT established
// here: that these draws are visually 2B's hair (a hide-draw check needs a live run, which is not authorized), which of
// scalp/lashes/cards each one is, whether the runtime does anything with the scalar -- W5 steps 2 and 4 measure those,
// and the look is the user's pick from a labelled sheet -- and that the other family is clothing rather than fur,
// velvet or some other two-lobe surface.
// Plain C++17, no D3D11 or Remix dependency: the game thread classifies, the worker builds the material from that answer.
// Gate: checks/test_live_hair.py (its part 1 re-reads the captured shaders and per-draw values this table comes from).
#include <cstdint>
namespace hair_class {
// The runtime's single anisotropy scalar (-1, 1: 0 isotropic, positive stretches the tangent-roughness lobe:
// isotropicRoughnessToAnisotropicRoughness in dxvk-remix's brdf.slangh). 0.5 is a LOOK CHOICE, not a measurement: the
// game's own pair (per-axis terms at cb1[7].yz) has no unit mapping onto this scalar, and no capture establishes one.
// W5 step 4 replaces it with whatever the user picks from the labelled sheet; the gate pins the constant so a change is
// always visible in a diff.
inline constexpr float kAnisotropy = 0.5f;
struct Draw {
    bool aniso_declared = false;     // the pixel shader's RDEF declares g_AnisoParam1 and g_AnisoParam2
    bool aniso_lobe = false;         // the draw's own g_AnisoParam2.x > 0: the shader runs the anisotropic lobe
    bool alpha_test = false;         // the shader discards: a card, not a solid surface
    bool skinned = false;            // bones move it: hair, cloth, a character
    bool blend_enabled = false;
    bool sky = false, effect = false, depth_only = false;
    std::uint32_t albedo = 0;        // 0 = no captured albedo texture for this draw
};
enum Reason : unsigned {
    kHair = 0,
    kBlended,
    kNotAlphaTested,
    kNotSkinned,
    kSky,
    kEffect,
    kDepthOnly,
    kNoAlbedo,
    kNoAnisoDecl,
    kNoAnisoLobe,   // the draw's shader declares the pair but this draw does not take the lobe
    kReasonCount,
};
// The first rule a draw fails, in the order the classes are counted. A declaration never overrides a refusal, and the
// lobe value is checked last so a caller only pays the constant-buffer read for a draw that passes everything else.
inline unsigned why(const Draw& d) {
    if (d.blend_enabled) return kBlended;
    if (!d.alpha_test) return kNotAlphaTested;
    if (!d.skinned) return kNotSkinned;
    if (d.sky) return kSky;
    if (d.effect) return kEffect;
    if (d.depth_only) return kDepthOnly;
    if (!d.albedo) return kNoAlbedo;
    if (!d.aniso_declared) return kNoAnisoDecl;
    if (!d.aniso_lobe) return kNoAnisoLobe;
    return kHair;
}
inline bool hair(const Draw& d) { return why(d) == kHair; }
}  // namespace hair_class
