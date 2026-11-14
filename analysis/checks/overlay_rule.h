// Item L7 (PLAN_2026-11-13): draws that are not surfaces, from the blend state the game set (classified on 30632051 and
// 41686139, 2026-11-14: every alpha-blended draw with depth write on is a lit surface - decals, ground overlays - while
// the depth-write-off ones are unlit darkening sheets, soft particles and tint layers, and DEST_COLOR x ZERO is a
// multiplicative decal). Pure function so it is gated natively (test_overlay_rule.py).
#pragma once

namespace overlay_rule {

// D3D11_BLEND values: ZERO 1, ONE 2, SRC_COLOR 3, DEST_COLOR 9 (d3d11.h).
inline bool is_overlay(bool blend_enable, unsigned src, unsigned dest, bool depth_write, bool has_material_roles) {
    if (!blend_enable) return false;
    const bool additive = dest == 2;                                                   // ... + dst * ONE
    const bool multiplicative = (src == 9 && dest == 1) || (src == 1 && dest == 3);  // dst * src
    if (additive || multiplicative) return true;
    return !depth_write && !has_material_roles;   // alpha blend, no depth, no traced albedo/metal/gloss: not a surface
}

}  // namespace overlay_rule
