#!/usr/bin/env python3
"""Frozen W3 step 2 gate: classify the pond's water family and refuse the hair/foliage/glass look-alikes.

PLAN_2026-11-14, W3 step 2: "Gate classification against hair/foliage/glass negatives. Teach fake runtime to inspect
translucent extensions, blend/category flags and resource lifetimes. Off retains today's cutout path. Mutation:
classify all blends as water or retain forced cutout on selected water; both must fail."

What the classifier is allowed to key on is a measured fact, not a guess, and part 1 pins that against the laptop
captures kept in this repository (runtime/laptop-play-20261114, frames 67078468 pond and 67279062 desert, 625 pixel
shaders):
  - both shaders the recon names as water (ps_550347550280 with the 16,848-index surface, ps_550347548488 with
    g_RefractParam/g_WaterFogParam) declare `g_TranslucentParam` in their DXBC RDEF, and they are the only two shaders
    the two frames draw that do (7 of the capture's 625 blobs declare it: the two drawn ones and five undrawn variants,
    every one of which also declares g_RefractParam, g_WaterFogParam or g_WetParam1);
  - every draw of those two is alpha-blended with SRC_ALPHA/INV_SRC_ALPHA, op ADD (blend_enable 1, 5, 6, 1) -- the
    state the classifier accepts;
  - the seven other blended shaders in the same capture -- the post/effect passes that declare g_EffectPixelCommonBuffers,
    550292875656, and the surface shaders 550339515912 / 550337747400 -- declare no `g_TranslucentParam`: blending alone is
    not water. What 550292875656 is (sky or not) is undetermined in the recon and does not matter here: it is not water.
  - `g_WaterFogParam` cannot be required: only ps_550347548488 declares it, and the *largest* water surface belongs to
    the shader that does not.
Part 1 reads those blobs and asserts the table, so the declaration the code keys on is never re-derived from memory.

Part 2 is a native ASan+UBSan harness (checks/water_class.h, checks/live_scene.h): the classifier's whole rule table,
its precedence, and the material a classified water draw is built with -- its own material (a different hash from the
cutout material built from the same texture, so a runtime cache cannot reuse a stale opaque asset), a
remixapi_MaterialInfoTranslucentEXT in the ext chain next to today's opaque ext, and no draw-call alpha state.

Part 3 runs the worker against the fake runtime (checks/remix_live_fake_runtime.cpp) with the mock game's blended world
draw, and pins:
  - unset and `=0` submit byte-identical category flags and materials: with the switch off the water draw keeps today's
    ALPHA_BLEND_TO_CUTOUT path, and nothing is counted;
  - on: the water draw's instance carries ANIMATED_WATER and *not* the cutout bit, its mesh names a material logged with
    translucency (index 1.33, diffuse layer on, thin wall unset) and a hash no cutout material uses, while the same
    texture path is still the albedo;
  - on, a blended draw whose shader declares no water constant (glass): today's cutout path, nothing submitted;
  - on, an alpha-tested card (foliage): today's cutout path, nothing submitted;
  - on, additive blending (the wrong blend state, a light shaft): today's path, nothing submitted;
  - resource lifetime: the fake runtime resolves every instance's mesh to a live material hash -- no VIOLATION line and
    `matlive=1` on every DrawInstance, in every case above.
Hair has no fixture in the mock game (no skinned draw); the classifier's refusal of alpha-tested and skinned draws is
pinned natively in part 2 and recorded as the live gap in the receipt.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-water'
CAPTURE = A / 'runtime/laptop-play-20261114'
VENDOR = A / 'remix-probe/vendor'
sys.path.insert(0, str(C))

WATER_SHADERS = (550347550280, 550347548488)   # pond: the water sheet and the refracting edge
BLENDED_NOT_WATER = (550345096712, 550288868808, 550288864328, 550421507528, 550337747400, 550339515912,
                     550292875656)             # post/effect, wet surface, sky: blended, and none of them water
CUTOUT = 1 << 15      # REMIXAPI_INSTANCE_CATEGORY_BIT_ALPHA_BLEND_TO_CUTOUT
WATER = 1 << 17       # REMIXAPI_INSTANCE_CATEGORY_BIT_ANIMATED_WATER

HARNESS = r'''
#include <cstdio>
#include <map>
#include <string>
#include "live_scene.h"
#include "water_class.h"

static int failures = 0;
static void check(const char* what, bool ok) { if (!ok) { ++failures; std::printf("FAIL %s\n", what); } }
struct Made { unsigned long long hash; int drawcall, translucent; float index, diffuse, thinhas, thin; float colour[3];
              const wchar_t* albedo; };
static std::map<unsigned long long, Made> made;
static unsigned long long next_handle = 0x1000;
static remixapi_ErrorCode REMIXAPI_CALL create_material(const remixapi_MaterialInfo* i, remixapi_MaterialHandle* out) {
    Made m{};
    if (i) {
        m.hash = i->hash;
        m.albedo = i->albedoTexture;
        // The worker chains the opaque ext with the translucent one; walk the whole chain, as the runtime does.
        struct Head { remixapi_StructType sType; const void* pNext; };
        for (const Head* h = static_cast<const Head*>(i->pNext); h; h = static_cast<const Head*>(h->pNext)) {
            if (h->sType == REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT) {
                const auto* e = reinterpret_cast<const remixapi_MaterialInfoOpaqueEXT*>(h);
                m.drawcall = int(e->useDrawCallAlphaState);
            }
            if (h->sType == REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_TRANSLUCENT_EXT) {
                const auto* t = reinterpret_cast<const remixapi_MaterialInfoTranslucentEXT*>(h);
                m.translucent = 1;
                m.index = t->refractiveIndex;
                m.diffuse = t->useDiffuseLayer;
                m.thinhas = t->thinWallThickness_hasvalue;
                m.thin = t->thinWallThickness_value;
                m.colour[0] = t->transmittanceColor.x;
                m.colour[1] = t->transmittanceColor.y;
                m.colour[2] = t->transmittanceColor.z;
            }
        }
    }
    made[next_handle] = m;
    *out = reinterpret_cast<remixapi_MaterialHandle>(next_handle++);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL ok_handle(void*) { return REMIXAPI_ERROR_CODE_SUCCESS; }
static Made& at(remixapi_MaterialHandle h) { return made[reinterpret_cast<unsigned long long>(h)]; }

// One scene draw as the live path sees it, spelled out per case so a field a rule reads cannot hide behind a default:
// the state of every water draw in the two captures is blend on, SRC_ALPHA/INV_SRC_ALPHA, op ADD.
static water_class::Draw draw(bool declared = true) {
    water_class::Draw d;
    d.blend_enabled = true;
    d.src = 5; d.dst = 6; d.op = 1;          // D3D11_BLEND_SRC_ALPHA, INV_SRC_ALPHA, BLEND_OP_ADD
    d.alpha_to_coverage = false;
    d.translucent_declared = declared;
    d.albedo = 7;
    return d;
}
int main(int argc, char** argv) {
    const std::string dir = argc > 1 ? argv[1] : ".";
    const std::wstring wdir(dir.begin(), dir.end());
    {   // ---- the classifier: the measured water state, then every rule on its own ----------------------
        check("classify: the measured water state is water", water_class::water(draw()));
        check("classify: ... with a reason of its own", water_class::why(draw()) == water_class::kWater);
        { auto d = draw(); d.translucent_declared = false;
          check("classify: no g_TranslucentParam is not water (glass, wet rock, the post passes)",
                !water_class::water(d) && water_class::why(d) == water_class::kNoTranslucentDecl); }
        { auto d = draw(); d.blend_enabled = false;
          check("classify: an opaque draw is not water", !water_class::water(d) &&
                water_class::why(d) == water_class::kNotBlended); }
        { auto d = draw(); d.src = 2; d.dst = 2;
          check("classify: additive blending is not water (a light shaft, an effect quad)",
                !water_class::water(d) && water_class::why(d) == water_class::kBlendNotAlpha); }
        { auto d = draw(); d.src = 2; d.dst = 1;
          check("classify: ONE/ZERO (blending on, the runtime's opaque alias) is not water",
                !water_class::water(d) && water_class::why(d) == water_class::kBlendNotAlpha); }
        { auto d = draw(); d.op = 3;
          check("classify: a non-ADD blend op is not water",
                !water_class::water(d) && water_class::why(d) == water_class::kBlendNotAlpha); }
        { auto d = draw(); d.alpha_to_coverage = true;
          check("classify: alpha-to-coverage is not water",
                !water_class::water(d) && water_class::why(d) == water_class::kBlendNotAlpha); }
        { auto d = draw(); d.alpha_test = true;
          check("classify: an alpha-tested card is not water (foliage, hair cards)",
                !water_class::water(d) && water_class::why(d) == water_class::kAlphaTested); }
        { auto d = draw(); d.skinned = true;
          check("classify: a skinned draw is not water (hair, cloth)",
                !water_class::water(d) && water_class::why(d) == water_class::kSkinned); }
        { auto d = draw(); d.sky = true;
          check("classify: the sky dome is not water", !water_class::water(d) &&
                water_class::why(d) == water_class::kSky); }
        { auto d = draw(); d.effect = true;
          check("classify: an effects shader is not water", !water_class::water(d) &&
                water_class::why(d) == water_class::kEffect); }
        { auto d = draw(); d.depth_only = true;
          check("classify: a depth-only pass is not water", !water_class::water(d) &&
                water_class::why(d) == water_class::kDepthOnly); }
        { auto d = draw(); d.albedo = 0;
          check("classify: a draw with no captured albedo is not water (no material to make translucent)",
                !water_class::water(d) && water_class::why(d) == water_class::kNoAlbedo); }
        // Precedence: a refused draw stays refused for the reason the caller counts, whatever else it also is. The
        // declaration alone can never make a shared state water -- that is the mutation the plan names.
        { auto d = draw(); d.sky = true; d.effect = true; d.alpha_test = true; d.skinned = true; d.albedo = 0;
          check("classify: every refusal beats the declaration", !water_class::water(d)); }
    }
    {   // ---- the material a classified water draw is built with --------------------------------------
        terrain_bake::Image im; im.w = 2; im.h = 2;
        for (int i = 0; i < 4; ++i) { im.rgba.push_back(0.4f); im.rgba.push_back(0.5f); im.rgba.push_back(0.6f); im.rgba.push_back(1.f); }
        const std::wstring source = wdir + L"/live_1.dds";
        check("setup: the albedo file is on disk", live_scene::write_whole(source, terrain_bake::dds_bytes(im, false, false)));
        remixapi_Interface api{};
        api.CreateMaterial = create_material;
        api.DestroyMaterial = reinterpret_cast<decltype(api.DestroyMaterial)>(ok_handle);
        live_scene::State s;
        s.texture_paths = {source}; s.landed = {1};
        const auto cutout = live_scene::material_for(api, s, 1);
        const auto water = live_scene::material_for(api, s, 1, 7, 0, 0, 0, 0, live_capture::MaterialConstants{}, false, true);
        check("material: today's material is cutout and carries no translucency",
              cutout && at(cutout).translucent == 0);
        check("material: the water material carries a translucent extension", water && at(water).translucent == 1);
        check("material: water's refractive index is 1.33", water && at(water).index > 1.329f && at(water).index < 1.331f);
        check("material: water keeps the diffuse layer (today's albedo still shows)", water && at(water).diffuse == 1);
        check("material: thin-wall thickness is not invented (unset until the pond capture measures it)",
              water && at(water).thinhas == 0);
        check("material: transmittance is clear white, not a guessed tint",
              water && at(water).colour[0] == 1.f && at(water).colour[1] == 1.f && at(water).colour[2] == 1.f);
        check("material: no draw-call alpha state (the particle path owns that)", water && at(water).drawcall == 0);
        check("material: its own hash, so a cache cannot reuse the cutout material",
              cutout && water && at(cutout).hash != at(water).hash);
        check("material: a second ask for the water material is the same one",
              live_scene::material_for(api, s, 1, 7, 0, 0, 0, 0, live_capture::MaterialConstants{}, false, true) == water);
        check("material: and the cutout material is still the cutout material",
              live_scene::material_for(api, s, 1) == cutout);
        // The water material still names the draw's albedo: the translucent extension is added to today's surface, it
        // does not replace it.
        check("material: the albedo path is still the draw's texture", water && at(water).albedo && at(cutout).albedo &&
              std::wstring(at(water).albedo) == std::wstring(at(cutout).albedo));
    }
    {   // ---- grey_first: the refreshed material stays a water material ----------------------------------
        // The albedo lands after the material exists, so the first one is grey and refresh_incomplete_materials destroys
        // and re-creates it under its own hash. A refresh that dropped the translucent extension would leave the water
        // surface opaque the moment its texture arrived -- and only on the first frame of a session.
        terrain_bake::Image im; im.w = 2; im.h = 2;
        for (int i = 0; i < 4; ++i) { im.rgba.push_back(0.3f); im.rgba.push_back(0.3f); im.rgba.push_back(0.3f); im.rgba.push_back(1.f); }
        const std::wstring source = wdir + L"/live_2.dds";
        remixapi_Interface api{};
        api.CreateMaterial = create_material;
        api.DestroyMaterial = reinterpret_cast<decltype(api.DestroyMaterial)>(ok_handle);
        live_scene::State s;
        // Its own texture id, so this material's hash cannot be the one the block above already created: the check below
        // has to see the refreshed material itself, not an earlier one that happens to share the hash.
        s.texture_paths = {wdir + L"/live_0.dds", source};
        s.landed = {1, 0};
        const auto grey = live_scene::material_for(api, s, 2, 7, 0, 0, 0, 0, live_capture::MaterialConstants{}, false, true);
        check("grey_first: the pending water material is still translucent", grey && at(grey).translucent == 1);
        const unsigned long long grey_hash = grey ? at(grey).hash : 0;
        check("setup: the albedo lands", live_scene::write_whole(source, terrain_bake::dds_bytes(im, false, false)));
        s.landed = {1, 1};
        live_scene::refresh_incomplete_materials(api, s);
        bool refreshed = false, refreshed_translucent = false;
        for (const auto& [handle, m] : made)
            if (m.hash == grey_hash && handle != reinterpret_cast<unsigned long long>(grey)) {
                refreshed = true;
                refreshed_translucent = m.translucent == 1;
            }
        check("grey_first: the landed material is re-created under the same hash", refreshed);
        check("grey_first: and is still a water material", refreshed_translucent);
    }
    std::printf("failures=%d\n", failures);
    return failures ? 1 : 0;
}
'''


def field(line, key):
    assert f'{key}=' in line, f'the log line does not report {key}=: {line}'
    return line.split(f'{key}=')[1].split()[0]


def measured_facts():
    """Part 1: the declaration table, read from the captured shaders themselves (never from a table in this file)."""
    import dump_shader_decls as D

    def declared(ps, name):
        path = CAPTURE / 'shaders' / f'ps_{ps}.dxbc'
        if not path.exists():
            return None
        cb, _res = D.declarations(D.chunks(path.read_bytes())['RDEF'][0])
        return any(v == name for (_n, _s, vs) in cb for (v, _o, _z) in vs)

    for ps in WATER_SHADERS:
        got = declared(ps, 'g_TranslucentParam')
        assert got is True, f'water shader ps_{ps} must declare g_TranslucentParam (read: {got})'
    for ps in BLENDED_NOT_WATER:
        assert declared(ps, 'g_TranslucentParam') is False, (
            f'ps_{ps} is blended but not water: it must not declare g_TranslucentParam')
    # Every shader of both captures, not only the nine named above: the declaration has to single the family out, or the
    # classifier's key is a coincidence of two hand-picked shaders. Two facts are asserted:
    #  - among the 31 shaders the two frames actually draw, exactly the two water shaders declare it;
    #  - every blob in the capture that declares it also declares another member of the same family (g_RefractParam,
    #    g_WaterFogParam or g_WetParam1). The capture holds 625 blobs and 7 declarers: the two drawn ones and five further
    #    variants of the same shaders, which these two frames never draw. The camp capture (README.md:90 records water
    #    keywords there) is not part of this evidence, so nothing below claims it.
    used = set()
    for frame in ('frame_67078468', 'frame_67279062'):
        for p in (CAPTURE / frame).glob('draw_*/capture.json'):
            used.add(int(json.loads(p.read_text())['ps_hash']))
    assert used, 'the frame records must be readable'
    family = {'g_RefractParam', 'g_WaterFogParam', 'g_WetParam1'}
    blind, declarers = [], {}
    for path in sorted((CAPTURE / 'shaders').glob('ps_*.dxbc')):
        try:
            cb, _res = D.declarations(D.chunks(path.read_bytes())['RDEF'][0])
        except Exception as e:   # noqa: BLE001 - an unparseable blob would make the scan a silent pass
            blind.append(f'{path.stem}: {e}')
            continue
        names = {v for (_n, _s, vs) in cb for (v, _o, _z) in vs}
        if 'g_TranslucentParam' in names:
            pid = int(path.stem.split('_')[1])
            declarers[pid] = names
            assert names & family, f'{path.stem} declares g_TranslucentParam and nothing else of the water family'
    assert not blind, f'the declaration scan may not skip a shader: {blind[:4]}'
    assert {p for p in declarers if p in used} == set(WATER_SHADERS), (
        f'the drawn declarers must be exactly the two water shaders, got {sorted(set(declarers) & used)}')
    assert len(declarers) >= len(WATER_SHADERS), declarers.keys()
    # The state every draw of the two water shaders is in, from the draw records themselves.
    draws = 0
    for frame in ('frame_67078468', 'frame_67279062'):
        for p in (CAPTURE / frame).glob('draw_*/capture.json'):
            d = json.loads(p.read_text())
            if int(d['ps_hash']) not in WATER_SHADERS:
                continue
            draws += 1
            st = d['state']
            assert (st['blend_enable'], st['src_blend'], st['dest_blend'], st['blend_op']) == (1, 5, 6, 1), (p, st)
    assert draws >= 10, f'the water family must have its measured draws in the captures, found {draws}'
    return f'{len(WATER_SHADERS)} drawn water shaders declare g_TranslucentParam ({len(declarers)} of the capture\'s ' \
           f'blobs do), {draws} draws in state (1,5,6,1), {len(BLENDED_NOT_WATER)} blended look-alikes do not'


def native(work):
    """Part 2: the classifier table and the water material, natively, sanitized."""
    (work / 'harness.cpp').write_text(HARNESS)
    cmd = ['g++', '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
           '-Wall', '-Wextra', '-Werror', '-DREMIX_WINAPI_NO_INCLUDE', '-DREMIX_WINAPI_NO_LIBRARY_LOADER',
           '-D_WIN64=1', '-D__stdcall=', '-D__declspec(x)=', '-isystem', str(VENDOR), '-I', str(C),
           str(work / 'harness.cpp'), '-o', str(work / 'harness')]
    built = subprocess.run(cmd, capture_output=True, text=True)
    assert built.returncode == 0, 'the native harness must compile:\n' + built.stderr[-2500:]
    run = subprocess.run([str(work / 'harness'), str(work)], capture_output=True, text=True)
    assert run.returncode == 0, 'the classifier or the water material is wrong:\n' + (run.stdout + run.stderr)[-2500:]


def main():
    facts = measured_facts()
    work = Path(tempfile.mkdtemp(prefix='live-water-'))
    native(work)
    import test_remix_live as tr
    import test_menu_overlay as tmo
    import test_nscn_scene as ts
    tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE_WATER', 'MOCK_WATER_PS', 'FAKE_REMIX_INSTANCE_LOG',
                                        'NIER_REMIX_LIVE_STATS_EVERY', 'NIER_REMIX_LIVE_GREY_FIRST')
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
               # grey_first off: a material appears once with its texture, so two runs submit comparable lists.
               'NIER_REMIX_LIVE_GREY_FIRST': '0', 'NIER_REMIX_LIVE_STATS_EVERY': '10'}
        if switch is not None:
            env['NIER_REMIX_LIVE_WATER'] = switch
        env.update(extra or {})
        _, _, log, fake = tr.run(work, name, env)
        assert fake and 'VIOLATION' not in fake, fake[-1500:]
        return log, fake

    def instances(fake):
        return [l for l in fake.splitlines() if l.startswith('DrawInstance ')]

    def shape(lines):
        """What the switch may change and nothing else: the categories of the instances submitted, as a multiset. Not the
        transforms (the mock's camera drifts with wall clock), not the frame a draw landed in, and not the instance count:
        the hold path repeats whatever the game skipped in a frame, so a run's counts move with scheduling, not with this
        switch."""
        return sorted(int(field(l, 'flags')) for l in lines)

    def materials(fake):
        return [l for l in fake.splitlines() if l.startswith('CreateMaterial ')]

    def translucent(lines):
        return [l for l in lines if field(l, 'trans') == '1']

    def counted(log):
        return [l for l in log.splitlines() if 'remix: live water' in l]

    def live_materials(fake):
        """Every instance resolved its mesh to a live material hash: the fake logs matlive= 1 for that, 0 for a hash that
        was destroyed and not re-created, and -1 for a mesh with no material at all. -1 is reported, never skipped: a bare
        mesh passes "the material is live" vacuously, and this fixture's world draw always has an albedo."""
        return [int(field(l, 'matlive')) for l in instances(fake)]

    blender = {'MOCK_WATER_PS': '1'}
    # 1. Default: the water draw takes today's blended path, and nothing about the classification runs.
    default_log, default_fake = run('default', 'live-blend', None, blender)
    assert not counted(default_log), f'the switch is off by default: nothing may be counted (\n{chr(10).join(counted(default_log))})'
    flags = [int(field(l, 'flags')) for l in instances(default_fake)]
    assert flags and all(f & CUTOUT for f in flags), f'a blended draw is cutout today: {flags[:4]}'
    assert not any(f & WATER for f in flags), f'no instance may be ANIMATED_WATER with the switch off: {flags[:4]}'
    assert not translucent(materials(default_fake)), 'no material may carry translucency with the switch off:\n' + \
        '\n'.join(materials(default_fake)[-4:])
    today_hashes = {int(field(l, 'mathash')) for l in default_fake.splitlines() if l.startswith('CreateMesh ')}
    results = {'default': f'switch off: {len(flags)} blended instances, all cutout, no translucency'}
    # 2. An explicit 0 is the same program as unset.
    zero_log, zero_fake = run('zero', 'live-blend', '0', blender)
    assert not counted(zero_log), 'explicit 0 must not be read as "on"'
    assert shape(instances(zero_fake)) == shape(instances(default_fake)), 'NIER_REMIX_LIVE_WATER=0 must submit today'
    assert {int(field(l, 'mathash')) for l in zero_fake.splitlines() if l.startswith('CreateMesh ')} == today_hashes, \
        'NIER_REMIX_LIVE_WATER=0 must build today\'s materials'
    results['zero-parity'] = 'unset and =0 submit the same categories and the same materials'
    # 3. On, the water shader: ANIMATED_WATER instead of cutout, a translucent material of its own.
    on_log, on_fake = run('on', 'live-blend', '1', blender)
    on_flags = [int(field(l, 'flags')) for l in instances(on_fake)]
    assert on_flags and all(f & WATER for f in on_flags), f'the water draw must be ANIMATED_WATER: {on_flags[:4]}'
    assert not any(f & CUTOUT for f in on_flags), (
        f'water must leave the forced-cutout path (the cutout flag also switches the runtime\'s blending off): '
        f'{on_flags[:4]}')
    water_materials = translucent(materials(on_fake))
    assert len(water_materials) == 1, 'exactly one translucent material (the water surface):\n' + \
        '\n'.join(materials(on_fake))
    line = water_materials[0]
    assert abs(float(field(line, 'index')) - 1.33) < 0.001, line
    assert field(line, 'diffuse') == '1', line
    assert field(line, 'thinwall') == '0,0.000', f'thin-wall thickness must stay unset: {line}'
    assert field(line, 'transcol') == '1.000,1.000,1.000', line
    # remix_c.h has no has-value flag for the distance, so 0 is what "not established yet" looks like on the wire: pinned
    # here so W3 step 3 cannot change it without this gate noticing.
    assert field(line, 'dist') == '0.000', line
    assert field(line, 'path') != '-', f'the water material still names the draw\'s albedo: {line}'
    # ... and it is the same texture today's cutout material names, not some other file.
    today_paths = {field(l, 'path') for l in materials(default_fake)}
    assert field(line, 'path') in today_paths, (
        f'the water material must name the albedo the cutout material names: {field(line, "path")} vs {sorted(today_paths)}')
    water_hashes = {int(field(l, 'mathash')) for l in on_fake.splitlines() if l.startswith('CreateMesh ')}
    assert water_hashes and not (water_hashes & today_hashes), (
        f'the water material must be its own hash, not the cutout one: water={sorted(water_hashes)} '
        f'cutout={sorted(today_hashes)}')
    counts = counted(on_log)
    assert counts, 'the switch is on: the classified draws must be counted'
    assert int(field(counts[-1], 'submitted')) >= 1, counts[-1]
    assert int(field(counts[-1], 'refused')) == 0, counts[-1]
    results['on-water'] = ('water draw: ANIMATED_WATER, no cutout bit, one translucent material (1.33, diffuse layer, '
                           'no thin wall) under a hash of its own')
    # 4. On, glass: blended, no water declaration -- today's cutout path, nothing submitted.
    glass_log, glass_fake = run('on-glass', 'live-blend', '1')
    glass_flags = [int(field(l, 'flags')) for l in instances(glass_fake)]
    assert glass_flags and all((f & CUTOUT) and not (f & WATER) for f in glass_flags), glass_flags[:4]
    assert not translucent(materials(glass_fake)), 'a blended draw without the declaration may not become water'
    counts = counted(glass_log)
    assert counts and int(field(counts[-1], 'submitted')) == 0, counts[-1] if counts else 'no stats line'
    results['on-glass'] = 'blended, no declaration: cutout as today, nothing submitted'
    # 5. On, foliage: the alpha-tested card keeps today's path even with the water shader's declaration on it.
    foliage_log, foliage_fake = run('on-foliage', 'live-blend', '1', blender | {'MOCK_CUTOUT_PS': '1'})
    foliage_flags = [int(field(l, 'flags')) for l in instances(foliage_fake)]
    assert foliage_flags and all((f & CUTOUT) and not (f & WATER) for f in foliage_flags), foliage_flags[:4]
    assert not translucent(materials(foliage_fake)), 'an alpha-tested card may not become water'
    results['on-foliage'] = 'alpha-tested card: never water, whatever its shader declares'
    # 6. On, additive blending (a light shaft): the wrong blend state is not water either.
    add_log, add_fake = run('on-additive', 'live-additive', '1', blender)
    add_flags = [int(field(l, 'flags')) for l in instances(add_fake)]
    # Today an additive draw is not "blended" in the capture's narrow sense (it tests for SRC_ALPHA/INV_SRC_ALPHA), so it
    # goes out opaque: neither category bit. Both absent is the today-path assertion for this case.
    assert add_flags and all(not (f & (CUTOUT | WATER)) for f in add_flags), add_flags[:4]
    assert not translucent(materials(add_fake)), 'additive blending may not become water'
    results['on-additive'] = 'additive: never water'
    # 7. Resource lifetimes: every instance's mesh resolves to a material hash that is live, in every case above.
    for name, fake in (('default', default_fake), ('zero', zero_fake), ('on', on_fake), ('on-glass', glass_fake),
                       ('on-foliage', foliage_fake), ('on-additive', add_fake)):
        live = live_materials(fake)
        assert live and all(v == 1 for v in live), f'{name}: an instance named a material hash that is not live: {live}'
        assert 'VIOLATION' not in fake, f'{name}: {fake[-800:]}'
    results['lifetimes'] = 'every drawn mesh resolves to a live material hash in all six runs'
    # 8. The measured declaration table, reported so the receipt carries it.
    print('W3 water class gate: OK')
    print('  measured:', facts)
    for k, v in results.items():
        print(f'  {k}: {v}')


def outside():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    env = os.environ.copy()
    for k in list(env):
        # The suite exports its own lane's environment; this gate wants the same isolated prefix every other live gate
        # uses, warm, or a 14-way parallel suite run pays a fresh wineboot inside the mock's 180 s timeout.
        if k.startswith(('NIER_', 'MOCK_', 'FAKE_')) and k != 'NIER_XVFB_DISPLAY':
            env.pop(k, None)
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               GALLIUM_DRIVER='llvmpipe', WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable,
                    str(Path(__file__).resolve()), '--inside'], env=env, cwd=OUT, check=True)


if __name__ == '__main__':
    if '--inside' in sys.argv:
        main()
    else:
        outside()
