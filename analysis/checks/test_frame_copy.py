#!/usr/bin/env python3
"""Gate: frame_copy.h preserves the old readback conversion, including padding and opaque alpha.

Optional --benchmark compares the production helper to the old loop at 2880x1800; timings are not assertions.
"""
import json
import subprocess
import sys
from pathlib import Path

C = Path(__file__).resolve().parent
OUT = C.parent / 'runtime' / 'frame-copy'
HARNESS = r'''
#include "frame_copy.h"
#include <algorithm>
#include <cassert>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <vector>

// The old Remix readback loop, independent of the SIMD implementation.
#if defined(__GNUC__)
__attribute__((noinline))
#endif
void reference(const unsigned char* src, std::ptrdiff_t pitch, unsigned char* dst,
               std::size_t width, std::size_t height, bool swap) {
    for (std::size_t y = 0; y < height; ++y) {
        const unsigned char* s = src + static_cast<std::ptrdiff_t>(y) * pitch;
        unsigned char* d = dst + y * width * 4;
        for (std::size_t x = 0; x < width; ++x, s += 4, d += 4) {
            d[0] = swap ? s[2] : s[0]; d[1] = s[1]; d[2] = swap ? s[0] : s[2]; d[3] = 255;
        }
    }
}

void checks() {
    // All SIMD tail lengths; odd row pitches and unaligned source/destination; source alpha must not survive.
    for (std::size_t w = 0; w <= 65; ++w) for (std::size_t h : {0u, 1u, 3u})
    for (std::size_t padding : {0u, 1u, 13u}) for (std::size_t offset = 0; offset < 16; ++offset)
    for (bool swap : {false, true}) for (bool reverse : {false, true}) {
        const std::size_t pitch = w * 4 + padding;
        std::vector<unsigned char> src(pitch * h + offset + 32, 0xAB);
        for (std::size_t i = 0; i < src.size(); ++i) src[i] = static_cast<unsigned char>(i * 37 + i / 11);
        const auto before = src;
        std::vector<unsigned char> got(w * h * 4 + offset + 32, 0xAB), want = got;
        const auto* start = src.data() + offset + (reverse && h ? (h - 1) * pitch : 0);
        const auto step = reverse ? -static_cast<std::ptrdiff_t>(pitch) : static_cast<std::ptrdiff_t>(pitch);
        reference(start, step, want.data() + offset, w, h, swap);
        frame_copy::bgra(start, step, got.data() + offset, w, h, swap);
        assert(got == want && src == before);
    }
    // Hand-computed channel and alpha checks, covering SIMD plus its tail.
    const unsigned char s[] = {1, 2, 3, 0, 4, 5, 6, 19, 7, 8, 9, 255, 10, 11, 12, 1, 13, 14, 15, 2};
    unsigned char d[20]{};
    frame_copy::bgra(s, sizeof s, d, 5, 1, true);
    const unsigned char rgba[] = {3, 2, 1, 255, 6, 5, 4, 255, 9, 8, 7, 255, 12, 11, 10, 255, 15, 14, 13, 255};
    assert(std::memcmp(d, rgba, sizeof d) == 0);
    frame_copy::bgra(s, sizeof s, d, 5, 1, false);
    assert(d[0] == 1 && d[2] == 3 && d[3] == 255 && d[16] == 13 && d[18] == 15 && d[19] == 255);
    // Neither implementation may touch even a pointer for empty images.
    frame_copy::bgra(nullptr, 0, nullptr, 0, 4, true);
    frame_copy::bgra(nullptr, 0, nullptr, 4, 0, false);
}

volatile unsigned checksum = 0;
void benchmark() {
    const std::size_t w = 2880, h = 1800, pitch = w * 4 + 64;
    std::vector<unsigned char> src(pitch * h, 37), dst(w * h * 4);
    for (bool swap : {false, true}) {
        double med[2]{};
        for (unsigned impl = 0; impl < 2; ++impl) {
            const auto fn = impl ? frame_copy::bgra : reference;
            std::vector<double> times;
            for (int sample = 0; sample < 9; ++sample) {
                const auto start = std::chrono::steady_clock::now();
                for (int n = 0; n < 12; ++n) {
                    fn(src.data(), pitch, dst.data(), w, h, swap);
                    checksum += dst[static_cast<std::size_t>(n)];
                }
                const auto stop = std::chrono::steady_clock::now();
                times.push_back(std::chrono::duration<double, std::milli>(stop - start).count() / 12);
            }
            std::sort(times.begin(), times.end());
            med[impl] = times[times.size() / 2];
        }
        std::printf("%s 2880x1800: old=%.3f ms SIMD=%.3f ms ratio=%.2fx\n", swap ? "RGBA" : "BGRA",
                    med[0], med[1], med[0] / med[1]);
    }
}
int main(int argc, char**) {
    checks();
    std::puts("byte-exact: widths 0..65, all alignments/tails, padded/reversed rows, opaque alpha, empty images");
    if (argc > 1) benchmark();
}
'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    src = OUT / 'harness.cpp'
    src.write_text(HARNESS)
    try:
        common = ['-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(C)]
        for label, compiler, flags, suffix in (
                ('native-asan', 'g++', ['-fsanitize=address,undefined'], ''),
                ('windows-cross', 'x86_64-w64-mingw32-g++', ['-static'], '.exe')):
            exe = OUT / (label + suffix)
            p = subprocess.run([compiler, *common, *flags, str(src), '-o', str(exe)], capture_output=True, text=True)
            assert p.returncode == 0, f'{label} compile: {p.stderr[-2000:]}'
            if label == 'native-asan':
                p = subprocess.run([str(exe)], capture_output=True, text=True)
                assert p.returncode == 0, f'{label}: {(p.stdout + p.stderr)[-2000:]}'
                checks = p.stdout.strip()
        live = (C / 'remix_live.cpp').read_text()
        assert '#include "frame_copy.h"' in live and 'frame_copy::bgra(' in live, 'production readback must use the tested copy'
        result = {'passed': True, 'checks': checks, 'windows_cross_build': True}
        if '--benchmark' in sys.argv:
            exe = OUT / 'benchmark'
            p = subprocess.run(['g++', *common, str(src), '-o', str(exe)], capture_output=True, text=True)
            assert p.returncode == 0, p.stderr[-2000:]
            p = subprocess.run([str(exe), 'benchmark'], capture_output=True, text=True)
            assert p.returncode == 0, (p.stdout + p.stderr)[-2000:]
            result['benchmark'] = p.stdout.strip().splitlines()[1:]
        print(json.dumps(result, indent=2))
        return 0
    except (AssertionError, OSError) as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
