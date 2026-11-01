#!/usr/bin/env python3
"""Gate: mask_channels.h extracts one channel (optionally inverted) from BC1, BC3, RGBA8 and BGRA8 levels.

Blocks are built here by hand from the D3D block-compression rules, so the expected texels are known exactly: BC1 in
4-colour and 3-colour+transparent modes, BC3 with the colour half always 4-colour and an 8-alpha BC4 block,
partial edge blocks (a 6x5 level), short input refused, and the roughness case (1 - gloss in G -> R).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include "mask_channels.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
using namespace mask_channels;

// 565 endpoints: pure red (0xF800) and pure green (0x07E0).
static void bc1(unsigned char* b, unsigned c0, unsigned c1, unsigned indices) {
    b[0] = c0 & 255; b[1] = c0 >> 8; b[2] = c1 & 255; b[3] = c1 >> 8;
    for (int i = 0; i < 4; ++i) b[4 + i] = (indices >> (8 * i)) & 255;
}

int main() {
    unsigned char out[64];
    // BC1, 4-colour mode (c0 > c1): red, green, 2/3 red + 1/3 green, 1/3 red + 2/3 green. Texels 0..3 use indices 0..3.
    unsigned char b[16];
    bc1(b, 0xF800, 0x07E0, 0b11100100);
    assert(extract_level(Source::Bc1, b, 8, 4, 4, 0, false, out));
    assert(out[0] == 255 && out[1] == 0 && out[2] == 170 && out[3] == 85);
    assert(extract_level(Source::Bc1, b, 8, 4, 4, 1, false, out));     // green channel
    assert(out[0] == 0 && out[1] == 255 && out[2] == 85 && out[3] == 170);
    assert(extract_level(Source::Bc1, b, 8, 4, 4, 1, true, out));      // roughness = 1 - gloss
    assert(out[0] == 255 && out[1] == 0 && out[2] == 170 && out[3] == 85);
    // BC1, 3-colour mode (c0 <= c1): index 2 = average, index 3 = transparent black.
    bc1(b, 0x07E0, 0xF800, 0b11100100);
    assert(extract_level(Source::Bc1, b, 8, 4, 4, 0, false, out));
    assert(out[0] == 0 && out[1] == 255 && out[2] == 128 && out[3] == 0);
    assert(extract_level(Source::Bc1, b, 8, 4, 4, 3, false, out));     // alpha
    assert(out[0] == 255 && out[3] == 0);
    // BC3: alpha block (a0 = 255 > a1 = 0, texel 0 index 0 -> 255, texel 1 index 1 -> 0, texel 2 index 2 -> 6/7*255)
    // then a colour block that is 4-colour even though c0 <= c1.
    std::memset(b, 0, 16);
    b[0] = 255; b[1] = 0;
    b[2] = (1 << 3) | (2 << 6);  // texel 0: index 0, texel 1: index 1, texel 2: index 2 (3-bit fields from bit 0)
    bc1(b + 8, 0x07E0, 0xF800, 0b11100100);
    assert(extract_level(Source::Bc3, b, 16, 4, 4, 3, false, out));
    assert(out[0] == 255 && out[1] == 0 && out[2] == 219);
    assert(extract_level(Source::Bc3, b, 16, 4, 4, 0, false, out));    // colour stays 4-colour in BC3
    assert(out[0] == 0 && out[1] == 255 && out[2] == 85 && out[3] == 170);
    // Partial edge blocks: a 6x5 level is 2x2 blocks; only real texels are written, row-major w = 6.
    std::vector<unsigned char> blocks(4 * 8);
    for (int k = 0; k < 4; ++k) bc1(blocks.data() + 8 * k, k % 2 ? 0x07E0 : 0xF800, 0x0000, 0);
    std::vector<unsigned char> level(6 * 5, 7);
    assert(extract_level(Source::Bc1, blocks.data(), blocks.size(), 6, 5, 0, false, level.data()));
    assert(level[0] == 255 && level[4] == 0 && level[4 * 6 + 0] == 255 && level[4 * 6 + 5] == 0);
    // Too short: refused.
    assert(!extract_level(Source::Bc1, blocks.data(), blocks.size() - 1, 6, 5, 0, false, level.data()));
    assert(!extract_level(Source::Bc1, b, 8, 4, 4, 4, false, out));    // no channel 4
    // RGBA8 / BGRA8: R is byte 0 / byte 2.
    const unsigned char px[8] = {10, 20, 30, 40, 50, 60, 70, 80};
    assert(extract_level(Source::Rgba8, px, 8, 2, 1, 0, false, out) && out[0] == 10 && out[1] == 50);
    assert(extract_level(Source::Bgra8, px, 8, 2, 1, 0, false, out) && out[0] == 30 && out[1] == 70);
    assert(extract_level(Source::Bgra8, px, 8, 2, 1, 1, true, out) && out[0] == 235 && out[1] == 195);
    // Roughness floor, applied after inversion: gloss 255 -> roughness 0 -> raised to the floor; others untouched.
    bc1(b, 0xF800, 0x07E0, 0b11100100);
    assert(extract_level(Source::Bc1, b, 8, 4, 4, 1, true, out, 38));
    assert(out[0] == 255 && out[1] == 38 && out[2] == 170 && out[3] == 85);
    assert(extract_level(Source::Rgba8, px, 8, 2, 1, 3, true, out, 200) && out[0] == 215 && out[1] == 200);
    std::puts("BC1 4/3-colour, BC3 alpha + forced 4-colour, inversion, edge blocks, short input, RGBA8/BGRA8, floor");
    return 0;
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='mask-channels-'))
    (work / 't.cpp').write_text(HARNESS)
    build = subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                            '-I', str(C), str(work / 't.cpp'), '-o', str(work / 't')], capture_output=True, text=True)
    if build.returncode:
        print(json.dumps({'passed': False, 'error': 'compile:\n' + build.stderr[-1500:]}))
        return 1
    run = subprocess.run([str(work / 't')], capture_output=True, text=True)
    if run.returncode:
        print(json.dumps({'passed': False, 'error': 'run:\n' + (run.stdout + run.stderr)[-1500:]}))
        return 1
    print(json.dumps({'passed': True, 'checks': run.stdout.strip()}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
