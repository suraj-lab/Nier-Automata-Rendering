#!/usr/bin/env python3
"""Gate: alpha_test.h reads the discard condition out of a pixel shader's disassembly.

Fixtures are real NieR pixel shaders (capture frame_23275488, disassembled with the game prefix's d3dcompiler_47),
hand-read before this gate was written:
  ps_1799720080: sample t0.w; lt r0.x, r0.x, l(0.8); discard_nz r0.x       -> keep alpha >= 0.8  (kGreaterOrEqual, 204)
  ps_1888384240: ge r1.x, l(9.99999975e-05), r0.w; discard_nz r1.x         -> keep alpha > 0.0001 (kGreater, 0)
  ps_1802564064: eq r3.x, r1.w, l(0); if_nz r3.x; discard_nz l(4294967295) -> keep value != 0 (kNotEqual, 0)
plus edge cases (discard_z, operand order, an unrelated component write in between, an unknown comparison -> fallback),
and, when present, the 23 real scene shaders of that frame: exactly the 11 that discard are found, all parsed.
Native g++ only.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
CORPUS = C.parent / 'runtime/ps-asm-frame_23275488'
K = {'never': 0, 'less': 1, 'equal': 2, 'lequal': 3, 'greater': 4, 'notequal': 5, 'gequal': 6, 'always': 7}

HARNESS = r'''
#include <cstdio>
#include <fstream>
#include <sstream>
#include "alpha_test.h"
int main(int argc, char** argv) {
    for (int i = 1; i < argc; ++i) {
        std::ifstream f(argv[i]); std::stringstream s; s << f.rdbuf();
        const auto r = alpha_test::parse(s.str());
        std::printf("%s %d %d %d %u\n", argv[i], r.discards, r.parsed, r.op, r.reference);
    }
}
'''

CASES = {
    'nier_0p8': ('sample_indexable(texture2d) r0.x, r0.xyxx, t0.wxyz, s0\nlt r0.x, r0.x, l(8.00000012e-01)\n'
                 'discard_nz r0.x\nret\n', (1, 1, K['gequal'], 204)),
    'nier_eps': ('sample_indexable(texture2d) r0.xyzw, r0.xyxx, t0.xyzw, s0\nlt r2.y, l(0.00000000e+00), |r2.w|\n'
                 'ge r1.x, l(9.99999975e-05), r0.w\ndiscard_nz r1.x\nmov o0.xyzw, r0.xyzw\nret\n', (1, 1, K['greater'], 0)),
    'opaque': ('sample_indexable(texture2d) r0.xyzw, v1.xyxx, t0.xyzw, s0\nmov o0.xyzw, r0.xyzw\nret\n', (0, 0, K['always'], 0)),
    'nier_if_eq0': ('max r3.x, r3.x, l(0.00000000e+00)\nmul r1.w, r1.w, r3.x\neq r3.x, r1.w, l(0.00000000e+00)\n'
                    'if_nz r3.x\n  discard_nz l(4294967295)\nendif\n', (1, 1, K['notequal'], 0)),
    'discard_z': ('lt r0.x, r0.w, l(5.00000000e-01)\ndiscard_z r0.x\n', (1, 1, K['less'], 128)),
    'literal_first_lt': ('lt r3.z, l(2.50000000e-01), r0.w\ndiscard_nz r3.z\n', (1, 1, K['lequal'], 64)),
    'other_component_between': ('lt r0.x, r0.w, l(5.00000000e-01)\nmov r0.y, l(1.0)\ndiscard_nz r0.x\n',
                                (1, 1, K['gequal'], 128)),
    'unknown_compare': ('and r0.x, r0.w, l(1)\ndiscard_nz r0.x\n', (1, 0, K['greater'], 127)),
}


def main():
    work = Path(tempfile.mkdtemp(prefix='alpha-'))
    (work / 'h.cpp').write_text(HARNESS)
    r = subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(C), str(work / 'h.cpp'),
                        '-o', str(work / 'h')], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    files = []
    for name, (text, _) in CASES.items():
        (work / f'{name}.asm').write_text(text)
        files.append(str(work / f'{name}.asm'))
    out = subprocess.run([str(work / 'h'), *files], capture_output=True, text=True, check=True).stdout.split('\n')
    for line, (name, (_, want)) in zip(out, CASES.items()):
        got = tuple(int(x) for x in line.split()[1:])
        assert got == want, f'{name}: got {got}, want {want}'
    report = {'cases': len(CASES)}
    corpus = sorted(CORPUS.glob('*.asm'))
    if corpus:
        rows = subprocess.run([str(work / 'h'), *map(str, corpus)], capture_output=True, text=True, check=True).stdout.split('\n')
        rows = [x.split() for x in rows if x]
        discards = [x for x in rows if x[1] == '1']
        assert len(rows) == 23 and len(discards) == 11, f'{len(rows)} shaders, {len(discards)} discard (want 23 / 11)'
        unparsed = [Path(x[0]).name for x in discards if x[2] != '1']
        assert not unparsed, f'real discard shaders not understood: {unparsed}'
        report['real'] = sorted({(int(x[3]), int(x[4])) for x in discards})
    print(json.dumps({'passed': True, **report}))


if __name__ == '__main__':
    try:
        main()
    except AssertionError as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
