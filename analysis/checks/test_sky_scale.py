#!/usr/bin/env python3
"""Frozen W1.3 step 1b gate: a textured sky layer (g_AlbedoParam.w == 0) becomes a scaled copy of its texture.

The game's sky shader computes `base = t0 * g_IntensityParam.y * g_MeshColor.rgb` for a textured layer
(runtime/w1-disasm/sky_ps.asm:24-30). Remix's `albedoConstant` *replaces* the albedo texture instead of multiplying it
(replay/research-2026-11-12/remix_material_api.md:19-21), so the only expression of t0 * factor is a texture that already
holds the product. This gate pins that path natively, sanitized, on real files:

  - BC2 (DXT3) decodes: camp's 2048x2048 cloud layers are BC2, which terrain_bake::read_dds could not read. The fixture
    is a 16-byte block built from the DDS/DX10 header and the BC2 layout (8 bytes of explicit 4-bit alpha, row-major, low
    nibble first, then a BC1-shaped colour block that always interpolates four colours) with hand-computed texels; it was
    cross-checked once against ImageMagick's independent DXT3 decoder (W1_SKY_SCALE.md);
  - the copy keeps the source's colour encoding: an UNORM source stays UNORM, an sRGB source stays sRGB, so the runtime's
    own gamma decode is applied exactly once;
  - the material names `sky_<id>_<factor>.dds` and that file's mip 0 is the source's mip 0 times the factor;
  - factor 1 (and a switch that never set a factor) submits today's material, byte for byte: the default-off path does
    not change;
  - a source that cannot be read, and more copies than the session cap, keep today's texture (never a black or missing
    sky) and are counted.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
VENDOR = C.parent / 'remix-probe/vendor'

HARNESS = r'''
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include "live_scene.h"
#include "sky_scale.h"
#include "terrain_bake.h"

static int failures = 0;
static void check(const char* what, bool ok) { if (!ok) { ++failures; std::printf("FAIL %s\n", what); } }

// A BC2 DDS written field by field from the DDS/DX10 layout (not through terrain_bake::dds_bytes, so the reader is not
// its own oracle). `blocks` is the raw 16-byte-per-4x4-block payload.
static std::vector<unsigned char> bc2_file(std::uint32_t dxgi, std::uint32_t w, std::uint32_t h,
                                           const std::vector<unsigned char>& blocks, std::uint32_t misc = 0) {
    std::uint32_t hd[32] = {};
    hd[0] = 0x20534444;                 // "DDS "
    hd[1] = 124;                        // header size
    hd[2] = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000;   // CAPS | HEIGHT | WIDTH | PIXELFORMAT | LINEARSIZE
    hd[3] = h; hd[4] = w;
    hd[5] = static_cast<std::uint32_t>(blocks.size());
    hd[7] = 1;                          // mip count
    hd[19] = 32;                        // pixel format size
    hd[20] = 0x4;                       // DDPF_FOURCC
    hd[21] = 0x30315844;                // "DX10"
    hd[27] = 0x1000;                    // DDSCAPS_TEXTURE
    const std::uint32_t dx10[5] = {dxgi, 3 /* TEXTURE2D */, misc, 1, 0};
    std::vector<unsigned char> out(148 + blocks.size());
    std::memcpy(out.data(), hd, sizeof hd);
    std::memcpy(out.data() + 128, dx10, sizeof dx10);
    std::memcpy(out.data() + 148, blocks.data(), blocks.size());
    return out;
}

// One BC2 block: alpha nibbles 0..F row-major (low nibble first), colour c0 = blue, c1 = red with c0 < c1 -- a BC1-style
// 3-colour block would put transparent black at index 3 here -- and the index pattern 0,1,2,3 on the first row.
static std::vector<unsigned char> bc2_block() {
    const unsigned char alpha[8] = {0x10, 0x32, 0x54, 0x76, 0x98, 0xba, 0xdc, 0xfe};
    std::vector<unsigned char> b(alpha, alpha + 8);
    b.push_back(0x1f); b.push_back(0x00);   // c0 = 0x001F: (0, 0, 1)
    b.push_back(0x00); b.push_back(0xf8);   // c1 = 0xF800: (1, 0, 0)
    b.push_back(0xe4); b.push_back(0x00); b.push_back(0x00); b.push_back(0x00);   // 2-bit indices 0,1,2,3 then 0
    return b;
}

static bool near(float a, float b, float tol = 1.5f / 255.f) { return std::fabs(a - b) <= tol; }
// The colour the runtime's shader gets out of an albedo texture: one pow(x, 2.2) over the stored values.
static float mean_decoded(const terrain_bake::Image& im) {
    double sum = 0.0;
    for (std::size_t i = 0; i < im.rgba.size() / 4; ++i) {
        double v = 0.0;
        for (int c = 0; c < 3; ++c) v += std::pow(static_cast<double>(im.rgba[i * 4 + c]), 2.2);
        sum += v / 3.0;
    }
    return static_cast<float>(sum / static_cast<double>(im.rgba.size() / 4));
}

struct Made { std::wstring path; unsigned long long hash; float aconst[3]; };
static std::map<unsigned long long, Made> made;
static unsigned long long next_handle = 0x1000;
static remixapi_ErrorCode REMIXAPI_CALL create_material(const remixapi_MaterialInfo* i, remixapi_MaterialHandle* out) {
    Made m;
    if (i->albedoTexture) m.path = i->albedoTexture;
    m.hash = i->hash;
    const auto* e = static_cast<const remixapi_MaterialInfoOpaqueEXT*>(i->pNext);
    for (int k = 0; k < 3; ++k)
        m.aconst[k] = e && e->sType == REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT ? (&e->albedoConstant.x)[k] : -1.f;
    made[next_handle] = m;
    *out = reinterpret_cast<remixapi_MaterialHandle>(next_handle++);
    return REMIXAPI_ERROR_CODE_SUCCESS;
}
static remixapi_ErrorCode REMIXAPI_CALL ok_handle(void*) { return REMIXAPI_ERROR_CODE_SUCCESS; }

int main(int argc, char** argv) {
    const std::string dir = argc > 1 ? argv[1] : ".";
    const std::wstring wdir(dir.begin(), dir.end());
    remixapi_Interface api{};
    api.CreateMaterial = create_material;
    api.DestroyMaterial = reinterpret_cast<decltype(api.DestroyMaterial)>(ok_handle);
    {   // ---- BC2 decode, from the fixture, with the texels hand-computed -----------------------------
        const auto file = bc2_file(74, 4, 4, bc2_block());
        terrain_bake::Image im;
        bool srgb = true;
        const bool read = terrain_bake::read_dds(file, im, &srgb, true);
        check("bc2: a BC2_UNORM file decodes", read && im.w == 4 && im.h == 4);
        check("bc2: UNORM is not reported as sRGB", read && !srgb);
        if (read && im.rgba.size() == 64) {
            check("bc2: texel 0 is c0", near(im.rgba[2], 1.f) && near(im.rgba[0], 0.f) && near(im.rgba[1], 0.f));
            check("bc2: texel 1 is c1", near(im.rgba[4], 1.f) && near(im.rgba[6], 0.f));
            // c0 < c1 on purpose: BC2's colour half always interpolates four colours.
            check("bc2: texel 2 is (2*c0+c1)/3", near(im.rgba[8], 85.f / 255.f) && near(im.rgba[10], 170.f / 255.f));
            check("bc2: texel 3 is (c0+2*c1)/3, not transparent black",
                  near(im.rgba[12], 170.f / 255.f) && near(im.rgba[14], 85.f / 255.f));
            // Explicit 4-bit alpha, row-major, low nibble first: texel (x, y) has alpha nibble y*4 + x.
            check("bc2: alpha nibbles 0,1,2,3 on the first row",
                  near(im.rgba[3], 0.f) && near(im.rgba[7], 17.f / 255.f) && near(im.rgba[11], 34.f / 255.f) &&
                  near(im.rgba[15], 51.f / 255.f));
            check("bc2: alpha of texel (1,1) is nibble 5", near(im.rgba[4 * 5 + 3], 85.f / 255.f));
            check("bc2: alpha of texel (3,3) is nibble F", near(im.rgba[4 * 15 + 3], 1.f));
        }
        {   // an sRGB-tagged BC2 is decoded to linear light
            terrain_bake::Image lin;
            bool tagged = false;
            check("bc2: BC2_UNORM_SRGB decodes", terrain_bake::read_dds(bc2_file(75, 4, 4, bc2_block()), lin, &tagged, true) &&
                                                 tagged);
            check("bc2: sRGB is decoded to linear", lin.rgba.size() == 64 && near(lin.rgba[8], 0.0908f, 0.002f) &&
                                                   near(lin.rgba[10], 0.4f, 0.01f));
        }
        terrain_bake::Image skipped;
        check("bc2: BC2_TYPELESS is refused", !terrain_bake::read_dds(bc2_file(73, 4, 4, bc2_block()), skipped, nullptr, true));
        check("bc2: without the flag, the terrain bake still refuses BC2",
              !terrain_bake::read_dds(bc2_file(74, 4, 4, bc2_block()), skipped));
        check("bc2: a truncated payload is refused", !terrain_bake::read_dds(
              std::vector<unsigned char>(file.begin(), file.begin() + 150), skipped, nullptr, true));
    }
    {   // ---- the scaled copy -------------------------------------------------------------------------
        // `mean_decoded` is the runtime's own view of an albedo texture: one pow(x, 2.2) over the stored bytes
        // (research-2026-11-12/remix_material_api.md: the shader always decodes, UNORM is one decode).
        const auto source = bc2_file(74, 4, 4, bc2_block());
        std::vector<unsigned char> out;
        check("scale: BC2 * 0.5 writes a copy", sky_scale::scaled_dds(source, 0.5f, out) && out.size() > 148);
        terrain_bake::Image back, src;
        bool back_srgb = true;
        check("scale: the copy reads back", terrain_bake::read_dds(out, back, &back_srgb));
        check("scale: the copy is UNORM (the live path's untagged albedo)", !back_srgb);
        check("scale: what the runtime decodes is the source's colour times the factor",
              terrain_bake::read_dds(source, src, nullptr, true) &&
              near(mean_decoded(back), mean_decoded(src) * 0.5f, 5.f / 255.f));
        check("scale: the bytes move by the factor^(1/2.2), not by the factor", back.rgba.size() == 64 &&
              near(back.rgba[8], 85.f / 255.f * std::pow(0.5f, 1.f / 2.2f), 2.f / 255.f));
        check("scale: the copy's alpha is the source's alpha", back.rgba.size() == 64 && near(back.rgba[7], 17.f / 255.f));
        std::vector<unsigned char> refused;
        {   // the copy keeps a mip chain, so a 2048x2048 sky layer is filtered instead of aliasing
            std::uint32_t mips = 0;
            std::memcpy(&mips, out.data() + 28, 4);
            check("scale: the copy carries the mip chain", mips == 3);   // 4x4 -> 2x2 -> 1x1
        }
        terrain_bake::Image mid; mid.w = 2; mid.h = 2;
        for (int i = 0; i < 4; ++i) { mid.rgba.push_back(0.4f); mid.rgba.push_back(0.5f); mid.rgba.push_back(0.6f); mid.rgba.push_back(1.f); }
        const auto tagged_source = terrain_bake::dds_bytes(mid);   // 29: sRGB-tagged
        check("scale: an sRGB-tagged layer is refused (its factor would sit in another space)",
              !sky_scale::scaled_dds(tagged_source, 0.5f, refused));
        check("scale: a cube layer is refused", !sky_scale::scaled_dds(bc2_file(74, 4, 4, bc2_block(), 0x4), 0.5f, refused));
        {   // a header claiming 8192x8192 with a 16-byte payload must not be decoded (it would allocate a gigabyte first)
            auto big = bc2_file(74, 4, 4, bc2_block());
            const std::uint32_t w = 8192, h = 8192;
            std::memcpy(big.data() + 12, &h, 4);
            std::memcpy(big.data() + 16, &w, 4);
            check("scale: an implausible header is refused before decoding", !sky_scale::scaled_dds(big, 0.5f, refused));
            check("scale: the size guard's own rule", !sky_scale::plausible_size(8192, 8192) &&
                                                     !sky_scale::plausible_size(0, 4) &&
                                                     sky_scale::plausible_size(2048, 2048));
        }
        check("scale: no factor is refused", !sky_scale::scaled_dds(source, 0.f, refused) &&
                                             !sky_scale::scaled_dds(source, -1.f, refused) &&
                                             !sky_scale::scaled_dds(source, std::nanf(""), refused));
        check("scale: garbage is refused", !sky_scale::scaled_dds(std::vector<unsigned char>(4, 'x'), 0.5f, refused) &&
                                           !sky_scale::scaled_dds({}, 0.5f, refused));
        {   // a 6x6 BC2 (four blocks, the last ones partial) decodes inside its bounds
            std::vector<unsigned char> blocks;
            for (int i = 0; i < 4; ++i) {
                const auto b = bc2_block();
                blocks.insert(blocks.end(), b.begin(), b.end());
            }
            terrain_bake::Image odd;
            check("bc2: a 6x6 texture keeps its size", terrain_bake::read_dds(bc2_file(74, 6, 6, blocks), odd, nullptr, true) &&
                                                        odd.w == 6 && odd.h == 6 && odd.rgba.size() == 6 * 6 * 4);
            check("bc2: the clipped block's last texel is the block's", odd.rgba.size() == 6 * 6 * 4 &&
                  near(odd.rgba[(5 * 6 + 5) * 4 + 2], 1.f));   // texel (1,1) of a block is c0 = blue
        }
    }
    {   // ---- the factor the shader applies ------------------------------------------------------------
        sky_layer::Inputs in;
        in.present = true;
        in.intensity = 0.5f;
        float factor = 0.f;
        check("factor: a textured layer with an identity mesh scales", sky_scale::layer_factor(in, factor) && factor == 0.5f);
        sky_layer::Inputs albedo = in;
        albedo.use_albedo = true;
        check("factor: an albedo override is not a textured layer", !sky_scale::layer_factor(albedo, factor));
        sky_layer::Inputs tinted = in;
        tinted.mesh[1] = 1.5f;
        check("factor: a non-identity mesh is refused (one factor, not three)", !sky_scale::layer_factor(tinted, factor));
        sky_layer::Inputs unity = in;
        unity.intensity = 1.f;
        check("factor: factor 1 keeps today's texture", !sky_scale::layer_factor(unity, factor));
        sky_layer::Inputs dark = in;
        dark.intensity = 0.001f;
        check("factor: a factor that quantises to zero is refused", !sky_scale::layer_factor(dark, factor));
        sky_layer::Inputs odd = in;
        odd.intensity = 1.3f;
        check("factor: quantised to the 1/64 grid", sky_scale::layer_factor(odd, factor) &&
                                                factor == sky_scale::quantize(1.3f) && factor != 1.3f);
        sky_layer::Inputs absent;
        check("factor: nothing folded without the members", !sky_scale::layer_factor(absent, factor));
        check("factor: quantised to 1/64", sky_scale::quantize(1.f / 3.f) == 21.f / 64.f);
        check("factor: the copy is named sky_<id>_<milli>.dds", sky_scale::file_name(7, 0.5f) == L"sky_7_500.dds" &&
                                                                sky_scale::file_name(7, 5.f) == L"sky_7_5000.dds");
    }
    {   // ---- the material a textured sky draw is submitted with ---------------------------------------
        terrain_bake::Image im; im.w = 2; im.h = 2;
        for (int i = 0; i < 4; ++i) { im.rgba.push_back(0.4f); im.rgba.push_back(0.5f); im.rgba.push_back(0.6f); im.rgba.push_back(1.f); }
        const std::wstring source = wdir + L"/live_1.dds";
        const auto layer_bytes = terrain_bake::dds_bytes(im, false, false);   // UNORM, as the live path tags an albedo
        check("setup: the layer file is on disk", live_scene::write_whole(source, layer_bytes));
        live_capture::MaterialConstants plain, scaled;
        scaled.albedo_scale = 0.5f;
        live_scene::State a, b;
        a.texture_paths = {source}; a.landed = {1};
        b.texture_paths = {source}; b.landed = {1};
        const auto today_handle = live_scene::material_for(api, a, 1);
        const auto plain_handle = live_scene::material_for(api, b, 1, 7, 0, 0, 0, 0, plain);
        check("parity: albedo_scale 1 is the material it was without constants",
              today_handle && plain_handle &&
              made[reinterpret_cast<unsigned long long>(today_handle)].path ==
                  made[reinterpret_cast<unsigned long long>(plain_handle)].path &&
              made[reinterpret_cast<unsigned long long>(today_handle)].hash ==
                  made[reinterpret_cast<unsigned long long>(plain_handle)].hash);
        live_scene::State s;
        s.texture_paths = {source}; s.landed = {1};
        const auto handle = live_scene::material_for(api, s, 1, 7, 0, 0, 0, 0, scaled);
        check("material: a textured sky layer gets a material", handle != nullptr);
        if (handle) {
            const Made& m = made[reinterpret_cast<unsigned long long>(handle)];
            check("material: it names sky_1_500.dds", m.path.size() > 13 &&
                  m.path.compare(m.path.size() - 13, 13, L"sky_1_500.dds") == 0);
            check("material: its constant colour stays 1,1,1", near(m.aconst[0], 1.f) && near(m.aconst[2], 1.f));
            check("material: it is its own material, not the unscaled one", m.hash != made[
                  reinterpret_cast<unsigned long long>(today_handle)].hash);
            std::vector<unsigned char> bytes;
            terrain_bake::Image copy, original;
            check("material: the copy is on disk and decodes to the layer times 0.5",
                  live_scene::read_whole(m.path, bytes) && terrain_bake::read_dds(bytes, copy) &&
                  terrain_bake::read_dds(layer_bytes, original) &&
                  near(mean_decoded(copy), mean_decoded(original) * 0.5f, 5.f / 255.f));
            check("material: the copy is written once", sky_scale::copies.load() == 1);
            const auto again = live_scene::material_for(api, s, 1, 7, 0, 0, 0, 0, scaled);
            check("material: a second ask is the same material", again == handle && sky_scale::copies.load() == 1);
            // The scaled and the unscaled material are two materials in one state: the layer's factor is part of the key,
            // not a detail of the file it happens to name.
            const auto unscaled = live_scene::material_for(api, s, 1);
            check("material: the scaled and the unscaled layer are two materials",
                  unscaled != handle && made[reinterpret_cast<unsigned long long>(unscaled)].path !=
                      made[reinterpret_cast<unsigned long long>(handle)].path);
        }
    }
    {   // ---- what must not change: an unreadable source, and the session cap -------------------------
        const std::wstring garbage = wdir + L"/live_2.dds";
        live_scene::write_whole(garbage, std::vector<unsigned char>(200, 'x'));
        live_capture::MaterialConstants scaled;
        scaled.albedo_scale = 0.5f;
        const std::wstring landed_source = wdir + L"/live_1.dds";   // written by the section above
        {   // a layer whose file has not landed yet: grey, no copy attempt, refreshed once it lands
            const std::wstring missing = wdir + L"/live_4.dds";
            live_scene::State pending;
            pending.texture_paths = {missing};
            pending.landed = {0};
            const auto unlanded_before = sky_scale::refused.load();
            const auto grey = live_scene::material_for(api, pending, 1, 7, 0, 0, 0, 0, scaled);
            check("late: an unlanded layer is grey and no copy is attempted",
                  grey && made[reinterpret_cast<unsigned long long>(grey)].path.empty() &&
                  sky_scale::refused.load() == unlanded_before && pending.incomplete.size() == 1);
            // ... and when the layer lands, the grey material is replaced, under its own hash, by the copy (T1's swap).
            const unsigned long long grey_hash = grey ? made[reinterpret_cast<unsigned long long>(grey)].hash : 0;
            pending.texture_paths = {landed_source};   // what add_textures records when the writer finishes the file
            pending.landed = {1};
            live_scene::refresh_incomplete_materials(api, pending);
            bool swapped = false;
            for (const auto& [handle, m] : made)
                if (m.hash == grey_hash && m.path.size() > 13 && m.path.compare(m.path.size() - 13, 13, L"sky_1_500.dds") == 0)
                    swapped = true;
            check("late: the landed layer is swapped in as the copy under the same hash", swapped);
        }
        live_scene::State s;
        s.texture_paths = {garbage}; s.landed = {1};
        const auto refused_before = sky_scale::refused.load();
        const auto handle = live_scene::material_for(api, s, 1, 7, 0, 0, 0, 0, scaled);
        check("fallback: an unreadable layer keeps today's texture",
              handle && made[reinterpret_cast<unsigned long long>(handle)].path == garbage);
        check("fallback: and is counted", sky_scale::refused.load() == refused_before + 1);

        terrain_bake::Image im; im.w = 2; im.h = 2;
        for (int i = 0; i < 4; ++i) { im.rgba.push_back(0.2f); im.rgba.push_back(0.2f); im.rgba.push_back(0.2f); im.rgba.push_back(1.f); }
        const std::wstring source = wdir + L"/live_3.dds";
        live_scene::write_whole(source, terrain_bake::dds_bytes(im, false, false));
        live_scene::State capped;
        capped.texture_paths = {source}; capped.landed = {1};
        const float factors[] = {0.5f, 0.75f, 2.f, 3.f, 4.f, 5.f, 6.f, 7.f, 8.f, 9.f};
        const auto cap_refused = sky_scale::refused.load();
        unsigned named = 0, kept = 0;
        for (const float f : factors) {
            live_capture::MaterialConstants c;
            c.albedo_scale = f;
            const auto h = live_scene::material_for(api, capped, 1, 7, 0, 0, 0, 0, c);
            const std::wstring& p = made[reinterpret_cast<unsigned long long>(h)].path;
            if (p.find(L"sky_") != std::wstring::npos) ++named;
            else if (p == source) ++kept;
        }
        check("cap: at most kMaxCopies copies are written", named == sky_scale::kMaxCopies);
        check("cap: the rest keep today's texture", kept == sizeof factors / sizeof factors[0] - sky_scale::kMaxCopies);
        check("cap: the refusals are counted", sky_scale::refused.load() == cap_refused + kept);
    }
    std::printf("failures=%d\n", failures);
    return failures ? 1 : 0;
}
'''

def main():
    work = Path(tempfile.mkdtemp(prefix='sky-scale-'))
    (work / 'harness.cpp').write_text(HARNESS)
    cmd = ['g++', '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
           '-Wall', '-Wextra', '-Werror', '-DREMIX_WINAPI_NO_INCLUDE', '-DREMIX_WINAPI_NO_LIBRARY_LOADER',
           '-D_WIN64=1', '-D__stdcall=', '-D__declspec(x)=', '-isystem', str(VENDOR), '-I', str(C),
           str(work / 'harness.cpp'), '-o', str(work / 'harness')]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(json.dumps({'passed': False, 'error': 'compile failed:\n' + r.stderr[-2500:]}))
        return 1
    run = subprocess.run([str(work / 'harness'), str(work)], capture_output=True, text=True, env=dict(os.environ))
    ok = run.returncode == 0
    print(json.dumps({'passed': ok, 'output': (run.stdout + run.stderr)[-3000:]}))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
