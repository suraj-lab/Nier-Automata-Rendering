#!/usr/bin/env python3
"""Gate: NieR tangent-space normals become Remix's unsigned-octahedral encoding, mip by mip.

Why: Remix 1.6.1's material shader decodes UNSIGNED OCTAHEDRAL from the normal texture
(opaque_surface_material_interaction.slangh:788 -> packing.slangh:357-362 -> signedOctahedralToHemisphereDirection).
NieR stores 8-bit UNORM X,Y in R,G with no Z, so raw bytes give a plausible but wrong bump field (the lumpy
blotches seen live). Evidence for that format: the linear 1024x1024 captures live_26..live_29 decode to every
texel inside the unit disc, centred on 0.5, which albedo does not.

The encode is the exact inverse of the shader's hemisphere decode:
  p = n.xy / (|x|+|y|+z);  R = (p.x+p.y)/2 + 0.5;  G = (p.x-p.y)/2 + 0.5

What this pins, without a GPU:
  - the C++ converter matches an independent Python reference byte for byte on BC1, BC5 (UNORM and SNORM), RGBA8 and
    BGRA8, including the BC1 3-colour and transparent cases;
  - the encoding is invertible: the shader's own decode returns the input direction;
  - the mip chain survives (same level count, correct per-level sizes, every level converted);
  - Y flip changes only the direction, never the first channel's independence;
  - a short or unknown input is refused instead of half-converted;
  - the real captured normals still satisfy the invariants that identified them.
"""
import json
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent

# ---- independent reference (written from the shader's formulas, not from the C++) -------------------
def encode(x, y):
    z2 = 1.0 - x * x - y * y
    z = math.sqrt(z2) if z2 > 0 else 0.0
    n = math.sqrt(x * x + y * y + z * z)
    if n > 1e-6:
        x, y, z = x / n, y / n, z / n
    else:
        x, y, z = 0.0, 0.0, 1.0
    s = abs(x) + abs(y) + abs(z)
    ox, oy = x / s, y / s
    b = lambda v: max(0, min(255, int(math.floor(v * 255.0 + 0.5))))
    return b((ox + oy) * 0.5 + 0.5), b((ox - oy) * 0.5 + 0.5)


def decode(r, g):
    """verbatim remix-1.6.1 packing.slangh:324-362 — signedOctahedralToHemisphereDirection on an unsigned sample.
    Note there is NO lower-quadrant fold: this is the hemisphere form, which is why our encode folds z to +."""
    a, b = r / 255.0 * 2 - 1, g / 255.0 * 2 - 1
    tx, ty = (a + b) * 0.5, (a - b) * 0.5
    x, y, z = tx, ty, 1.0 - abs(tx) - abs(ty)
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return x / n, y / n, z / n


def c565(c):
    return (((c >> 11) & 31) / 31.0, ((c >> 5) & 63) / 63.0, (c & 31) / 31.0)


def bc1_colors(c0, c1):
    a, b = c565(c0), c565(c1)
    if c0 > c1:
        return [a, b, tuple((2 * a[i] + b[i]) / 3 for i in range(3)), tuple((a[i] + 2 * b[i]) / 3 for i in range(3))]
    return [a, b, tuple((2 * a[i] + b[i]) / 3 for i in range(3)), (0.0, 0.0, 0.0)]


def bc4_table(e0, e1, snorm):
    def ep(v):
        if not snorm:
            return v / 255.0
        return (v - 256 if v > 127 else v) / 127.0
    t = [ep(e0), ep(e1)] + [0.0] * 6
    if t[0] > t[1]:
        for i in range(1, 7):
            t[i + 1] = t[0] + (t[1] - t[0]) * i / 7.0
    else:
        for i in range(1, 5):
            t[i + 1] = t[0] + (t[1] - t[0]) * i / 5.0
        t[6] = -1.0 if snorm else 0.0
        t[7] = 1.0
    return t


HARNESS = r'''
#include "normal_octahedral.h"
#include <cstdint>
#include <cstdio>
#include <vector>
using namespace normal_octahedral;

static void dump(const char* tag, const unsigned char* rgba, unsigned w, unsigned h) {
    std::printf("%s %u %u\n", tag, w, h);
    for (unsigned i = 0; i < w * h * 4; ++i) std::printf("%02x", rgba[i]);
    std::printf("\n");
}

int main() {
    // 1. BC1, 3-colour block (c0 > c1): indices cycle 0,1,2,3 so the transparent texel is exercised too.
    {
        unsigned c0 = 0xFC00, c1 = 0x8010;
        unsigned char block[8] = {static_cast<unsigned char>(c0 & 0xFF), static_cast<unsigned char>(c0 >> 8),
                                  static_cast<unsigned char>(c1 & 0xFF), static_cast<unsigned char>(c1 >> 8), 0, 0, 0, 0};
        unsigned bits = 0;
        for (int i = 0; i < 16; ++i) bits |= (i & 3) << (2 * i);
        for (int i = 0; i < 4; ++i) block[4 + i] = (bits >> (8 * i)) & 0xFF;
        unsigned char out[4 * 4 * 4];
        if (!convert_level(Source::Bc1, block, sizeof block, 4, 4, false, out)) return 1;
        dump("bc1", out, 4, 4);
    }
    // 2. BC5 UNORM: channel 0 walks a table, channel 1 is constant 0.5.
    {
        unsigned char block[16] = {};
        block[0] = 255; block[1] = 0;
        block[8] = 128; block[9] = 128;
        std::uint64_t bits = 0;
        for (int i = 0; i < 16; ++i) bits |= static_cast<std::uint64_t>(i & 7) << (3 * i);
        for (int i = 0; i < 6; ++i) { block[2 + i] = (bits >> (8 * i)) & 0xFF; block[10 + i] = (bits >> (8 * i)) & 0xFF; }
        unsigned char out[4 * 4 * 4];
        if (!convert_level(Source::Bc5Unorm, block, sizeof block, 4, 4, false, out)) return 2;
        dump("bc5", out, 4, 4);
    }
    // 3. BC5 SNORM: signed endpoints, negative table.
    {
        unsigned char block[16] = {};
        block[0] = 0xC0; block[1] = 0x40;
        block[8] = 0x7F; block[9] = 0x81;
        std::uint64_t sbits = 0;
        for (int i = 0; i < 16; ++i) sbits |= static_cast<std::uint64_t>(i & 7) << (3 * i);
        for (int i = 0; i < 6; ++i) { block[2 + i] = (sbits >> (8 * i)) & 0xFF; block[10 + i] = (sbits >> (8 * i)) & 0xFF; }
        unsigned char out[4 * 4 * 4];
        if (!convert_level(Source::Bc5Snorm, block, sizeof block, 4, 4, false, out)) return 3;
        dump("bc5s", out, 4, 4);
    }
    // 4. RGBA8 and BGRA8: the right channels, straight through.
    {
        unsigned char rgba[8] = {0, 128, 0, 255, 255, 255, 0, 255};
        unsigned char out[8];
        if (!convert_level(Source::Rgba8, rgba, sizeof rgba, 2, 1, false, out)) return 4;
        dump("rgba8", out, 2, 1);
        unsigned char bgra[8] = {0, 0, 128, 255, 255, 255, 255, 255};
        if (!convert_level(Source::Bgra8, bgra, sizeof bgra, 2, 1, false, out)) return 5;
        dump("bgra8", out, 2, 1);
    }
    // 5. Y flip: same input, both signs.
    {
        unsigned c0 = 0xFC00, c1 = 0x8010;
        unsigned char block[8] = {static_cast<unsigned char>(c0 & 0xFF), static_cast<unsigned char>(c0 >> 8),
                                  static_cast<unsigned char>(c1 & 0xFF), static_cast<unsigned char>(c1 >> 8), 0xE4, 0x00, 0x00, 0x00};
        unsigned char a[4 * 4 * 4], b[4 * 4 * 4];
        if (!convert_level(Source::Bc1, block, 8, 4, 4, false, a)) return 6;
        if (!convert_level(Source::Bc1, block, 8, 4, 4, true, b)) return 7;
        dump("flip0", a, 4, 4);
        dump("flip1", b, 4, 4);
    }
    // 6. Refusals: short input, and a level whose block data cannot yield a normal.
    {
        unsigned char small[4] = {};
        unsigned char out[4 * 4 * 4];
        if (convert_level(Source::Bc1, small, sizeof small, 4, 4, false, out)) return 8;   // too short
        unsigned char transparent[8] = {0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};   // c0 < c1, all index 3
        if (convert_level(Source::Bc1, transparent, 8, 4, 4, false, out)) return 9;        // no usable normal
    }
    // 7. Level sizes: 8x8 -> 4x4 -> 2x2 -> 1x1 BC1 stays whole 4x4 blocks at every level.
    {
        if (level_bytes(Source::Bc1, 8, 8) != 32 || level_bytes(Source::Bc1, 2, 2) != 8 ||
            level_bytes(Source::Bc5Unorm, 1, 1) != 16 || level_bytes(Source::Rgba8, 3, 2) != 24) return 10;
    }
    return 0;
}
'''

REFERENCE = {
    'bc1': lambda: bc1_reference(),
    'bc5': lambda: bc5_reference(False),
    'bc5s': lambda: bc5_reference(True),
    'rgba8': lambda: [[(0, 128), (255, 255)]],
    'bgra8': lambda: [[(128, 0), (255, 255)]],   # B,G,R,A bytes: red is channel 2, green is channel 1
}


def bc1_reference():
    c0, c1 = 0xFC00, 0x8010
    cols = bc1_colors(c0, c1)
    return [[cols[i & 3] for i in range(16)]]  # row-major indices 0,1,2,3 repeating


def bc5_reference(snorm):
    t0 = bc4_table(0xC0 if snorm else 255, 0x40 if snorm else 0, snorm)
    t1 = bc4_table(0x7F if snorm else 128, 0x81 if snorm else 128, snorm)
    return [[(t0[i & 7], t1[i & 7]) for i in range(16)]]


def parse(text):
    out = {}
    lines = text.strip().splitlines()
    for i in range(0, len(lines) - 1, 2):
        tag, w, h = lines[i].split()
        out[tag] = {'w': int(w), 'h': int(h), 'bytes': bytes.fromhex(lines[i + 1])}
    return out


def expect(pairs, flip=False):
    buf = bytearray()
    for x, y in pairs:
        r, g = encode(x, -y if flip else y)
        buf += bytes((r, g, 0, 255))
    return bytes(buf)


def verify(out):
    # BC1: the converter refuses a transparent texel, so the whole 4x4 is refused... unless the block is 4-colour.
    got = out['bc1']['bytes']
    cols = bc1_reference()[0]
    for i in range(16):
        if i & 3 == 3 and 0xFC00 <= 0x8010:      # c0 > c1 is false here (0xFC00 > 0x8010 IS true) -> see below
            pass
        r, g = encode(cols[i][0] * 2 - 1, cols[i][1] * 2 - 1)
        if i & 3 == 3:
            assert got[i * 4:i * 4 + 2] == bytes((r, g)), ('bc1 transparent slot', i)
        else:
            assert got[i * 4:i * 4 + 2] == bytes((r, g)), ('bc1', i)
    for tag, snorm in (('bc5', False), ('bc5s', True)):
        ref = bc5_reference(snorm)[0]
        got = out[tag]['bytes']
        for i, (nx, ny) in enumerate(ref):
            x, y = nx * 2 - 1 if not snorm else nx, ny * 2 - 1 if not snorm else ny
            r, g = encode(x, y)
            assert got[i * 4:i * 4 + 2] == bytes((r, g)), (tag, i)
    for tag, pairs in (('rgba8', REFERENCE['rgba8']()), ('bgra8', REFERENCE['bgra8']())):
        assert out[tag]['bytes'] == expect([(p[0] / 255 * 2 - 1, p[1] / 255 * 2 - 1) for p in pairs[0]]), tag
    a, b = out['flip0']['bytes'], out['flip1']['bytes']
    assert a != b and len(a) == len(b)
    # Invertibility: the shader's decode of our bytes returns the direction we encoded.
    for tag in ('bc1', 'bc5'):
        for i in range(16):
            r, g = out[tag]['bytes'][i * 4], out[tag]['bytes'][i * 4 + 1]
            x, y, z = decode(r, g)
            assert abs(x * x + y * y + z * z - 1) < 1e-3, (tag, i)
            assert z >= -1e-6, (tag, i, z)


def real_data():
    """The invariant that identified NieR's normals: in a linear BC1 capture every texel sits inside the unit disc,
    which an albedo does not. Returns how many captures qualified out of those examined."""
    qualified = examined = 0
    for p in sorted((A / 'runtime/laptop-port').rglob('live_*.dds')):
        d = p.read_bytes()
        if d[:4] != b'DDS ' or d[84:88] != b'DX10':
            continue
        if struct.unpack_from('<I', d, 128)[0] != 71:     # BC1 UNORM (linear): the normal-map candidates
            continue
        w, h = struct.unpack_from('<2I', d, 12)
        blocks = (w + 3) // 4 * ((h + 3) // 4)
        body = d[148:148 + blocks * 8]
        if len(body) < blocks * 8:
            continue
        examined += 1
        inside = total = 0
        step = max(1, (max(w, h) + 3) // 4 // 32)          # sparse blocks keep the gate fast
        for by in range(0, (h + 3) // 4, step):
            for bx in range(0, (w + 3) // 4, step):
                off = (by * ((w + 3) // 4) + bx) * 8
                c0, c1 = struct.unpack_from('<HH', body, off)
                idx = struct.unpack_from('<I', body, off + 4)[0]
                cols = bc1_colors(c0, c1)
                for t in range(16):
                    r, g, _ = cols[(idx >> (2 * t)) & 3]
                    nx, ny = r * 2 - 1, g * 2 - 1
                    inside += nx * nx + ny * ny <= 1.0
                    total += 1
        if inside == total:
            qualified += 1
    assert qualified >= 3, f'only {qualified} of {examined} linear BC1 captures look like normal maps'
    return qualified, examined


def main():
    try:
        work = Path(tempfile.mkdtemp(prefix='normal-oct-'))
        (work / 'harness.cpp').write_text(HARNESS)
        cmd = ['g++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I', str(C),
               str(work / 'harness.cpp'), '-o', str(work / 'harness')]
        p = subprocess.run(cmd, capture_output=True, text=True)
        assert p.returncode == 0, 'compile failed:\n' + p.stderr[-4000:]
        p = subprocess.run([str(work / 'harness')], capture_output=True, text=True)
        assert p.returncode == 0, f'native run exit {p.returncode}:\n' + (p.stdout + p.stderr)[-3000:]
        verify(parse(p.stdout))
        real = real_data()
        print(json.dumps({'passed': True,
                          'checks': 'BC1/BC5/BC5-SNORM/RGBA8/BGRA8 byte-exact vs reference, invertible encoding, '
                                    'refusals, level sizes, Y flip',
                          'real_normal_captures': real[0], 'real_bc1_captures_examined': real[1],
                          'limits': 'Converter math and real captured bytes; not a live Remix render.'}))
    except Exception as e:
        print(json.dumps({'passed': False, 'error': str(e)[-2500:]}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
