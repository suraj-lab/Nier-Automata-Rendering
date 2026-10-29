#!/usr/bin/env python3
"""Gate: decode the verified PS CB2 prefix, not the unrelated VS CB2 or dummy [1,1,1] vector.

The game uses saturate(dot(worldNormal, cb2[1].xyz)) and cb2[0].rgb as its light colour.
Remix Distant.direction points along incoming rays, hence the sign reversal. Radiometric
calibration and sky lighting are deliberately not asserted by this byte-level test.
"""
import json
import math
import struct
import subprocess
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include <cstdio>
#include <iterator>
#include <iostream>
#include "light_convert.h"
int main() {
    std::vector<unsigned char> b((std::istreambuf_iterator<char>(std::cin)), {});
    light_convert::Sun s{};
    for (int i=0; i<3; ++i) s.colour[i]=s.direction[i]=123;
    const bool ok=light_convert::parse_sun(b.empty()?nullptr:b.data(), b.size(), s);
    std::printf("%d %.9g %.9g %.9g %.9g %.9g %.9g\n", ok?1:0,
                s.colour[0],s.colour[1],s.colour[2],s.direction[0],s.direction[1],s.direction[2]);
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='sun-gate-') as tmp:
        w = Path(tmp)
        (w / 'h.cpp').write_text(HARNESS)
        p = subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(C),
                            str(w / 'h.cpp'), '-o', str(w / 'h')], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr[-1500:]

        def run(blob):
            p = subprocess.run([str(w / 'h')], input=blob, capture_output=True, check=True)
            return list(map(float, p.stdout.split()))

        def blob(colour=(6, 5.1, 4.8), direction=(-0.4291814, 0.83867055, -0.33531323)):
            return struct.pack('<8f', *colour, 6, *direction, 0)

        b = blob()
        a = run(b)
        assert a[0] == 1 and all(math.isclose(x, y, abs_tol=1e-6) for x, y in zip(a[1:4], (6, 5.1, 4.8))), a
        assert all(math.isclose(x, -y, abs_tol=1e-6) for x, y in zip(a[4:], (-0.4291814, 0.83867055, -0.33531323))), a
        assert math.isclose(sum(x*x for x in a[4:]), 1, abs_tol=1e-6), 'unit incoming ray direction'
        assert run(b + struct.pack('<24f', *([float('nan')] * 24))) == a, 'unrelated CB fields may contain NaN bitmasks'
        assert run(blob((0, 0, 0)))[1:4] == [0, 0, 0], 'disabled sun must not become a fallback sun'
        assert run(blob((1, 0, 0), (0, 1, 0)))[4:] == [0, -1, 0], 'upward to-light vector means downward rays'
        dummy_unit = bytearray(blob(direction=(0, 1, 0)))
        struct.pack_into('<f', dummy_unit, 28, 1)  # dummy row must not pass merely because xyz happens to be unit
        bad = [b'', b[:16], b[:31], bytes(dummy_unit), blob(direction=(1, 1, 1)), blob(direction=(0, 0, 0)),
               blob(direction=(float('inf'), 0, 0)), blob(colour=(-1, 1, 1)),
               blob(colour=(float('nan'), 1, 1)), blob(colour=(float('inf'), 1, 1))]
        for data in bad:
            assert run(data) == [0, 123, 123, 123, 123, 123, 123], 'invalid input must leave output untouched'
        print(json.dumps({'passed': True, 'cases': len(bad) + 5}))


if __name__ == '__main__':
    try:
        main()
    except (AssertionError, subprocess.SubprocessError) as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        raise SystemExit(1)
