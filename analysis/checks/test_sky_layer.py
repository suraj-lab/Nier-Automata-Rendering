#!/usr/bin/env python3
"""Frozen W1.3 gate, part 1: the sky shader's per-layer inputs, read by RDEF name -> (bind slot, byte offset).

Why a unit gate: the three inputs W1.3 folds into the sky material (`g_IntensityParam.y`, `g_AlbedoParam`,
`g_MeshColor`) live in constant buffers whose *slots* are not knowable from the shader's declaration alone. The sky
pixel shader (`runtime/w1-disasm/sky_ps.dxbc`, FNV-1a 64 `0x33856d1d3ba64bb3`, the same in camp, desert and pond)
declares `PSParamBuffer1` **twice** (64 bytes at bind 1, 128 at bind 2) and the captures bind neither at its declared
size (112 bytes at slot 1), so a "widest binding" or "table order" guess reads the wrong bytes. Two such guesses
already produced wrong values on this plan (`PLAN_2026-11-13.md` L9, corrected by `W1_SKY_CB_VALUES.md`).

This gate pins `checks/sky_layer.h` against:
  - the real sky shader bytes in the repository (not a fixture written for the header);
  - the (slot, register) pairs `checks/sky_cb_dump.py` measured on the three packed captures, passed in from
    `runtime/sky-cb-dump-gate/{camp,desert,pond}.json` (a second implementation, so the header is not its own oracle);
  - the ambiguity the real shader creates, and the malformed inputs that must be refused instead of guessed.

Usage: test_sky_layer.py   (native g++, CPU only, no Wine, no GPU)
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
SKY = A / 'runtime/w1-disasm/sky_ps.dxbc'
EVIDENCE = [A / 'runtime/sky-cb-dump-gate' / f'{area}.json' for area in ('camp', 'desert', 'pond')]
NAMES = ('g_IntensityParam', 'g_AlbedoParam', 'g_MeshColor', 'g_BaseBoolParam')

SRC = r'''
#include "sky_layer.h"
#include <array>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

static int failures = 0;
static void check(bool ok, const char* what, const char* detail = "") {
    if (ok) { std::printf("ok   %s\n", what); return; }
    ++failures;
    std::printf("FAIL %s %s\n", what, detail);
}

static std::vector<unsigned char> read_file(const char* path) {
    std::vector<unsigned char> out;
    FILE* f = std::fopen(path, "rb");
    if (!f) return out;
    unsigned char buf[65536];
    std::size_t n;
    while ((n = std::fread(buf, 1, sizeof buf, f)) > 0) out.insert(out.end(), buf, buf + n);
    std::fclose(f);
    return out;
}
// "1:112,2:128" -> bound sizes per slot
static std::array<std::uint32_t, 16> parse_bound(const char* text) {
    std::array<std::uint32_t, 16> bound{};
    unsigned slot = 0, bytes = 0;
    const char* p = text;
    while (*p) {
        if (std::sscanf(p, "%u:%u", &slot, &bytes) != 2) break;
        if (slot < 16) bound[slot] = bytes;
        p = std::strchr(p, ',');
        if (!p) break;
        ++p;
    }
    return bound;
}
static std::uint32_t slot_of(const std::vector<sky_layer::Decl>& decls, const std::vector<std::uint32_t>& placed,
                             const char* name, std::uint32_t* offset = nullptr) {
    for (std::size_t i = 0; i < decls.size(); ++i)
        if (decls[i].name == name) { if (offset) *offset = decls[i].offset; return placed[i]; }
    return sky_layer::kUnbound;
}

int main(int argc, char** argv) {
    // argv: 1 = sky_ps.dxbc, 2 = bound sizes ("slot:bytes,..."), then one "name=slot,reg" per expected member.
    if (argc < 3) { std::printf("usage: t <dxbc> <bound> [name=slot,reg ...]\n"); return 2; }
    const std::vector<unsigned char> dxbc = read_file(argv[1]);
    check(!dxbc.empty(), "the repository's sky shader is readable", argv[1]);
    check(sky_layer::fnv1a64(dxbc) == sky_layer::kSkyPsCode,
          "the fixture is the sky shader (FNV-1a 64 of its bytecode == 0x33856d1d3ba64bb3, as in the live proxy log)");

    std::vector<sky_layer::Decl> decls;
    check(sky_layer::members(dxbc, decls), "RDEF parsed");
    int param_buffers = 0;   // distinct (name, size) pairs: PSParamBuffer1 appears twice, at 64 and at 128 bytes
    std::vector<std::pair<std::string, std::uint32_t>> seen_buffers;
    for (const auto& d : decls) {
        const std::pair<std::string, std::uint32_t> key{d.buffer, d.buffer_size};
        bool known = false;
        for (const auto& k : seen_buffers) known |= k == key;
        if (!known) seen_buffers.push_back(key);
    }
    for (const auto& k : seen_buffers) if (k.first == "PSParamBuffer1") ++param_buffers;
    check(param_buffers == 2, "PSParamBuffer1 is declared twice (the duplicate name the slot resolution must survive)");
    bool saw_64 = false, saw_128 = false;
    for (const auto& d : decls)
        if (d.buffer == "PSParamBuffer1") { saw_64 |= d.buffer_size == 64; saw_128 |= d.buffer_size == 128; }
    check(saw_64 && saw_128, "the two declarations are 64 and 128 bytes: a name alone names no slot");

    const std::array<std::uint32_t, 16> bound = parse_bound(argv[2]);
    std::vector<std::uint32_t> placed;
    check(sky_layer::place(decls, bound, placed), "the capture's bindings resolve (no ambiguity)");
    check(placed.size() == decls.size(), "one placement per declaration");
    for (int i = 3; i < argc; ++i) {   // measured (slot, register) from the captures, register * 16 = byte offset
        char name[64] = {};
        unsigned slot = 0, reg = 0;
        if (std::sscanf(argv[i], "%63[^=]=%u,%u", name, &slot, &reg) != 3) continue;
        std::uint32_t offset = 0;
        const std::uint32_t got_slot = slot_of(decls, placed, name, &offset);
        char detail[160];
        std::snprintf(detail, sizeof detail, "%s: header slot %u offset %u, capture says slot %u offset %u", name,
                      got_slot, offset, slot, reg * 16);
        check(got_slot == slot && offset == reg * 16, "member placed where the capture measured it", detail);
    }

    // A shader whose declared size fits two bound buffers must be refused, not resolved by table order.
    {
        std::array<std::uint32_t, 16> both{}; both[1] = 128; both[2] = 128;
        std::vector<std::uint32_t> out;
        check(!sky_layer::place(decls, both, out), "two exact-size binds for the 128-byte declaration are refused");
    }
    {   // a declared size larger than its only bind is refused too
        std::array<std::uint32_t, 16> small{}; small[1] = 48; small[2] = 128;
        std::vector<std::uint32_t> out;
        check(!sky_layer::place(decls, small, out), "a 64-byte declaration with only a 48-byte bind is refused");
    }
    {   // ... while exact matches win outright
        std::array<std::uint32_t, 16> exact{}; exact[1] = 64; exact[2] = 128;
        std::vector<std::uint32_t> out;
        const bool ok = sky_layer::place(decls, exact, out);
        std::uint32_t offset = 0;
        check(ok && slot_of(decls, out, "g_IntensityParam", &offset) == 1 && offset == 16,
              "exact declared sizes resolve to their own enables (64 -> slot 1)");
    }

    // Reading the values: synthetic buffers shaped like the captures (slot 1 binds 112 bytes, slot 4 16).
    std::vector<unsigned char> b1(112, 0), b4(16, 0);
    const float intensity[4] = {0.f, 6.f, 0.f, 0.f}, mesh[4] = {1.f, 1.f, 1.f, 1.f};
    float albedo[4] = {1.f, 0.713f, 0.55f, 1.f};
    std::memcpy(b1.data() + 16, intensity, 16);       // g_IntensityParam.y = 6
    std::memcpy(b1.data() + 48, albedo, 16);          // g_AlbedoParam
    std::memcpy(b4.data(), mesh, 16);                 // g_MeshColor
    std::array<sky_layer::Binding, 16> bindings{};
    bindings[1] = {static_cast<std::uint32_t>(b1.size()), b1.data()};
    bindings[4] = {static_cast<std::uint32_t>(b4.size()), b4.data()};
    sky_layer::Inputs in;
    check(sky_layer::read(decls, placed, bindings, in), "all three members read from the bound buffers");
    check(in.use_albedo, "g_AlbedoParam.w > 0: the shader uses the constant, not t0");
    check(in.intensity == 6.f && in.mesh[0] == 1.f, "intensity 6 and mesh 1 read back");
    float colour[3] = {0, 0, 0};
    const bool constant = sky_layer::constant_colour(in, colour);
    char detail[160];
    std::snprintf(detail, sizeof detail, "got %.4f,%.4f,%.4f", colour[0], colour[1], colour[2]);
    check(constant && colour[0] == 6.f && std::abs(colour[1] - 4.278f) < 1e-4f && std::abs(colour[2] - 3.3f) < 1e-4f,
          "constant colour = albedo * intensity * mesh (1,0.713,0.55) * 6", detail);
    {   // w == 0: the base is t0 * factor, and Remix's albedoConstant replaces a texture instead of multiplying it
        std::memcpy(b1.data() + 60, &(albedo[3] = 0.f), 4);   // g_AlbedoParam.w = 0
        sky_layer::Inputs t;
        check(sky_layer::read(decls, placed, bindings, t) && !t.use_albedo, "g_AlbedoParam.w == 0: t0 is used");
        check(!sky_layer::constant_colour(t, colour), "a textured layer has no constant colour to send");
        albedo[3] = 1.f;
        std::memcpy(b1.data() + 48, albedo, 16);
    }
    {   // mesh colour other than 1 still folds in
        const float grey[4] = {0.5f, 0.5f, 0.5f, 1.f};
        std::memcpy(b4.data(), grey, 16);
        sky_layer::Inputs m;
        float c[3] = {0, 0, 0};
        check(sky_layer::read(decls, placed, bindings, m) && sky_layer::constant_colour(m, c) &&
              std::abs(c[0] - 3.f) < 1e-5f, "g_MeshColor multiplies the colour too (1 * 6 * 0.5 = 3)");
        std::memcpy(b4.data(), mesh, 16);
    }
    {   // an unbound member: nothing to read, so no fold (never a zero-filled guess)
        std::array<sky_layer::Binding, 16> partial = bindings;
        partial[4] = {};
        sky_layer::Inputs p;
        check(!sky_layer::read(decls, placed, partial, p), "an unbound g_MeshColor means no fold, not a guess");
    }
    {   // a binding shorter than the member it must hold is refused, not read past its end
        std::vector<unsigned char> tiny(20, 0);
        std::array<sky_layer::Binding, 16> short_bind = bindings;
        short_bind[1] = {static_cast<std::uint32_t>(tiny.size()), tiny.data()};
        sky_layer::Inputs s;
        check(!sky_layer::read(decls, placed, short_bind, s), "a bind shorter than the member is refused");
    }
    {   // malformed blobs: refused, no crash (the gate runs under ASan/UBSan)
        std::vector<std::vector<unsigned char>> bad;
        bad.push_back({});
        bad.push_back({'n', 'o', 't', 'a', 's', 'h', 'a', 'd', 'e', 'r'});
        bad.push_back(std::vector<unsigned char>(dxbc.begin(), dxbc.begin() + 40));
        bad.push_back(dxbc);
        bad.back().resize(60);   // a container that points past its own end
        int refused = 0;
        for (const auto& blob : bad) {
            std::vector<sky_layer::Decl> d;
            if (!sky_layer::members(blob, d)) ++refused;
        }
        check(refused == static_cast<int>(bad.size()), "malformed blobs are refused, not parsed");
    }
    std::printf("failures=%d\n", failures);
    return failures ? 1 : 0;
}
'''


def evidence_arguments():
    """(bound sizes, [name=slot,reg ...]) as measured by checks/sky_cb_dump.py on the three packed captures. All three
    must agree: they use one shader, so a header that resolves it differently per area would be reading the capture,
    not the declaration."""
    args, bound_text = [], None
    for path in EVIDENCE:
        assert path.is_file(), f'missing evidence {path}; rerun checks/sky_cb_dump.py'
        data = json.loads(path.read_text())
        bound = sorted((c['slot'], c['bound']) for c in data['cbuffers'] if c['slot'] is not None and c['bound'])
        text = ','.join(f'{slot}:{bytes_}' for slot, bytes_ in bound)
        if bound_text is None:
            bound_text = text
        else:
            assert text == bound_text, f'{path.name} binds different sizes: {text} vs {bound_text}'
        registers = data['draws'][0]['registers']
        names = [f'{n}={registers[n][0]},{registers[n][1]}' for n in NAMES if n in registers]
        if not args:
            args = names
        else:
            assert names == args, f'{path.name} resolves the same members differently: {names} vs {args}'
    return bound_text, args


def main():
    bound_text, names = evidence_arguments()
    work = Path(tempfile.mkdtemp(prefix='sky-layer-'))
    (work / 't.cpp').write_text(SRC)
    subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-I',
                    str(C), str(work / 't.cpp'), '-o', str(work / 't')], check=True)
    r = subprocess.run([str(work / 't'), str(SKY), bound_text, *names], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr.strip()[-2000:])
    return 0 if r.returncode == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
