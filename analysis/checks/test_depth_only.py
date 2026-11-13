#!/usr/bin/env python3
"""Gate for item L7's depth-pass rule (checks/depth_only.h). Native, sanitized.

Positives: NieR's two linear-depth shaders, disassembled from a real capture (fixtures/depth-only, bytecode FNV-1a
653185b46aa47c13 with an alpha cut and 653dabe484d5d462 without). Negatives: every lit shader of the corpus
(runtime/pbr-re/all_lit, all surfaces; none may be flagged), and hand-written shapes that look close: a flat-colour unlit
shader (no sample, no z/w), an alpha-cut card whose colour is its texture, and a depth write whose value is a sample.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
A = C.parent
FIX = C / 'fixtures/depth-only'
CORPUS = A / 'runtime/pbr-re/all_lit'

FLAT = """ps_5_0
dcl_constantbuffer CB1[5], immediateIndexed
dcl_output o0.xyzw
mov o0.xyzw, cb1[4].xyzw
ret
"""
CARD = """ps_5_0
dcl_resource_texture2d (float,float,float,float) t0
dcl_input_ps linear v1.zw
dcl_input_ps linear v2.xy
dcl_output o0.xyzw
dcl_temps 2
sample_indexable(texture2d)(float,float,float,float) r0.xyzw, v2.xyxx, t0.xyzw, s0
lt r1.x, r0.w, l(0.500000)
discard_nz r1.x
div_sat r1.y, v1.z, v1.w
mul o0.xyzw, r0.xyzw, r1.yyyy
ret
"""
SAMPLED_DEPTH = """ps_5_0
dcl_resource_texture2d (float,float,float,float) t0
dcl_input_ps linear v1.zw
dcl_output o0.xyzw
dcl_temps 1
div_sat r0.x, v1.z, v1.w
sample_indexable(texture2d)(float,float,float,float) r0.y, v1.zwzz, t0.yxzw, s0
add r0.x, r0.x, r0.y
mov o0.xyzw, r0.xxxx
ret
"""
SRC = r'''
#include "depth_only.h"
#include <cstdio>
#include <fstream>
#include <sstream>
int main(int argc, char** argv) {
    for (int i = 1; i < argc; ++i) {
        std::ifstream f(argv[i]);
        std::stringstream ss; ss << f.rdbuf();
        std::printf("%d %s\n", depth_only::writes_depth_only(ss.str()) ? 1 : 0, argv[i]);
    }
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='depth-only-'))
    (work / 't.cpp').write_text(SRC)
    subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I', str(C), str(work / 't.cpp'), '-o', str(work / 't')], check=True)
    for name, text in (('flat.asm', FLAT), ('card.asm', CARD), ('sampled_depth.asm', SAMPLED_DEPTH)):
        (work / name).write_text(text)
    positives = sorted(FIX.glob('*.asm'))
    negatives = [work / 'flat.asm', work / 'card.asm', work / 'sampled_depth.asm']
    corpus = sorted(CORPUS.glob('*.asm')) if CORPUS.exists() else []
    files = positives + negatives + corpus
    out = {}
    for start in range(0, len(files), 500):
        r = subprocess.run([str(work / 't')] + [str(f) for f in files[start:start + 500]], capture_output=True, text=True, check=True)
        for line in r.stdout.splitlines():
            flag, path = line.split(' ', 1)
            out[path] = flag == '1'
    assert len(positives) == 2 and all(out[str(p)] for p in positives), {p.name: out[str(p)] for p in positives}
    for n in negatives:
        assert not out[str(n)], f'{n.name} is a surface and was flagged a depth pass'
    flagged = [f.name for f in corpus if out[str(f)]]
    assert not flagged, f'{len(flagged)} lit corpus shaders flagged as depth passes: {flagged[:5]}'
    print(json.dumps({'passed': True, 'positives': len(positives), 'negatives': len(negatives),
                      'corpus_lit_checked': len(corpus)}))


if __name__ == '__main__':
    try:
        main()
    except AssertionError as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
