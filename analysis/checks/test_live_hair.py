#!/usr/bin/env python3
"""Frozen W5 step 1 gate: classify the character's hair from the draw's own bytecode evidence and give only it the
runtime's anisotropy, with the switch off by default.

PLAN_2026-11-14, W5 step 1: "Identify hair by bytecode/material evidence and a hide-draw check; separate scalp, lashes
and alpha cards." and the handoff's reading of it: "find `g_AnisoParam*`'s offsets in the hair shader by disassembly,
then classify hair draws the way W3 step 2 classifies water (its own header + frozen gate, alpha-tested/skinned
positives against a clothing/skin negative) and set `MaterialInfoOpaqueEXT.anisotropy` behind a default-off switch."

W5 step 2 (whether the runtime's anisotropy and tangent basis do anything) and step 4 (the look) are NOT claimed here:
the sheet is the user's pick and no live run exists. What is claimed is measured, and part 1 re-measures it from the
captures kept in this repository (runtime/laptop-play-20261114, frames 67078468 pond and 67279062 desert, 625 pixel
shaders), so nothing below is remembered:

  - 46 of the 625 blobs declare `g_AnisoParam1` and `g_AnisoParam2`, always together, always both in one
    `PSParamBuffer1` at byte offsets 96 and 112. The disassembly of the drawn hair shader (ps_550297348744) reads
    those two registers and nothing else of the pair: `lt r0.x, l(0), cb1[6].x` (the alternate sign path) and
    `lt r0.y, l(0), cb1[7].x` / `div r18.xy, cb1[7].yzyy, r13.w` (the anisotropic lobe). 96/16 = 6 and 112/16 = 7,
    and the same struct's `g_AlbedoColor` at 48 is read as `cb1[3]` at the same site, which is what ties the member
    offsets to the register the shader uses. So `g_AnisoParam2.x` is the flag the shader itself branches on.
  - The two frames draw exactly two aniso declarers each, and only one of them also declares
    `g_SecondarySpecParam` (the two-lobe family the recon names as hair). Both are skinned with the same input layout
    (POSITION/TANGENT/TEXCOORD/BLENDINDICES/BLENDWEIGHT/TEXCOORD/NORMAL) and neither is blended (blend_enable 0,
    depth_enable 1, depth_write 0).
  - The per-draw value at offset 112 (read from the draw's own ps_cb_1.bin): the hair family takes the lobe
    (x = 1) on 2 of its 3 draws in each frame, the third has it off (the 10,656-index mesh); the other family has
    x = 0 on every draw, so its shader never runs the lobe. A draw's declaration alone therefore cannot be the test.
  - The alpha test separates them: disassembled with the vendor's own decoder (d3dcompiler_47!D3DDisassemble, the
    same way checks/test_dxbc_discard.py does), the hair shader discards and the other family's does not, and the
    hair family's t0 is 22.3% fully transparent texels against 0.0% for the other (measured from the capture's DDS).
  - The `PSParamBuffer1` that declares the pair is bound at slot 1 with 208 bytes against its 192-byte declaration in
    the hair draws (the same shape the sky shader shows: 112 bound for a 64-byte declaration), so the slot comes from
    the shader's RDEF bind table plus the sizes the draw binds, never from a size equality.

Part 2 is a native ASan+UBSan harness (hair_class.h, live_scene.h): the whole rule table, its precedence, the pinned
anisotropy scalar, the hair material's own key and hash, and that a grey_first refresh keeps the anisotropy.

Part 3 runs the worker against the fake runtime with the mock game's skinned draw carrying a shader that declares and
reads the pair, and pins: unset and =0 submit exactly today's materials; on, only a draw that is alpha-tested, skinned,
unblended, has an albedo and takes the lobe gets `aniso=0.500` under a hash of its own -- the cloth look-alike (lobe
off), the unskinned card and the draw with no declaration keep today's material and are counted as refused.

Not claimed: that these draws are visually 2B's hair (a hide-draw check needs a live run, which is not authorized),
which of scalp/lashes/cards a given draw is, and any aesthetic judgement of 0.5.
"""
import json
import os
import struct
import re
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-hair'
CAPTURE = A / 'runtime/laptop-play-20261114'
VENDOR = A / 'remix-probe/vendor'
FRAMES = {'pond': 'frame_67078468', 'desert': 'frame_67279062'}
ANISO1, ANISO2 = 'g_AnisoParam1', 'g_AnisoParam2'
TWO_LOBE = 'g_SecondarySpecParam'   # the second specular lobe: the family's own name for it, read as a declaration only
OFFSETS = {ANISO1: 96, ANISO2: 112}
sys.path.insert(0, str(C))

HARNESS = r'''
#include <array>
#include <cmath>
#include <cstdio>
#include <map>
#include <string>
#include <vector>
#include "hair_class.h"
#include "live_scene.h"
#include "sky_layer.h"

static int failures = 0;
static void check(const char* what, bool ok) { if (!ok) { ++failures; std::printf("FAIL %s\n", what); } }
struct Made { unsigned long long hash; int drawcall, translucent; float anisotropy; const wchar_t* albedo; };
static std::map<unsigned long long, Made> made;
static unsigned long long next_handle = 0x1000;
static remixapi_ErrorCode REMIXAPI_CALL create_material(const remixapi_MaterialInfo* i, remixapi_MaterialHandle* out) {
    Made m{};
    if (i) {
        m.hash = i->hash;
        m.albedo = i->albedoTexture;
        m.anisotropy = 0.f;
        struct Head { remixapi_StructType sType; const void* pNext; };
        for (const Head* h = static_cast<const Head*>(i->pNext); h; h = static_cast<const Head*>(h->pNext)) {
            if (h->sType == REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT) {
                const auto* e = reinterpret_cast<const remixapi_MaterialInfoOpaqueEXT*>(h);
                m.drawcall = int(e->useDrawCallAlphaState);
                m.anisotropy = e->anisotropy;
            }
            if (h->sType == REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_TRANSLUCENT_EXT) m.translucent = 1;
        }
    }
    made[next_handle] = m;
    *out = reinterpret_cast<remixapi_MaterialHandle>(next_handle++);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL ok_handle(void*) { return REMIXAPI_ERROR_CODE_SUCCESS; }
static Made& at(remixapi_MaterialHandle h) { return made[reinterpret_cast<unsigned long long>(h)]; }

// One scene draw as the live path sees it, spelled out per case so a field a rule reads cannot hide behind a default:
// the measured state of the hair draws in the two captures is unblended, alpha-tested, skinned, lobe on, albedo at t0.
static hair_class::Draw draw() {
    hair_class::Draw d;
    d.blend_enabled = false;
    d.alpha_test = true;
    d.skinned = true;
    d.aniso_declared = true;
    d.aniso_lobe = true;
    d.albedo = 7;
    return d;
}
int main(int argc, char** argv) {
    const std::string dir = argc > 1 ? argv[1] : ".";
    const std::wstring wdir(dir.begin(), dir.end());
    {   // ---- the classifier: the measured hair state, then every rule on its own ----------------------
        check("classify: the measured hair state is hair", hair_class::hair(draw()));
        check("classify: ... with a reason of its own", hair_class::why(draw()) == hair_class::kHair);
        { auto d = draw(); d.blend_enabled = true;
          check("classify: a blended draw is not hair (the captures' hair is opaque)",
                !hair_class::hair(d) && hair_class::why(d) == hair_class::kBlended); }
        { auto d = draw(); d.alpha_test = false;
          check("classify: a solid surface is not hair (the cloth family's t0 is 0.0% transparent texels)",
                !hair_class::hair(d) && hair_class::why(d) == hair_class::kNotAlphaTested); }
        { auto d = draw(); d.skinned = false;
          check("classify: an unskinned alpha-tested card is not hair (foliage, a decal)",
                !hair_class::hair(d) && hair_class::why(d) == hair_class::kNotSkinned); }
        { auto d = draw(); d.sky = true;
          check("classify: the sky is not hair", !hair_class::hair(d) && hair_class::why(d) == hair_class::kSky); }
        { auto d = draw(); d.effect = true;
          check("classify: an effects shader is not hair",
                !hair_class::hair(d) && hair_class::why(d) == hair_class::kEffect); }
        { auto d = draw(); d.depth_only = true;
          check("classify: a depth-only pass is not hair",
                !hair_class::hair(d) && hair_class::why(d) == hair_class::kDepthOnly); }
        { auto d = draw(); d.albedo = 0;
          check("classify: a draw with no captured albedo is not hair (no material to make anisotropic)",
                !hair_class::hair(d) && hair_class::why(d) == hair_class::kNoAlbedo); }
        { auto d = draw(); d.aniso_declared = false; d.aniso_lobe = false;
          check("classify: no g_AnisoParam pair is not hair (skin, foliage, the lit surfaces)",
                !hair_class::hair(d) && hair_class::why(d) == hair_class::kNoAnisoDecl); }
        { auto d = draw(); d.aniso_lobe = false;
          check("classify: a draw that does not take the lobe is not hair (the cloth family, the 10,656-index mesh)",
                !hair_class::hair(d) && hair_class::why(d) == hair_class::kNoAnisoLobe); }
        { auto d = draw(); d.sky = true; d.effect = true; d.alpha_test = false; d.skinned = false; d.albedo = 0;
          d.aniso_lobe = false;
          check("classify: every refusal beats the declaration", !hair_class::hair(d) &&
                hair_class::why(d) == hair_class::kNotAlphaTested); }
        check("classify: the anisotropy scalar is pinned, finite and inside the runtime's (-1, 1)",
              hair_class::kAnisotropy == 0.5f && std::isfinite(hair_class::kAnisotropy) &&
              hair_class::kAnisotropy > -1.f && hair_class::kAnisotropy < 1.f);
    }
    {   // ---- the material a classified hair draw is built with --------------------------------------
        terrain_bake::Image im; im.w = 2; im.h = 2;
        for (int i = 0; i < 4; ++i) {
            im.rgba.push_back(0.4f); im.rgba.push_back(0.5f); im.rgba.push_back(0.6f); im.rgba.push_back(1.f);
        }
        const std::wstring source = wdir + L"/live_1.dds";
        check("setup: the albedo file is on disk",
              live_scene::write_whole(source, terrain_bake::dds_bytes(im, false, false)));
        remixapi_Interface api{};
        api.CreateMaterial = create_material;
        api.DestroyMaterial = reinterpret_cast<decltype(api.DestroyMaterial)>(ok_handle);
        live_scene::State s;
        s.texture_paths = {source}; s.landed = {1};
        const auto plain = live_scene::material_for(api, s, 1);
        const auto hair = live_scene::material_for(api, s, 1, 7, 0, 0, 0, 0, live_capture::MaterialConstants{},
                                                  false, false, true);
        check("material: today's material is isotropic", plain && at(plain).anisotropy == 0.f);
        check("material: the hair material carries the pinned anisotropy",
              hair && at(hair).anisotropy == hair_class::kAnisotropy);
        check("material: its own hash, so a cache cannot reuse the isotropic material",
              plain && hair && at(plain).hash != at(hair).hash);
        check("material: the albedo path is still the draw's texture",
              hair && at(hair).albedo && at(plain).albedo &&
              std::wstring(at(hair).albedo) == std::wstring(at(plain).albedo));
        check("material: no draw-call alpha state (the particle path owns that)", hair && at(hair).drawcall == 0);
        check("material: and no translucency (water owns that)", hair && at(hair).translucent == 0);
        check("material: a second ask for the hair material is the same one",
              live_scene::material_for(api, s, 1, 7, 0, 0, 0, 0, live_capture::MaterialConstants{}, false, false,
                                       true) == hair);
        check("material: and today's material is still today's material", live_scene::material_for(api, s, 1) == plain);
        // An alpha-tested hair card keeps the game's own comparison and reference: the cutout is what makes it a card.
        const auto card = live_scene::material_for(api, s, 1, 4, 200, 0, 0, 0, live_capture::MaterialConstants{},
                                                   false, false, true);
        check("material: an alpha-tested hair card keeps cutout and its anisotropy",
              card && at(card).anisotropy == hair_class::kAnisotropy && at(card).hash != at(hair).hash);
    }
    {   // ---- grey_first: the refreshed material stays a hair material --------------------------------
        // The albedo lands after the material exists, so the first one is grey and refresh_incomplete_materials
        // destroys and re-creates it under its own hash. A refresh that dropped the anisotropy would leave the hair
        // isotropic the moment its texture arrived -- and only on the first frame of a session.
        terrain_bake::Image im; im.w = 2; im.h = 2;
        for (int i = 0; i < 4; ++i) {
            im.rgba.push_back(0.3f); im.rgba.push_back(0.3f); im.rgba.push_back(0.3f); im.rgba.push_back(1.f);
        }
        const std::wstring source = wdir + L"/live_2.dds";
        remixapi_Interface api{};
        api.CreateMaterial = create_material;
        api.DestroyMaterial = reinterpret_cast<decltype(api.DestroyMaterial)>(ok_handle);
        live_scene::State s;
        s.texture_paths = {wdir + L"/live_0.dds", source};
        s.landed = {1, 0};
        const auto grey = live_scene::material_for(api, s, 2, 7, 0, 0, 0, 0, live_capture::MaterialConstants{},
                                                   false, false, true);
        check("grey_first: the pending hair material is anisotropic",
              grey && at(grey).anisotropy == hair_class::kAnisotropy);
        const unsigned long long grey_hash = grey ? at(grey).hash : 0;
        check("setup: the albedo lands", live_scene::write_whole(source, terrain_bake::dds_bytes(im, false, false)));
        s.landed = {1, 1};
        live_scene::refresh_incomplete_materials(api, s);
        bool refreshed = false, refreshed_aniso = false;
        for (const auto& [handle, m] : made)
            if (m.hash == grey_hash && handle != reinterpret_cast<unsigned long long>(grey)) {
                refreshed = true;
                refreshed_aniso = m.anisotropy == hair_class::kAnisotropy;
            }
        check("grey_first: the landed material is re-created under the same hash", refreshed);
        check("grey_first: and is still a hair material", refreshed_aniso);
    }
    {   // ---- the placement the LIVE path runs, against the captured shader and the draw's own bindings ----------
        // The rules can all be right and every hair draw still be refused if sky_layer::place does not find the slot:
        // in the captures 208 bytes are bound for a 192-byte declaration, so no size equality can. This reads the
        // capture's own files through the production helpers instead of trusting the gate's Python copy of the rule.
        if (argc > 2) {
            std::FILE* f = std::fopen(argv[2], "rb");
            check("placement: the evidence file opens", f != nullptr);
            if (f) {
                char blob_path[4096] = "", on_path[4096] = "", off_path[4096] = "";
                std::array<std::uint32_t, sky_layer::kSlots> bound{};
                int expect_on = 0, expect_off = 0;
                int got = std::fscanf(f, "%4095s", blob_path);
                for (std::size_t i = 0; i < sky_layer::kSlots; ++i) got += std::fscanf(f, "%u", &bound[i]);
                got += std::fscanf(f, "%4095s %4095s %d %d", on_path, off_path, &expect_on, &expect_off);
                std::fclose(f);
                check("placement: the evidence file parses", got == int(1 + sky_layer::kSlots + 4));
                const auto slurp = [](const char* path) {
                    std::vector<unsigned char> bytes;
                    if (std::FILE* g = std::fopen(path, "rb")) {
                        unsigned char buf[8192];
                        std::size_t n = 0;
                        while ((n = std::fread(buf, 1, sizeof buf, g)) > 0) bytes.insert(bytes.end(), buf, buf + n);
                        std::fclose(g);
                    }
                    return bytes;
                };
                std::vector<sky_layer::Decl> decls;
                check("placement: the captured hair shader's RDEF parses", sky_layer::members(slurp(blob_path), decls));
                // Both members of ONE buffer, the way the live path asks (the shader declares twelve buffers, and place()
                // refuses as soon as any unrelated one is bound smaller than its declaration).
                const std::vector<sky_layer::Decl> pair = sky_layer::both_members(decls, "g_AnisoParam1", "g_AnisoParam2");
                check("placement: the pair is one buffer's, not two", pair.size() == 2);
                std::vector<std::uint32_t> placed;
                check("placement: the slot is found with the draw's own binding sizes (208 for 192)",
                      !pair.empty() && sky_layer::place(pair, bound, placed));
                // ... and it is NOT found when every declared buffer is offered instead: that is why the live path asks
                // about the pair alone. Pinned so the filter cannot be dropped as a "simplification".
                std::vector<std::uint32_t> all_placed;
                check("placement: offering every declared buffer is refused for this shader (the filter's reason)",
                      !sky_layer::place(decls, bound, all_placed));
                std::size_t hits = 0, index = 0;
                for (std::size_t i = 0; i < pair.size(); ++i)
                    if (pair[i].name == "g_AnisoParam2") { ++hits; index = i; }
                check("placement: g_AnisoParam2 is declared exactly once", hits == 1);
                if (hits == 1 && index < placed.size()) {
                    check("placement: and it is placed at slot 1, where the draw binds it", placed[index] == 1);
                    const auto read = [&](const char* path) {
                        const std::vector<unsigned char> bytes = slurp(path);
                        std::array<sky_layer::Binding, sky_layer::kSlots> bindings{};
                        if (placed[index] < sky_layer::kSlots)
                            bindings[placed[index]] = {static_cast<std::uint32_t>(bytes.size()), bytes.data()};
                        float v[4] = {0, 0, 0, 0};
                        return sky_layer::detail::value(pair[index], placed[index], bindings, v) ? v[0] : -1.f;
                    };
                    check("placement: the lobe-on draw reads 1 from the captured bytes", read(on_path) == float(expect_on));
                    check("placement: the lobe-off draw reads 0 from the captured bytes", read(off_path) == float(expect_off));
                }
            }
        }
    }
    std::printf("failures=%d\n", failures);
    return failures ? 1 : 0;
}
'''


def field(line, key):
    assert f'{key}=' in line, f'the log line does not report {key}=: {line}'
    return line.split(f'{key}=')[1].split()[0]


def blobs():
    return sorted((CAPTURE / 'shaders').glob('ps_*.dxbc'))


def declarations(ps):
    import dump_shader_decls as D
    path = CAPTURE / 'shaders' / f'ps_{ps}.dxbc'
    cb, res = D.declarations(D.chunks(path.read_bytes())['RDEF'][0])
    return cb, res


def drawn_shaders(frame):
    """ps_hash -> the frame's draw directories, from the capture's own capture.json files."""
    out = {}
    for draw in sorted((CAPTURE / FRAMES[frame]).glob('draw_*')):
        j = json.loads((draw / 'capture.json').read_text())
        out.setdefault(int(j['ps_hash']), []).append(draw)
    return out


def slot_reading(draw, declared_size, binds):
    """The slot a declared constant buffer is bound at, per the RDEF bind table plus the sizes the draw binds: exactly
    one binding whose size can hold the declaration, or nothing (never a size equality, which the hair draws fail
    because 208 bytes are bound for a 192-byte declaration)."""
    j = json.loads((draw / 'capture.json').read_text())
    bound = {c['slot']: c['bytes'] for c in j['ps_cbs']}
    fits = [b for b in binds if bound.get(b, 0) >= declared_size]
    return (fits[0], bound.get(fits[0])) if len(fits) == 1 else (None, None)


def discards(work, shaders):
    """The vendor disassembler's own verdict per shader (the technique checks/test_dxbc_discard.py established)."""
    src = C / 'dxbc_disasm.cpp'
    exe = work / 'disasm.exe'
    subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O1', '-static', '-static-libgcc', '-static-libstdc++',
                    str(src), '-o', str(exe), '-ld3dcompiler'], check=True)
    indir = work / 'disasm-in'
    indir.mkdir(exist_ok=True)
    for ps in shaders:
        (indir / f'ps_{ps}.dxbc').write_bytes((CAPTURE / 'shaders' / f'ps_{ps}.dxbc').read_bytes())
    prefix = work / 'prefix'
    env = {'WINEPREFIX': str(prefix), 'WINEDEBUG': '-all', 'PATH': '/usr/bin:/bin'}
    r = subprocess.run(['wine', str(exe), f'Z:{indir}'], capture_output=True, text=True, timeout=600, env=env,
                       cwd=work)
    assert r.returncode == 0, f'dxbc_disasm failed rc={r.returncode}: {r.stderr[-400:]}'
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == 'DISCARD':
            out[int(parts[1].split('_')[-1])] = int(parts[2])
    assert len(out) == len(shaders), f'not every shader was disassembled: {out}'
    return out


def measured_facts(work):
    """Part 1: the declaration table and the per-draw lobe flag, re-read from the capture (never from a table here)."""
    import dump_shader_decls as D
    del D
    declarers = {ANISO1: 0, ANISO2: 0, TWO_LOBE: 0}
    both_together = True
    offsets_ok = True
    one_buffer = True
    for blob in blobs():
        cb, _res = declarations(blob.stem.split('_')[-1])
        names = {v: (o, n) for (n, _s, vs) in cb for (v, o, _z) in vs}
        for key in declarers:
            if key in names:
                declarers[key] += 1
        if (ANISO1 in names) != (ANISO2 in names):
            both_together = False
        if ANISO1 in names:
            offsets_ok &= names[ANISO1][0] == OFFSETS[ANISO1] and names[ANISO2][0] == OFFSETS[ANISO2]
            one_buffer &= names[ANISO1][1] == names[ANISO2][1]   # both in the same declared constant buffer
        if TWO_LOBE in names:
            offsets_ok &= ANISO1 in names and ANISO2 in names
    assert len(blobs()) == 625, f'the capture holds 625 pixel shaders: {len(blobs())}'
    assert both_together, 'g_AnisoParam1 and g_AnisoParam2 must always be declared together'
    assert one_buffer, 'the pair must sit in ONE declared buffer (PSParamBuffer1), as the disassembly reads it'
    assert offsets_ok, 'the pair must sit at 96/112 in the buffer that declares it, as the disassembly reads it'
    assert declarers[ANISO1] == 46 and declarers[TWO_LOBE] == 21, declarers
    facts = {'blobs': len(blobs()), 'declarers': dict(declarers), 'offsets': dict(OFFSETS)}
    per_frame = {}
    for frame in FRAMES:
        drawn = drawn_shaders(frame)
        families = {}
        for ps, draws in drawn.items():
            cb, res = declarations(ps)
            names = {v for (_n, _s, vs) in cb for (v, _o, _z) in vs}
            if ANISO2 not in names:
                continue
            size = next(s for (n, s, vs) in cb if any(v == ANISO2 for v, _o, _z in vs))
            binds = [r[2] for r in res if r[1] == 'cbuffer' and r[0] == 'PSParamBuffer1']
            slot, bound = slot_reading(draws[0], size, binds)
            assert slot is not None, f'{ps}: the aniso buffer must have exactly one binding that can hold it'
            lobe = []
            for draw in draws:
                raw = (draw / f'ps_cb_{slot}.bin').read_bytes()
                import struct
                lobe.append(struct.unpack_from('<f', raw, OFFSETS[ANISO2])[0])
                state = json.loads((draw / 'capture.json').read_text())['state']
                assert state['blend_enable'] == 0 and state['depth_write'] == 0 and state['depth_enable'] == 1, (
                    f'{draw}: every aniso draw in these captures is opaque with depth-write off: {state}')
            families[ps] = {'draws': len(draws), 'two_lobe': TWO_LOBE in names, 'slot': slot, 'declared': size,
                            'bound': bound, 'lobe': lobe, 'blob': CAPTURE / 'shaders' / f'ps_{ps}.dxbc',
                            'first_draw': draws[0], 'size': size,
                            'binds': binds,
                            'max_index': max(int(json.loads((d / 'capture.json').read_text())['index_count'])
                                             for d in draws)}
        hair = [ps for ps, f in families.items() if f['two_lobe']]
        cloth = [ps for ps, f in families.items() if not f['two_lobe']]
        assert len(families) == 2 and len(hair) == 1, f'{frame}: exactly two aniso families, one with {TWO_LOBE}: ' \
                                                      f'{sorted(families)}'
        h, c = families[hair[0]], families[cloth[0]]
        assert h['slot'] == 1 and c['slot'] == 1, families
        assert h['bound'] > h['declared'], f'{frame}: the hair buffer is bound larger than declared: {h}'
        assert c['bound'] == c['declared'], f'{frame}: the other family binds exactly its declaration: {c}'
        assert any(v > 0 for v in h['lobe']), f'{frame}: the hair family must take the lobe on some draw: {h["lobe"]}'
        assert not any(v > 0 for v in c['lobe']), f'{frame}: the other family must never take the lobe: {c["lobe"]}'
        assert h['draws'] == 3 and c['draws'] in (6, 10), f'{frame}: draw counts moved: {h["draws"]} / {c["draws"]}'
        # The measured pattern: the hair family takes the lobe on two of its three draws (the third is the
        # 10,656-index mesh the camp capture's scout report also found with cb1[7].x = 0), the other family never.
        assert sorted(h['lobe']) == [0.0, 1.0, 1.0], f'{frame}: the hair family\'s lobe pattern moved: {h["lobe"]}'
        assert sorted(set(c['lobe'])) == [0.0], f'{frame}: the other family must carry 0 on every draw: {c["lobe"]}'
        per_frame[frame] = {'hair': hair[0], 'other': cloth[0], 'lobe': h['lobe'], 'other_lobe': c['lobe'],
                            'draws': (h['draws'], c['draws'])}
    facts['frames'] = per_frame
    verdicts = discards(work, sorted({per_frame[f][k] for f in FRAMES for k in ('hair', 'other')}))
    for frame in FRAMES:
        hair_ps, other_ps = per_frame[frame]['hair'], per_frame[frame]['other']
        assert verdicts[hair_ps] == 1, f'{frame}: the hair shader discards (alpha cards): {verdicts}'
        assert verdicts[other_ps] == 0, f'{frame}: the other family does not (a solid surface): {verdicts}'
    facts['discard'] = verdicts
    # The offsets are only worth anything if the shader reads those registers: assert the instruction shapes the live
    # path's member-to-register mapping rests on, in the vendor disassembler's own text.
    hair_ps = per_frame['pond']['hair']
    asm = (work / 'disasm-in' / f'ps_{hair_ps}.asm').read_text()
    # cb1[3] is the tie: g_AlbedoColor sits at offset 48 of the same struct, so the buffer the shader reads as b1 is the
    # one that declares the pair at 96/112. (The shader also reads a second PSParamBuffer1 at b2 -- fog -- so the mere
    # presence of cb2 reads proves nothing either way.)
    for shape in ('cb1[6].x', 'cb1[7].x', 'cb1[7].yzyy', 'cb1[3].xyzx'):
        assert shape in asm, f'ps_{hair_ps} must read {shape} (the mapping the offsets rest on)'
    facts['asm_shapes'] = ['cb1[6].x', 'cb1[7].x', 'cb1[7].yzyy', 'cb1[3].xyzx']
    # What the C++ side must reproduce on real data: the declared members, the draw's own binding sizes, the placed slot
    # and the two lobe values. The harness runs sky_layer::members/place/detail::value on these same files.
    hair = per_frame['pond']['hair']
    on = [d for d in sorted((CAPTURE / FRAMES['pond']).glob('draw_*'))
          if json.loads((d / 'capture.json').read_text())['ps_hash'] == hair and
          struct.unpack_from('<f', (d / 'ps_cb_1.bin').read_bytes(), OFFSETS[ANISO2])[0] > 0][0]
    off = [d for d in sorted((CAPTURE / FRAMES['pond']).glob('draw_*'))
           if json.loads((d / 'capture.json').read_text())['ps_hash'] == hair and
           struct.unpack_from('<f', (d / 'ps_cb_1.bin').read_bytes(), OFFSETS[ANISO2])[0] == 0][0]
    bound = {c['slot']: c['bytes'] for c in json.loads((on / 'capture.json').read_text())['ps_cbs']}
    placement = work / 'placement.txt'
    placement.write_text('\n'.join([
        str(CAPTURE / 'shaders' / f'ps_{hair}.dxbc'),
        ' '.join(str(bound.get(i, 0)) for i in range(16)),
        str(on / 'ps_cb_1.bin'), str(off / 'ps_cb_1.bin'), '1', '0']) + '\n')
    facts['placement'] = str(placement)
    return facts


def native(work):
    """Part 2: the classifier table and the hair material, natively, sanitized."""
    (work / 'harness.cpp').write_text(HARNESS)
    cmd = ['g++', '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
           '-Wall', '-Wextra', '-Werror', '-DREMIX_WINAPI_NO_INCLUDE', '-DREMIX_WINAPI_NO_LIBRARY_LOADER',
           '-D_WIN64=1', '-D__stdcall=', '-D__declspec(x)=', '-isystem', str(VENDOR), '-I', str(C),
           str(work / 'harness.cpp'), '-o', str(work / 'harness')]
    built = subprocess.run(cmd, capture_output=True, text=True)
    assert built.returncode == 0, 'the native harness must compile:\n' + built.stderr[-2500:]
    run = subprocess.run([str(work / 'harness'), str(work), str(work / 'placement.txt')], capture_output=True,
                         text=True)
    assert run.returncode == 0, 'the classifier or the hair material is wrong:\n' + (run.stdout + run.stderr)[-2500:]


def main():
    facts = measured_facts(OUT / 'tmp')
    work = Path(tempfile.mkdtemp(prefix='live-hair-'))
    (work / 'placement.txt').write_text(Path(facts['placement']).read_text())   # the harness reads the same evidence
    native(work)
    import test_remix_live as tr
    import test_menu_overlay as tmo
    import test_nscn_scene as ts
    tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE_HAIR', 'MOCK_HAIR_PS', 'FAKE_REMIX_INSTANCE_LOG',
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
            env['NIER_REMIX_LIVE_HAIR'] = switch
        env.update(extra or {})
        _, _, log, fake = tr.run(work, name, env)
        assert fake and 'VIOLATION' not in fake, fake[-1500:]
        return log, fake

    def materials(fake):
        return [l for l in fake.splitlines() if l.startswith('CreateMaterial ')]

    def aniso_values(fake):
        return [float(field(l, 'aniso')) for l in materials(fake)]

    def counted(log):
        return [l for l in log.splitlines() if 'remix: live hair' in l]

    def mesh_hashes(fake):
        return {int(field(l, 'mathash')) for l in fake.splitlines() if l.startswith('CreateMesh ')}

    hair_draw = {'MOCK_HAIR_PS': '1'}
    skinned = 'live-skinned'
    # 1. Default: the hair shader's draw takes today's material, and nothing about the classification runs.
    default_log, default_fake = run('default', skinned, None, hair_draw)
    assert not counted(default_log), 'the switch is off by default: nothing may be counted'
    assert aniso_values(default_fake) and not any(aniso_values(default_fake)), \
        'no material may carry anisotropy with the switch off:\n' + '\n'.join(materials(default_fake)[-3:])
    today = mesh_hashes(default_fake)
    results = {'default': f'switch off: {len(materials(default_fake))} materials, all isotropic'}
    # 2. An explicit 0 is the same program as unset.
    zero_log, zero_fake = run('zero', skinned, '0', hair_draw)
    assert not counted(zero_log), 'explicit 0 must not be read as "on"'
    assert mesh_hashes(zero_fake) == today, 'NIER_REMIX_LIVE_HAIR=0 must build today\'s materials'
    results['zero-parity'] = 'unset and =0 build the same materials'
    # 3. On: the alpha-tested skinned draw that takes the lobe gets the pinned anisotropy, under a hash of its own.
    on_log, on_fake = run('on', skinned, '1', hair_draw)
    values = [v for v in aniso_values(on_fake) if v]
    assert len(values) == 1 and abs(values[0] - 0.5) < 1e-6, (
        'exactly one anisotropic material, at the pinned 0.5: ' + '\n'.join(materials(on_fake)))
    line = [l for l in materials(on_fake) if field(l, 'aniso') != '0.000'][0]
    assert field(line, 'path') != '-', f'the hair material still names the draw\'s albedo: {line}'
    assert field(line, 'drawcall') == '0', f'no draw-call alpha state: {line}'
    assert field(line, 'trans') == '0', f'no translucency: {line}'
    assert mesh_hashes(on_fake) and not (mesh_hashes(on_fake) & today), (
        f'the hair material must be its own hash: hair={sorted(mesh_hashes(on_fake))} today={sorted(today)}')
    counts = counted(on_log)
    assert counts, 'the switch is on: the classified draws must be counted'
    assert int(field(counts[-1], 'submitted')) >= 1, counts[-1]
    assert int(field(counts[-1], 'refused')) == 0, counts[-1]
    results['on-hair'] = 'alpha-tested skinned lobe draw: aniso 0.500, its own hash, same albedo'
    # 4. On, the lobe off (the capture's own cloth family and its 10,656-index mesh): today's material, counted refused.
    lobe_off_log, lobe_off_fake = run('on-lobe-off', skinned, '1', {'MOCK_HAIR_PS': '0'})
    assert not any(aniso_values(lobe_off_fake)), 'a draw that does not take the lobe may not become hair'
    counts = counted(lobe_off_log)
    assert counts and int(field(counts[-1], 'submitted')) == 0 and int(field(counts[-1], 'refused')) >= 1, counts[-1]
    results['on-lobe-off'] = 'declared, alpha-tested, skinned, lobe off: refused, today\'s material'
    # 5. On, no declaration: nothing to classify, today's material (the skin / lit surface negative).
    plain_log, plain_fake = run('on-plain', skinned, '1')
    assert not any(aniso_values(plain_fake)), 'a shader without the pair may not become hair'
    counts = counted(plain_log)
    assert counts and int(field(counts[-1], 'submitted')) == 0, counts[-1]
    assert int(field(counts[-1], 'refused')) == 0, 'nothing declares the pair in this run: nothing to refuse'
    results['on-plain'] = 'no declaration: nothing classified'
    # 6. On, the same hair shader on an unskinned draw: refused (a card that no bone moves is not hair), and the
    # materials are exactly the ones the same draw gets with the switch off.
    card_log, card_fake = run('on-unskinned', 'live', '1', hair_draw)
    assert not any(aniso_values(card_fake)), 'an unskinned alpha-tested draw may not become hair'
    counts = counted(card_log)
    assert counts and int(field(counts[-1], 'submitted')) == 0 and int(field(counts[-1], 'refused')) >= 1, counts[-1]
    _, card_off = run('off-unskinned', 'live', None, hair_draw)
    assert mesh_hashes(card_fake) == mesh_hashes(card_off), (
        'a refused draw must keep exactly today\'s materials: '
        f'{sorted(mesh_hashes(card_fake))} vs {sorted(mesh_hashes(card_off))}')
    results['on-unskinned'] = 'the same shader without a skinned layout: refused, today\'s materials'
    # 7. On, with grey_first at its shipped default (the variable unset, or =1: both enable it): the material a first
    # sight gets is grey until its albedo lands, and the refreshed one must still be a hair material.
    grey_log, grey_fake = run('on-grey-default', skinned, '1',
                              {'MOCK_HAIR_PS': '1', 'NIER_REMIX_LIVE_GREY_FIRST': '1'})
    grey_values = aniso_values(grey_fake)
    assert grey_values and all(abs(v - 0.5) < 1e-6 for v in grey_values), (
        'with grey_first on, every material of the hair draw carries the anisotropy: '
        + '\n'.join(materials(grey_fake)))
    assert int(field(counted(grey_log)[-1], 'submitted')) >= 1, counted(grey_log)[-1]
    results['on-grey-default'] = f'grey_first on: {len(grey_values)} material(s) of the hair draw, all at 0.500'
    # 8. No instance ever named a material hash that is not live.
    for name, fake in (('default', default_fake), ('zero', zero_fake), ('on', on_fake),
                       ('on-lobe-off', lobe_off_fake), ('on-plain', plain_fake), ('on-unskinned', card_fake),
                       ('on-grey-default', grey_fake)):
        live = [int(field(l, 'matlive')) for l in fake.splitlines() if l.startswith('DrawInstance ')]
        assert live and all(v == 1 for v in live), f'{name}: an instance named a material hash that is not live: {live}'
    results['lifetimes'] = 'every drawn mesh resolves to a live material hash in all seven runs'
    print('W5 hair class gate: OK')
    print('  measured:', json.dumps(facts['declarers']), 'offsets', facts['offsets'], 'discard', facts['discard'])
    for frame, f in facts['frames'].items():
        print(f'  {frame}: hair ps_{f["hair"]} {f["draws"][0]} draws lobe {f["lobe"]}; '
              f'other ps_{f["other"]} {f["draws"][1]} draws lobe {f["other_lobe"]}')
    for k, v in results.items():
        print(f'  {k}: {v}')


def outside():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'tmp').mkdir(parents=True, exist_ok=True)
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
               GALLIUM_DRIVER='llvmpipe', WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=',
               TMPDIR=str(OUT / 'tmp'))
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable,
                    str(Path(__file__).resolve()), '--inside'], env=env, cwd=OUT, check=True)


if __name__ == '__main__':
    if '--inside' in sys.argv:
        main()
    else:
        outside()
