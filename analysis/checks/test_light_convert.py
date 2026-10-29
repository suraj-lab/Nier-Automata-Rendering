#!/usr/bin/env python3
"""Gate: light_convert.h turns NieR's light-array bytes into Remix sphere-light parameters.

Pins: field offsets (point 0/12/32/44, spot 0/12/32/44/48, from SHADER_DECLARATIONS.md); padding and junk are skipped
(zero position, NaN, black, non-positive range, zero direction); FirstElement/NumElements are honoured; the
64-light budget; the emitter stays small (0.1) instead of becoming a range-sized ball (the earlier live code used the
range as the sphere radius); intensity = colour * scale * (range/2)^2 / (pi r^2); spot cone from the cosines.
Native g++ only.
"""
import json
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include <cstdio>
#include <fstream>
#include <iterator>
#include <cstdlib>
#include "light_convert.h"
int main(int, char** argv) {
    std::ifstream f(argv[1], std::ios::binary);
    std::vector<unsigned char> b((std::istreambuf_iterator<char>(f)), {});
    std::vector<light_convert::Light> out;
    light_convert::parse(b.data(), b.size(), std::atoi(argv[2]), std::atoi(argv[3]), std::atoi(argv[4]), argv[5][0] == '1', out);
    for (const auto& l : out) {
        const auto s = light_convert::to_sphere(l, std::atof(argv[6]));
        std::printf("%g %g %g %g %g %g %g %g %d %g %g %g %g %g\n", s.position[0], s.position[1], s.position[2], s.radius,
                    s.radiance[0], s.radiance[1], s.radiance[2], l.range, s.shaped ? 1 : 0, s.direction[0], s.direction[1],
                    s.direction[2], s.cone_angle_degrees, s.cone_softness);
    }
}
'''


def point(pos, rng, colour, inner):
    e = [0.0] * 12
    e[0:3], e[3], e[8:11], e[11] = pos, rng, colour, inner
    return struct.pack('<12f', *e)


def spot(pos, outer_cos, colour, inner_cos, direction):
    e = [0.0] * 20
    e[0:3], e[3], e[8:11], e[11], e[12:15] = pos, outer_cos, colour, inner_cos, direction
    return struct.pack('<20f', *e)


def run(exe, work, blob, stride, first, count, is_spot, scale=1.0):
    p = work / 'in.bin'
    p.write_bytes(blob)
    out = subprocess.run([str(exe), str(p), str(stride), str(first), str(count), '1' if is_spot else '0', str(scale)],
                         capture_output=True, text=True, check=True).stdout
    return [list(map(float, l.split())) for l in out.splitlines() if l]


def near(a, b, tol=1e-3):
    return abs(a - b) <= tol * max(1.0, abs(b))


def main():
    work = Path(tempfile.mkdtemp(prefix='lights-'))
    (work / 'h.cpp').write_text(HARNESS)
    r = subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(C), str(work / 'h.cpp'),
                        '-o', str(work / 'h')], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    exe = work / 'h'

    good = point((100, 20, 300), 25, (3, 1.5, 0.5), 1)
    blob = (good + point((0, 0, 0), 25, (1, 1, 1), 1) + point((float('nan'), 0, 1), 25, (1, 1, 1), 1)
            + point((5, 5, 5), 10, (0, 0, 0), 1) + point((6, 6, 6), 0, (1, 1, 1), 1) + point((-50, 5, 650), 40, (0.2, 0.6, 4), 2))
    rows = run(exe, work, blob, 48, 0, 6, False)
    assert len(rows) == 2, f'padding/junk not skipped: {len(rows)} lights from 6 elements (2 valid)'
    a = rows[0]
    k = 12.5 ** 2 / (math.pi * 0.01)
    assert a[0:3] == [100, 20, 300] and near(a[3], 0.1), f'position/emitter radius: {a[0:4]}'
    assert all(near(a[4 + i], c * k) for i, c in enumerate((3, 1.5, 0.5))), f'radiance {a[4:7]} != colour * {k:.1f}'
    assert a[7] == 25 and a[8] == 0, 'range from offset 12; points are unshaped'
    rows2 = run(exe, work, blob, 48, 0, 6, False, 0.5)
    assert near(rows2[0][4], 3 * k * 0.5), 'scale must multiply the radiance'
    assert len(run(exe, work, blob, 48, 5, 1, False)) == 1 and run(exe, work, blob, 48, 5, 1, False)[0][0] == -50, 'FirstElement'
    assert run(exe, work, good * 100, 48, 0, 100, False).__len__() == 64, '64-light budget'
    assert run(exe, work, blob, 64, 0, 6, False) == [], 'unknown stride must yield nothing'

    sblob = spot((1, 2, 3), math.cos(math.radians(30)), (2, 2, 2), math.cos(math.radians(15)), (0, 0, 2)) \
        + spot((4, 4, 4), 0.9, (1, 1, 1), 0.95, (0, 0, 0))
    srows = run(exe, work, sblob, 80, 0, 2, True)
    assert len(srows) == 1, f'spot with zero direction must be skipped: {len(srows)}'
    s = srows[0]
    assert s[8] == 1 and s[9:12] == [0, 0, 1], f'spot shaping/direction: {s[8:12]}'
    assert near(s[12], 30) and near(s[13], 0.5), f'cone {s[12]} deg softness {s[13]} (want 30, 0.5)'
    print(json.dumps({'passed': True}))


if __name__ == '__main__':
    try:
        main()
    except AssertionError as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
