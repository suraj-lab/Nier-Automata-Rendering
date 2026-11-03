#!/usr/bin/env python3
"""Gate: normal_octahedral.h and mask_channels.h are faster AND produce byte-identical output to the frozen reference.

Why: the Remix worker converts every new normal / mask texture inline (remix_live.cpp, texture loop before `live
update`), and that cost is the visible 0.8-1.7 s freezes in frametime1 (evidence/remix-current/2026-11-01/
frametime1-attribution.md). The per-texel code re-decodes each BC block's endpoints for all 16 texels, and a BC1 block
has only 4 distinct normals, so a per-block decode can do far less work with identical results.

The reference is the shipped code, frozen under fixtures/texture-convert-reference/ with renamed namespaces and pinned
by SHA-256 below. Contract checked here, for every source format, size (incl. partial edge blocks and 1x1 mips), flip,
channel, invert and floor:
  * the return value equals the reference's;
  * when true, every one of the w*h output texels equals the reference's, byte for byte;
  * never a write past the w*h output (64 sentinel bytes after it stay 0xAB), true or false.
Speed floors at -O2 on one 1024x1024 level, best of 7: BC1 normal >= 3x, BC1 mask >= 3x, BC3 mask >= 2.5x, BC5 and
uncompressed normals and RGBA/BGRA masks no slower than 0.9x. Public function names and signatures stay as they are.
Prints one JSON line; exit 0 only when passed.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
REF = C / 'fixtures' / 'texture-convert-reference'
PINNED = {
    'ref_normal_octahedral.h': '70e61e4e4cd7995d46601ce8782ee0b6dc93d5678089ac25370e004e2aea796b',
    'ref_mask_channels.h': '490cf1d0f3e7e228b098f122424eaa4d92247ab3cf401ab809ed9be79dc38d2c',
}

HARNESS = r'''
#include "normal_octahedral.h"
#include "mask_channels.h"
#include "ref_normal_octahedral.h"
#include "ref_mask_channels.h"
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

static unsigned long long checked = 0, failures = 0;
static char first_failure[512] = "";
static void fail(const char* what) {
    if (!failures++) std::snprintf(first_failure, sizeof first_failure, "%s", what);
}

static std::mt19937 rng(20261103);
static unsigned char rb() { return static_cast<unsigned char>(rng()); }

// BC colour block flavours. 0 raw random, 1 four-colour (c0 > c1), 2 three-colour without index 3,
// 3 three-colour with index 3 only on texels outside the level (padding), 4 three-colour with index 3 inside.
static void colour_block(unsigned char* b, int mode, unsigned bx, unsigned by, unsigned w, unsigned h) {
    for (int i = 0; i < 8; ++i) b[i] = rb();
    if (mode == 0) return;
    unsigned c0 = b[0] | (b[1] << 8), c1 = b[2] | (b[3] << 8);
    if (mode == 1) { if (c0 == c1) c1 = c0 ? c0 - 1 : 1; if (c0 < c1) std::swap(c0, c1); if (c0 == c1) c0 = c1 + 1; }
    else { if (c0 > c1) std::swap(c0, c1); }
    b[0] = c0 & 255; b[1] = c0 >> 8; b[2] = c1 & 255; b[3] = c1 >> 8;
    unsigned bits = b[4] | (b[5] << 8) | (b[6] << 16) | (static_cast<unsigned>(b[7]) << 24);
    if (mode >= 2) {
        bool placed = false;
        for (unsigned t = 0; t < 16; ++t) {
            const unsigned px = bx * 4 + t % 4, py = by * 4 + t / 4;
            const bool inside = px < w && py < h;
            unsigned idx = (bits >> (2 * t)) & 3;
            if (idx == 3 && (mode == 2 || (mode == 3 && inside) || (mode == 4 && inside && placed))) idx = rng() % 3;
            if (mode == 3 && !inside) { idx = 3; }
            if (mode == 4 && inside && !placed) { idx = 3; placed = true; }
            bits = (bits & ~(3u << (2 * t))) | (idx << (2 * t));
        }
    }
    for (int i = 0; i < 4; ++i) b[4 + i] = (bits >> (8 * i)) & 255;
}

static std::vector<unsigned char> level(int fmt /*0 bc1 1 bc5 2 bc3 3 uncompressed*/, unsigned w, unsigned h, int mode) {
    const unsigned bw = (w + 3) / 4, bh = (h + 3) / 4;
    std::vector<unsigned char> v;
    if (fmt == 3) { v.resize(static_cast<std::size_t>(w) * h * 4); for (auto& c : v) c = rb(); return v; }
    const unsigned bytes = fmt == 0 ? 8 : 16;
    v.resize(static_cast<std::size_t>(bw) * bh * bytes);
    for (unsigned by = 0; by < bh; ++by) for (unsigned bx = 0; bx < bw; ++bx) {
        unsigned char* b = v.data() + (static_cast<std::size_t>(by) * bw + bx) * bytes;
        if (fmt == 0) colour_block(b, mode, bx, by, w, h);
        else if (fmt == 1) { for (unsigned i = 0; i < 16; ++i) b[i] = rb(); if (mode == 1) { b[0] = 0x80; b[8] = 0x7f; } }
        else { for (unsigned i = 0; i < 8; ++i) b[i] = rb(); colour_block(b + 8, mode % 2 ? 0 : 4, bx, by, w, h); }
    }
    return v;
}

static const unsigned SIZES[][2] = {{1,1},{2,2},{1,4},{4,1},{3,5},{4,4},{5,4},{6,5},{7,9},{8,8},{13,3},{64,32},{33,67},{128,128}};

static void check_normals() {
    using NS = normal_octahedral::Source; using RS = ref_normal_octahedral::Source;
    const NS ns[] = {NS::Bc1, NS::Bc5Unorm, NS::Bc5Snorm, NS::Rgba8, NS::Bgra8};
    const RS rs[] = {RS::Bc1, RS::Bc5Unorm, RS::Bc5Snorm, RS::Rgba8, RS::Bgra8};
    const int fmts[] = {0, 1, 1, 3, 3};
    for (int s = 0; s < 5; ++s) for (const auto& sz : SIZES) for (int mode = 0; mode < 5; ++mode)
    for (int rep = 0; rep < 3; ++rep) for (bool flip : {false, true}) for (int trim : {0, 1}) {
        const unsigned w = sz[0], h = sz[1];
        auto in = level(fmts[s], w, h, mode);
        const std::size_t n = static_cast<std::size_t>(w) * h * 4;
        std::vector<unsigned char> want(n + 64, 0xAB), got(n + 64, 0xAB);
        const std::size_t bytes = trim ? in.size() - 1 : in.size();
        const bool r = ref_normal_octahedral::convert_level(rs[s], in.data(), bytes, w, h, flip, want.data());
        const bool c = normal_octahedral::convert_level(ns[s], in.data(), bytes, w, h, flip, got.data());
        ++checked;
        char what[256];
        std::snprintf(what, sizeof what, "convert_level source=%d %ux%u mode=%d flip=%d trim=%d: ", s, w, h, mode, flip, trim);
        if (r != c) { std::strcat(what, r ? "reference true, candidate false" : "reference false, candidate true"); fail(what); continue; }
        if (r && std::memcmp(want.data(), got.data(), n)) {
            std::size_t i = 0; while (want[i] == got[i]) ++i;
            char more[96]; std::snprintf(more, sizeof more, "byte %zu differs (want %u got %u)", i, want[i], got[i]);
            std::strcat(what, more); fail(what); continue;
        }
        for (std::size_t i = n; i < n + 64; ++i) if (got[i] != 0xAB) { std::strcat(what, "wrote past w*h*4"); fail(what); break; }
    }
    // Null pointers are refused like the reference.
    unsigned char o[4];
    ++checked;
    if (normal_octahedral::convert_level(NS::Rgba8, nullptr, 4, 1, 1, false, o)) fail("convert_level accepted null input");
    const unsigned char px[4] = {128, 128, 0, 0};
    if (normal_octahedral::convert_level(NS::Rgba8, px, 4, 1, 1, false, nullptr)) fail("convert_level accepted null output");
}

static void check_masks() {
    using NS = mask_channels::Source; using RS = ref_mask_channels::Source;
    const NS ns[] = {NS::Bc1, NS::Bc3, NS::Rgba8, NS::Bgra8};
    const RS rs[] = {RS::Bc1, RS::Bc3, RS::Rgba8, RS::Bgra8};
    const int fmts[] = {0, 2, 3, 3};
    unsigned zero_sizes[][2] = {{0, 4}, {4, 0}};
    for (int s = 0; s < 4; ++s) for (const auto& sz : SIZES) for (int mode = 0; mode < 5; ++mode)
    for (unsigned channel = 0; channel <= 4; ++channel) for (bool invert : {false, true})
    for (unsigned floor : {0u, 38u, 255u}) for (int trim : {0, 1}) {
        const unsigned w = sz[0], h = sz[1];
        auto in = level(fmts[s], w, h, mode);
        const std::size_t n = static_cast<std::size_t>(w) * h;
        std::vector<unsigned char> want(n + 64, 0xAB), got(n + 64, 0xAB);
        const std::size_t bytes = trim ? in.size() - 1 : in.size();
        const unsigned char f = static_cast<unsigned char>(floor);
        const bool r = ref_mask_channels::extract_level(rs[s], in.data(), bytes, w, h, channel, invert, want.data(), f);
        const bool c = mask_channels::extract_level(ns[s], in.data(), bytes, w, h, channel, invert, got.data(), f);
        ++checked;
        char what[256];
        std::snprintf(what, sizeof what, "extract_level source=%d %ux%u mode=%d channel=%u invert=%d floor=%u trim=%d: ",
                      s, w, h, mode, channel, invert, floor, trim);
        if (r != c) { std::strcat(what, r ? "reference true, candidate false" : "reference false, candidate true"); fail(what); continue; }
        if (r && std::memcmp(want.data(), got.data(), n)) {
            std::size_t i = 0; while (want[i] == got[i]) ++i;
            char more[96]; std::snprintf(more, sizeof more, "texel %zu differs (want %u got %u)", i, want[i], got[i]);
            std::strcat(what, more); fail(what); continue;
        }
        for (std::size_t i = n; i < n + 64; ++i) if (got[i] != 0xAB) { std::strcat(what, "wrote past w*h"); fail(what); break; }
    }
    for (auto& z : zero_sizes) {
        unsigned char b[16] = {}, o[4];
        ++checked;
        if (mask_channels::extract_level(NS::Bc1, b, 16, z[0], z[1], 0, false, o)) fail("extract_level accepted a zero size");
    }
}

template <class F> static double best_ms(F f) {
    double best = 1e30;
    for (int i = 0; i < 7; ++i) {
        const auto t0 = std::chrono::steady_clock::now();
        f();
        best = std::min(best, std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count());
    }
    return best;
}

int main() {
    check_normals();
    check_masks();
    const unsigned W = 1024;
    auto bc1 = level(0, W, W, 1), bc5 = level(1, W, W, 0), bc3 = level(2, W, W, 0), raw = level(3, W, W, 0);
    std::vector<unsigned char> o4(static_cast<std::size_t>(W) * W * 4), o1(static_cast<std::size_t>(W) * W);
    volatile unsigned sink = 0;
    using NN = normal_octahedral::Source; using RN = ref_normal_octahedral::Source;
    using NM = mask_channels::Source; using RM = ref_mask_channels::Source;
    struct Row { const char* name; double ref, cand, floor; };
    Row rows[] = {
        {"normal_bc1", best_ms([&] { sink = sink + ref_normal_octahedral::convert_level(RN::Bc1, bc1.data(), bc1.size(), W, W, false, o4.data()); }),
                       best_ms([&] { sink = sink + normal_octahedral::convert_level(NN::Bc1, bc1.data(), bc1.size(), W, W, false, o4.data()); }), 3.0},
        {"normal_bc5", best_ms([&] { sink = sink + ref_normal_octahedral::convert_level(RN::Bc5Unorm, bc5.data(), bc5.size(), W, W, false, o4.data()); }),
                       best_ms([&] { sink = sink + normal_octahedral::convert_level(NN::Bc5Unorm, bc5.data(), bc5.size(), W, W, false, o4.data()); }), 0.9},
        {"normal_rgba8", best_ms([&] { sink = sink + ref_normal_octahedral::convert_level(RN::Rgba8, raw.data(), raw.size(), W, W, false, o4.data()); }),
                         best_ms([&] { sink = sink + normal_octahedral::convert_level(NN::Rgba8, raw.data(), raw.size(), W, W, false, o4.data()); }), 0.9},
        {"mask_bc1", best_ms([&] { sink = sink + ref_mask_channels::extract_level(RM::Bc1, bc1.data(), bc1.size(), W, W, 1, true, o1.data(), 38); }),
                     best_ms([&] { sink = sink + mask_channels::extract_level(NM::Bc1, bc1.data(), bc1.size(), W, W, 1, true, o1.data(), 38); }), 3.0},
        {"mask_bc3", best_ms([&] { sink = sink + ref_mask_channels::extract_level(RM::Bc3, bc3.data(), bc3.size(), W, W, 0, false, o1.data(), 0); }),
                     best_ms([&] { sink = sink + mask_channels::extract_level(NM::Bc3, bc3.data(), bc3.size(), W, W, 0, false, o1.data(), 0); }), 2.5},
        {"mask_bgra8", best_ms([&] { sink = sink + ref_mask_channels::extract_level(RM::Bgra8, raw.data(), raw.size(), W, W, 0, true, o1.data(), 38); }),
                       best_ms([&] { sink = sink + mask_channels::extract_level(NM::Bgra8, raw.data(), raw.size(), W, W, 0, true, o1.data(), 38); }), 0.9},
    };
    bool fast = true;
    std::printf("{\"checked\": %llu, \"failures\": %llu, \"first_failure\": \"%s\", \"speed\": {", checked, failures, first_failure);
    for (std::size_t i = 0; i < sizeof rows / sizeof rows[0]; ++i) {
        const double x = rows[i].ref / rows[i].cand;
        if (x < rows[i].floor) fast = false;
        std::printf("%s\"%s\": {\"ref_ms\": %.2f, \"cand_ms\": %.2f, \"speedup\": %.2f, \"floor\": %.1f}", i ? ", " : "",
                    rows[i].name, rows[i].ref, rows[i].cand, x, rows[i].floor);
    }
    std::printf("}, \"fast_enough\": %s}\n", fast ? "true" : "false");
    return failures || !fast ? 1 : 0;
}
'''


def result(passed, **kw):
    print(json.dumps({'passed': passed, **kw}))
    return 0 if passed else 1


def main():
    for name, digest in PINNED.items():
        got = hashlib.sha256((REF / name).read_bytes()).hexdigest()
        if got != digest:
            return result(False, error=f'frozen reference {name} changed (sha256 {got}); it must never be edited')
    with tempfile.TemporaryDirectory() as tmp:
        src, exe = Path(tmp) / 'gate.cpp', Path(tmp) / 'gate'
        src.write_text(HARNESS)
        flags = ['-std=c++17', '-Wall', '-Wextra', '-Werror', f'-I{C}', f'-I{REF}']
        build = subprocess.run(['g++', '-O2', *flags, str(src), '-o', str(exe)], capture_output=True, text=True)
        if build.returncode:
            return result(False, error='native -O2 build failed', compiler=build.stderr[-3000:])
        # The DLL is built with MinGW -O2 (build_menu_dll.py): the headers must compile there too.
        cross = subprocess.run(['x86_64-w64-mingw32-g++', '-O2', '-fsyntax-only', *flags, str(src)], capture_output=True, text=True)
        if cross.returncode:
            return result(False, error='MinGW -O2 compile failed', compiler=cross.stderr[-3000:])
        try:
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return result(False, error='harness timed out after 600 s')
        try:
            report = json.loads(run.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return result(False, error='harness crashed or printed no report', exit_code=run.returncode,
                          stdout=run.stdout[-1500:], stderr=run.stderr[-1500:])
    ok = run.returncode == 0 and report['failures'] == 0 and report['fast_enough']
    return result(ok, **report)


if __name__ == '__main__':
    sys.exit(main())
