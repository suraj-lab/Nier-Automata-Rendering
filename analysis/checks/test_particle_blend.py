#!/usr/bin/env python3
"""Frozen E1.6 gate: an additive or straight-alpha effect quad submitted as a Remix PARTICLE instance that carries the
game's own blend state.

Remix can take per-instance alpha state (remixapi_InstanceInfoBlendEXT). Two facts, both read from the runtime source in
this repository, shape what this path may submit:
  - the EXT's factor/op fields are cast straight to VkBlendFactor / VkBlendOp
    (runtime/remix-source/0ba9973fd856e29fe9cf8dd2f2bc754bcbb2037a/rtx_remix_api.cpp:861-867), and D3D11 numbers the
    same states differently (D3D11 ONE is 2, VK_BLEND_FACTOR_ONE is 1; D3D11 DEST_COLOR is 9, VK's is 4);
  - the runtime enables blending only for the (op, src, dst) combinations it recognises and draws everything else as an
    opaque alias (runtime/src/dxvk-remix/src/dxvk/rtx_render/rtx_instance_manager.cpp:771-860). A state it does not know
    must therefore be refused before submission, not sent and quietly turned solid.
The material must also be built with `useDrawCallAlphaState`, or the runtime never reads the instance's blend state
(rtx_instance_manager.cpp:710), and the EXT's alpha-test op is read as well -- 0 is kNever, i.e. every sample discarded.
Part 1 pins the map natively, sanitized, on the whole table; part 2 pins what the live path submits, from the fake
runtime's own log of DrawInstance and CreateMaterial.
What is asserted, and why each case exists:
  - (native) every D3D11 factor and every op the map accepts or refuses, the 16 colour pairs the runtime blends and the
    near misses it does not, the write mask, and both alpha factors;
  - (native) a particle material is its own material with useDrawCallAlphaState, and stays one when grey_first re-creates
    it after its texture lands -- a grey material that lost the flag would never blend;
  - unset and `=0` submit byte-identical categories: with the switch off the effect draw is left out exactly as today;
  - on, additive (D3D11 ONE/ONE): one PARTICLE instance per presented frame, its blend read back as VK ONE/ONE with op ADD
    -- the numbers the runtime casts to kEmissive, not the D3D11 ones (2/2) it would have been handed by a pass-through;
  - that instance carries no ALPHA_BLEND_TO_CUTOUT (the runtime forces the alpha test and drops the blend for those) and an
    alpha test of kAlways, not the zero-filled kNever;
  - the same frame's world draw of the same buffers is *not* a particle and gets no blend state, and the particle mesh
    is its own mesh: one contribution, one instance, no shared material;
  - the particle's mesh carries a material built with useDrawCallAlphaState, and the world's does not;
  - on, straight alpha (D3D11 SRC_ALPHA/INV_SRC_ALPHA): SRC_ALPHA/ONE_MINUS_SRC_ALPHA, so the map is a table and not a
    constant;
  - on, alpha-to-coverage, on, ONE/ZERO (the runtime's "opaque alias") and on, an effect draw with no material: refused
    and left out as today, and counted -- never submitted as a quad the runtime would draw solid.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-particle-blend'
VENDOR = A / 'remix-probe/vendor'
sys.path.insert(0, str(C))
HARNESS = r'''
#include <cstdio>
#include <map>
#include <string>
#include "live_scene.h"
#include "particle_blend.h"
#include "terrain_bake.h"
static int failures = 0;
static void check(const char* what, bool ok) { if (!ok) { ++failures; std::printf("FAIL %s\n", what); } }
struct Made { unsigned long long hash; int drawcall; };
static std::map<unsigned long long, Made> made;
static unsigned long long next_handle = 0x1000;
static remixapi_ErrorCode REMIXAPI_CALL create_material(const remixapi_MaterialInfo* i, remixapi_MaterialHandle* out) {
    Made m{};
    if (i) {
        m.hash = i->hash;
        const auto* e = static_cast<const remixapi_MaterialInfoOpaqueEXT*>(i->pNext);
        m.drawcall = e && e->sType == REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT ? int(e->useDrawCallAlphaState) : -1;
    }
    made[next_handle] = m;
    *out = reinterpret_cast<remixapi_MaterialHandle>(next_handle++);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL ok_handle(void*) { return REMIXAPI_ERROR_CODE_SUCCESS; }
static Made& at(remixapi_MaterialHandle h) { return made[reinterpret_cast<unsigned long long>(h)]; }
// A D3D11_RENDER_TARGET_BLEND_DESC, spelled out per case so a wrong field is not hidden by a default.
static particle_blend::State state(unsigned src, unsigned dst, unsigned asrc = 2, unsigned adst = 1, unsigned op = 1,
                                   unsigned aop = 1, unsigned mask = 15, bool enable = true, bool atoc = false) {
    particle_blend::State s;
    s.enable = enable; s.alpha_to_coverage = atoc;
    s.src = src; s.dst = dst; s.op = op;
    s.src_alpha = asrc; s.dst_alpha = adst; s.op_alpha = aop;
    s.write_mask = mask;
    return s;
}
static bool is(const particle_blend::Mapped& m, unsigned src, unsigned dst, unsigned asrc, unsigned adst, unsigned mask) {
    return m.ok && m.enable_blending == 1 && m.src_color == src && m.dst_color == dst && m.color_op == 0 &&
           m.src_alpha == asrc && m.dst_alpha == adst && m.alpha_op == 0 && m.write_mask == mask;
}
static bool refused(const particle_blend::State& s) { return !particle_blend::map(s).ok; }
int main(int argc, char** argv) {
    const std::string dir = argc > 1 ? argv[1] : ".";
    const std::wstring wdir(dir.begin(), dir.end());
    remixapi_Interface api{};
    api.CreateMaterial = create_material;
    api.DestroyMaterial = reinterpret_cast<decltype(api.DestroyMaterial)>(ok_handle);
    {   // ---- D3D11_BLEND -> VkBlendFactor, value by value (the two numberings are not an offset) -------------
        const struct { unsigned d3d, vk; } factors[] = {
            {1, 0}, {2, 1}, {3, 2}, {4, 3}, {9, 4}, {10, 5}, {5, 6}, {6, 7}, {7, 8}, {8, 9}, {11, 14},
            {16, 15}, {17, 16}, {18, 17}, {19, 18},
        };
        for (const auto& f : factors) {
            char what[96];
            std::snprintf(what, sizeof what, "factor: D3D11 %u is VK %u", f.d3d, f.vk);
            check(what, particle_blend::factor(f.d3d) == f.vk);
        }
        // 14/15 are BLEND_FACTOR/InvBlendFactor: they need the blend constant, which this path does not send.
        for (const unsigned d3d : {0u, 12u, 13u, 14u, 15u, 20u, 21u})
            check("factor: an invalid or constant-requiring value is refused",
                  particle_blend::factor(d3d) == particle_blend::kUnmappable);
    }
    {   // ---- the pairs the runtime blends (rtx_instance_manager.cpp:771-860) and the ones it draws opaque ------
        const unsigned pairs[][2] = {{6, 7}, {7, 6}, {6, 1}, {7, 1}, {1, 6}, {1, 7}, {2, 3}, {3, 2},
                                     {2, 1}, {3, 1}, {1, 2}, {1, 3}, {1, 1}, {4, 0}, {0, 2}, {4, 2}};
        for (const auto& p : pairs) check("pair: a pair the runtime blends is accepted", particle_blend::blendable(p[0], p[1]));
        // ONE/ZERO is the runtime's opaque alias (blendEnabled = false), and the rest are combinations it does not map.
        const unsigned rejected[][2] = {{1, 0}, {0, 0}, {0, 1}, {5, 1}, {1, 5}, {9, 9}, {14, 1}, {1, 14}};
        for (const auto& p : rejected)
            check("pair: a pair the runtime does not blend is refused", !particle_blend::blendable(p[0], p[1]));
    }
    {   // ---- one draw's state -> the EXT struct ---------------------------------------------------------
        check("map: straight alpha is VK SRC_ALPHA/ONE_MINUS_SRC_ALPHA", is(particle_blend::map(state(5, 6)), 6, 7, 1, 0, 15));
        check("map: additive is VK ONE/ONE (the runtime's kEmissive)", is(particle_blend::map(state(2, 2)), 1, 1, 1, 0, 15));
        check("map: premultiplied alpha is VK ONE/ONE_MINUS_SRC_ALPHA",
              is(particle_blend::map(state(2, 6, 2, 6)), 1, 7, 1, 7, 15));
        // ONE/ONE_MINUS_SRC_ALPHA is premultiplied only with an alpha state that says so, or with alpha writes off;
        // otherwise the runtime classifies the same pair as inverted reverse-emissive.
        check("map: the premultiplied pair needs the premultiplied alpha state", refused(state(2, 6)) &&
              refused(state(2, 6, 5, 6)));
        check("map: ... or no alpha writes", is(particle_blend::map(state(2, 6, 2, 1, 1, 1, 7)), 1, 7, 1, 0, 7));
        check("map: multiplicative is VK DST_COLOR/ZERO", is(particle_blend::map(state(9, 1)), 4, 0, 1, 0, 15));
        // The alpha factors are mapped on their own, through the same table.
        check("map: alpha factors use the same table", is(particle_blend::map(state(5, 6, 5, 6)), 6, 7, 6, 7, 15));
        const auto unmapped = particle_blend::map(state(14, 1));
        check("map: BLEND_FACTOR is refused (no blend constant is sent)", !unmapped.ok && unmapped.enable_blending == 0);
        check("map: alpha BLEND_FACTOR is refused too", refused(state(5, 6, 14, 1)));
        check("map: blending off is refused", refused(state(5, 6, 2, 1, 1, 1, 15, false)));
        check("map: alpha-to-coverage is refused", refused(state(2, 2, 2, 1, 1, 1, 15, true, true)));
        check("map: a non-ADD colour op is refused", refused(state(2, 2, 2, 1, 2)) &&
                                                    refused(state(2, 2, 2, 1, 3)) && refused(state(2, 2, 2, 1, 5)));
        check("map: a non-ADD alpha op is refused", refused(state(2, 2, 2, 1, 1, 3)));
        check("map: a zero write mask is refused (nothing would be visible)", refused(state(2, 2, 2, 1, 1, 1, 0)));
        check("map: an unknown factor is refused", refused(state(99, 1)) && refused(state(5, 99)));
        // D3D11_COLOR_WRITE_ENABLE and VkColorComponentFlags number the bits alike, so the mask passes through.
        check("map: the write mask passes through", particle_blend::map(state(2, 2, 2, 1, 1, 1, 7)).write_mask == 7 &&
                                                   particle_blend::map(state(2, 2, 2, 1, 1, 1, 8)).write_mask == 8);
    }
    {   // ---- the material a particle mesh is built with ------------------------------------------------
        terrain_bake::Image im; im.w = 2; im.h = 2;
        for (int i = 0; i < 4; ++i) { im.rgba.push_back(0.4f); im.rgba.push_back(0.5f); im.rgba.push_back(0.6f); im.rgba.push_back(1.f); }
        const std::wstring source = wdir + L"/live_1.dds";
        check("setup: the albedo file is on disk", live_scene::write_whole(source, terrain_bake::dds_bytes(im, false, false)));
        live_scene::State s;
        s.texture_paths = {source}; s.landed = {1};
        const auto world = live_scene::material_for(api, s, 1);
        const auto particle = live_scene::material_for(api, s, 1, 7, 0, 0, 0, 0, {}, true);
        check("material: the world material does not ask for the draw-call alpha state", world && at(world).drawcall == 0);
        check("material: the particle material does", particle && at(particle).drawcall == 1);
        check("material: and is its own material, not the world's", world && particle && world != particle &&
                                                                  at(world).hash != at(particle).hash);
        check("material: a second ask for the particle material is the same one",
              live_scene::material_for(api, s, 1, 7, 0, 0, 0, 0, {}, true) == particle &&
              live_scene::material_for(api, s, 1) == world);
    }
    {   // ---- grey_first: the refreshed material stays a particle material ------------------------------
        // The albedo is written only after the material exists, so the first one is grey and the refresh re-creates it.
        // Losing the flag there would leave a particle whose blend state nothing reads.
        terrain_bake::Image im; im.w = 2; im.h = 2;
        for (int i = 0; i < 4; ++i) { im.rgba.push_back(0.3f); im.rgba.push_back(0.3f); im.rgba.push_back(0.3f); im.rgba.push_back(1.f); }
        const std::wstring source = wdir + L"/live_2.dds";
        live_scene::State s;
        // Its own texture id, so this material's hash cannot be the one the first block already created: the check below
        // has to see the refreshed material itself, not an earlier one that happens to share the hash.
        s.texture_paths = {wdir + L"/live_0.dds", source};
        s.landed = {1, 0};
        const auto grey = live_scene::material_for(api, s, 2, 7, 0, 0, 0, 0, {}, true);
        check("grey_first: the pending particle material is sent grey and still asks for the draw-call state",
              grey && at(grey).drawcall == 1 && s.incomplete.size() == 1);
        const unsigned long long grey_hash = grey ? at(grey).hash : 0;
        check("setup: the albedo lands", live_scene::write_whole(source, terrain_bake::dds_bytes(im, false, false)));
        s.landed = {1, 1};
        live_scene::refresh_incomplete_materials(api, s);
        bool refreshed = false, refreshed_flag = false;
        for (const auto& [handle, m] : made)
            if (m.hash == grey_hash && handle != reinterpret_cast<unsigned long long>(grey)) {
                refreshed = true;
                refreshed_flag = m.drawcall == 1;
            }
        check("grey_first: the landed material is re-created under the same hash", refreshed);
        check("grey_first: and keeps useDrawCallAlphaState", refreshed_flag);
    }
    std::printf("failures=%d\n", failures);
    return failures ? 1 : 0;
}
'''
PARTICLE = 1 << 9
CUTOUT = 1 << 15   # REMIXAPI_INSTANCE_CATEGORY_BIT_ALPHA_BLEND_TO_CUTOUT
def field(line, key):
    parts = re.split(rf'(?<![\w]){key}=', line)
    assert len(parts) > 1, f'the log line does not report {key}=: {line}'
    return parts[1].split()[0]
def instances(fake):
    return [l for l in fake.splitlines() if l.startswith('DrawInstance ')]
def shape(lines):
    """What the switch can change, and nothing else: a transform is run-specific (the mock's camera moves with wall
    clock) and so is a frame's instance count (the hold path repeats whatever the game skipped)."""
    return [(int(field(l, 'presented')), int(field(l, 'flags')), int(field(l, 'blend'))) for l in lines]
def particles(lines):
    return [l for l in lines if int(field(l, 'flags')) & PARTICLE]
def blend_of(line):
    """(enabled, src, dst, op, asrc, adst, aop, mask) as the fake runtime read them out of the instance's EXT chain."""
    keys = ('src', 'dst', 'op', 'asrc', 'adst', 'aop', 'mask')
    return (int(field(line, 'blend')),) + tuple(int(field(line, k)) for k in keys)
def has_blend(line):
    """The instance carried no InstanceInfoBlendEXT: the fake logs -1 when its chain has none."""
    return int(field(line, 'blend')) == -1
def mesh_materials(fake):
    """mesh hash -> (material handle, material hash) CreateMesh gave that mesh."""
    out = {}
    for l in fake.splitlines():
        if l.startswith('CreateMesh '):
            out[int(field(l, 'hash'))] = (int(field(l, 'mat')), int(field(l, 'mathash')))
    return out
def draw_call_alpha(fake):
    """material hash -> useDrawCallAlphaState of the last material submitted under it."""
    out = {}
    for l in fake.splitlines():
        if l.startswith('CreateMaterial '):
            out[int(field(l, 'hash'))] = int(field(l, 'drawcall'))
    return out
def mesh_count(fake):
    """How many meshes the worker built. A dropped effect draw builds none, so a leaked one shows up here even when
    the categories it submits happen to match the switch-off run's."""
    return len([l for l in fake.splitlines() if l.startswith('CreateMesh ')])
def counted(log):
    return [l for l in log.splitlines() if 'remix: live particle_blend' in l]
def native(work):
    """Part 1: the map and the particle material, natively, sanitized, with no runtime involved."""
    (work / 'harness.cpp').write_text(HARNESS)
    cmd = ['g++', '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
           '-Wall', '-Wextra', '-Werror', '-DREMIX_WINAPI_NO_INCLUDE', '-DREMIX_WINAPI_NO_LIBRARY_LOADER',
           '-D_WIN64=1', '-D__stdcall=', '-D__declspec(x)=', '-isystem', str(VENDOR), '-I', str(C),
           str(work / 'harness.cpp'), '-o', str(work / 'harness')]
    built = subprocess.run(cmd, capture_output=True, text=True)
    assert built.returncode == 0, 'the native harness must compile:\n' + built.stderr[-2500:]
    run = subprocess.run([str(work / 'harness'), str(work)], capture_output=True, text=True)
    assert run.returncode == 0, 'the map or the particle material is wrong:\n' + (run.stdout + run.stderr)[-2500:]
def main():
    work = Path(tempfile.mkdtemp(prefix='live-particle-blend-'))
    native(work)
    import test_remix_live as tr
    import test_menu_overlay as tmo
    import test_nscn_scene as ts
    tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE_PARTICLE_BLEND', 'MOCK_EFFECT_REGISTER', 'MOCK_EFFECT_ONLY',
                                       'MOCK_EFFECT_BLEND', 'MOCK_EFFECT_NO_TEX', 'FAKE_REMIX_INSTANCE_LOG')
    tmo.build(work)
    subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                    '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(VENDOR),
                    str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
    def run(name, camera, switch, extra=None):
        tex = work / f'tex-{name}'
        tex.mkdir()
        env = {'MOCK_CAMERA': camera, 'MOCK_FRAME_MS': '60', 'NIER_REMIX': '1',
               'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'),
               'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'), 'NIER_REMIX_LIVE': '1',
               'NIER_REMIX_LIVE_TEX': tr.win(tex), 'FAKE_REMIX_INSTANCE_LOG': '1',
               'MOCK_EFFECT_REGISTER': '30' if camera == 'live-additive' else '27',
               # grey_first off, so a material appears once with its texture and two runs submit comparable lists; the
               # refresh path is pinned natively above.
               'NIER_REMIX_LIVE_GREY_FIRST': '0', 'NIER_REMIX_LIVE_STATS_EVERY': '10'}
        if switch is not None:
            env['NIER_REMIX_LIVE_PARTICLE_BLEND'] = switch
        env.update(extra or {})
        d, result, log, fake = tr.run(work, name, env)
        assert fake and 'VIOLATION' not in fake, fake[-1500:]
        return log, fake, d
    results = {'native': 'the whole factor/op/pair table, and a particle material that survives the grey_first refresh'}
    # 1. Default: the effect draw is left out as it is today, and the switch is never read.
    log, default_fake, _ = run('default', 'live-blend', None)
    default_lines = instances(default_fake)
    assert default_lines, 'the run submitted no instance at all'
    assert not particles(default_lines), 'the switch is off: no instance may carry the PARTICLE category'
    assert not counted(log), f'the switch is off by default: nothing may be counted (\n{chr(10).join(counted(log))})'
    assert all(has_blend(l) for l in default_lines), 'no instance may carry a blend state with the switch off'
    results['default'] = 'switch off: the effect draw stays out, no PARTICLE category, no blend state, nothing counted'
    # 2. An explicit 0 is the same program as unset: parity of every category the run submits.
    log, zero_fake, _ = run('zero', 'live-blend', '0')
    zero_lines = instances(zero_fake)
    assert not counted(log), 'explicit 0 must not be read as "on"'
    assert all(has_blend(l) for l in zero_lines), 'no instance may carry a blend state with 0'
    assert not particles(zero_lines), 'explicit 0 must not be read as "on"'
    assert {flags for _, flags, _ in shape(zero_lines)} == {flags for _, flags, _ in shape(default_lines)}, \
        'unset and 0 must submit the same categories'
    results['zero'] = 'explicit 0 submits the same categories as unset, and no blend state'
    # 3. On, additive: D3D11 ONE/ONE is VK ONE/ONE, which the runtime reads as an emissive blend.
    log, additive_fake, _ = run('on-additive', 'live-additive', '1')
    additive_lines = instances(additive_fake)
    stats = counted(log)
    assert stats, 'the switch is on: the draw and its fate must be counted'
    assert int(field(stats[-1], 'draws')) > 0 and int(field(stats[-1], 'refused')) == 0, stats[-1]
    submitted = int(field(stats[-1], 'submitted'))
    assert submitted > 0, f'the additive effect draw must be submitted ({stats[-1]})'
    part = particles(additive_lines)
    assert part, 'no instance carried the PARTICLE category:\n' + '\n'.join(additive_lines[-4:])
    assert len(part) >= submitted, (len(part), submitted)
    for line in part:
        assert blend_of(line) == (1, 1, 1, 0, 1, 0, 0, 15), (
            'additive must reach the runtime as VK ONE/ONE with op ADD (D3D11 ONE is 2, and 2 would be SRC_COLOR):\n' + line)
        assert not int(field(line, 'flags')) & CUTOUT, (
            'the cutout category forces the alpha test, which switches the blend off again:\n' + line)
        assert int(field(line, 'atestop')) == 7 and int(field(line, 'atestref')) == 0, (
            'the alpha test must be kAlways: 0 is kNever and would discard every sample:\n' + line)
    # One contribution per frame: every presented frame that drew the particle drew it exactly once.
    worlds = [l for l in additive_lines if not int(field(l, 'flags')) & PARTICLE]
    assert worlds, 'the world draw must still be submitted'
    assert [l for l in worlds if not has_blend(l)] == [], \
        'a draw that is not a particle may not carry a blend state:\n' + '\n'.join(worlds[-4:])
    per_frame = {}
    for l in part:
        per_frame[int(field(l, 'presented'))] = per_frame.get(int(field(l, 'presented')), 0) + 1
    assert max(per_frame.values()) == 1, f'a frame drew the particle more than once: {per_frame}'
    # The particle is its own mesh with its own material, and that material is the one the runtime reads the blend from.
    mats, alpha_state = mesh_materials(additive_fake), draw_call_alpha(additive_fake)
    particle_meshes = {int(field(l, 'mesh')) for l in part}
    world_meshes = {int(field(l, 'mesh')) for l in worlds}
    assert not (particle_meshes & world_meshes), (
        f'the particle must not share the world draw\'s mesh, or the blend state leaks onto the world: '
        f'{particle_meshes} vs {world_meshes}')
    for mesh in particle_meshes:
        assert mesh in mats, f'the particle mesh {mesh} was never created'
        material_hash = mats[mesh][1]
        assert material_hash and alpha_state.get(material_hash) == 1, (
            f'the particle mesh\'s material must be built with useDrawCallAlphaState, or the runtime ignores the blend '
            f'state (material hash {material_hash} -> {alpha_state.get(material_hash)})')
    for mesh in world_meshes:
        if mesh in mats and mats[mesh][1]:
            assert alpha_state.get(mats[mesh][1]) == 0, (
                f'a non-particle material may not claim the draw-call alpha state (material hash {mats[mesh][1]})')
    results['on-additive'] = ('one PARTICLE instance per frame, blend VK ONE/ONE/ADD (mask 15), no cutout flag, alpha '
                              'test kAlways, its own mesh, material with useDrawCallAlphaState')
    # 4. On, straight alpha: the same table maps a different pair, so nothing here is a constant.
    log, straight_fake, _ = run('on-straight', 'live-blend', '1')
    straight = particles(instances(straight_fake))
    assert straight, 'a straight-alpha effect draw must also be submitted'
    for line in straight:
        assert blend_of(line) == (1, 6, 7, 0, 1, 0, 0, 15), (
            'straight alpha must reach the runtime as VK SRC_ALPHA/ONE_MINUS_SRC_ALPHA:\n' + line)
        assert not int(field(line, 'flags')) & CUTOUT, (
            'a straight-alpha particle must not be labelled cutout, or its blend is dropped:\n' + line)
    results['on-straight'] = 'straight alpha reaches the runtime as VK SRC_ALPHA/ONE_MINUS_SRC_ALPHA, without the cutout flag'
    # 5/6. On, two states the runtime cannot express: left out as today and counted, never sent as an opaque quad.
    # 7. On, an effect draw with no albedo bound: the capture gives it no material, and a material is what carries
    #    useDrawCallAlphaState, so the runtime would never read the blend state. Refused, not sent as a solid quad.
    log, bare_fake, _ = run('on-notexture', 'live-additive', '1', {'MOCK_EFFECT_NO_TEX': '1'})
    bare_stats = counted(log)
    assert bare_stats, 'on-notexture: the draw must be counted'
    assert int(field(bare_stats[-1], 'refused')) > 0 and int(field(bare_stats[-1], 'submitted')) == 0, bare_stats[-1]
    assert not particles(instances(bare_fake)), \
        'a particle with no material cannot carry the blend state: it must not be submitted'
    # ... and it is dropped, not demoted to ordinary geometry: with the switch off the same camera submits the same
    # categories, and neither run leaves a mesh with no material behind.
    additive_off_log, additive_off_fake, _ = run('additive-off', 'live-additive', None)
    assert {flags for _, flags, _ in shape(instances(bare_fake))} == \
        {flags for _, flags, _ in shape(instances(additive_off_fake))}, \
        'an untextured effect draw must stay out, not become world geometry'
    assert mesh_count(bare_fake) == mesh_count(additive_off_fake), (
        f'a dropped effect draw must not build a mesh either ({mesh_count(bare_fake)} vs '
        f'{mesh_count(additive_off_fake)} meshes)')
    results['on-notexture'] = 'an effect draw with no material is refused, counted and dropped, never a solid particle'
    for name, mode in (('on-atoc', 'atoc'), ('on-opaque', 'opaque')):
        log, refused_fake, _ = run(name, 'live-additive', '1', {'MOCK_EFFECT_BLEND': mode})
        refused_stats = counted(log)
        assert refused_stats, f'{name}: the refusal must be counted'
        assert int(field(refused_stats[-1], 'refused')) > 0, refused_stats[-1]
        assert int(field(refused_stats[-1], 'submitted')) == 0, refused_stats[-1]
        assert not particles(instances(refused_fake)), (
            f'{name}: an unsupported blend may not be submitted as a particle -- the runtime would draw it opaque')
        results[name] = f'{mode} is refused and counted, and no PARTICLE instance is submitted'
    print('\n'.join(f'PASS {k}: {v}' for k, v in results.items()))
def outside():
    (OUT / 'xdg').mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    env = os.environ.copy()
    for k in list(env):
        # NIER_XVFB_DISPLAY is the suite's own lane display: the xvfb-run shim needs it.
        if k.startswith(('NIER_', 'MOCK_', 'FAKE_')) and k != 'NIER_XVFB_DISPLAY':
            env.pop(k, None)
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               GALLIUM_DRIVER='llvmpipe', WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable,
                    str(Path(__file__).resolve()), '--inside'], cwd=OUT, env=env, check=True)
if __name__ == '__main__':
    if '--inside' in sys.argv:
        main()
    else:
        outside()
