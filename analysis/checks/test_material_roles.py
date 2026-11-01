#!/usr/bin/env python3
"""FROZEN gate for material_roles.h: the C++ port of pbr_trace.py must give the same roles on every shader.

Usage: test_material_roles.py [--candidate PATH/material_roles.h]

Reference: analysis/checks/pbr_trace.py (roles()). Inputs: the synthetic shaders of test_pbr_trace.py, plus every
*.asm under analysis/runtime/pbr-re/all_lit (D3DDisassemble of the 3,080 lit pixel shaders; required, the gate fails
if the corpus is missing rather than passing on a handful of cases).

Required API (material_roles.h, header-only, C++17, no Windows headers):
    namespace material_roles {
    struct Channel { int slot = -1; std::string channels; bool invert = false; };  // slot -1: role not found
    struct Roles { Channel albedo, metal, gloss, normal, detail_normal; };
    Roles parse(const std::string& disassembly);
    }
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
sys.path.insert(0, str(C))
import pbr_trace  # noqa: E402
import test_pbr_trace as synth  # noqa: E402

HEADER = Path(sys.argv[sys.argv.index('--candidate') + 1]) if '--candidate' in sys.argv else C / 'material_roles.h'
CORPUS = C.parent / 'runtime' / 'pbr-re' / 'all_lit'
# The same 605 shader blobs (live run pbr-diag1) disassembled by Microsoft's D3DDisassemble on the laptop and by Wine's
# here: roles must not depend on the disassembler (the game process uses Microsoft's).
PAIRED = C.parent / 'runtime' / 'pbr-re' / 'paired_diag1'
ROLES = ('albedo', 'metal', 'gloss', 'normal', 'detail_normal')
HARNESS = r'''
#include "material_roles.h"
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
int main(int argc, char** argv) {
    for (int i = 1; i < argc; ++i) {
        std::ifstream f(argv[i], std::ios::binary);
        std::stringstream ss; ss << f.rdbuf();
        const material_roles::Roles r = material_roles::parse(ss.str());
        const material_roles::Channel* c[5] = {&r.albedo, &r.metal, &r.gloss, &r.normal, &r.detail_normal};
        std::printf("%s", argv[i]);
        for (int k = 0; k < 5; ++k) std::printf(" %d:%s:%d", c[k]->slot, c[k]->slot < 0 ? "-" : c[k]->channels.c_str(), c[k]->invert ? 1 : 0);
        std::printf("\n");
    }
    return 0;
}
'''


def expected(text):
    r = pbr_trace.roles(text)
    return ' '.join(f"{r[k]['slot']}:{r[k]['channels']}:{1 if r[k].get('invert') else 0}" if k in r else '-1:-:0'
                    for k in ROLES)


def fail(msg):
    print(json.dumps({'passed': False, 'error': msg[-3000:]}))
    sys.exit(1)


def main():
    if not HEADER.exists():
        fail(f'missing {HEADER}')
    files = sorted(CORPUS.glob('*.asm'))
    if len(files) < 3000:
        fail(f'corpus missing: {len(files)} .asm files in {CORPUS} (expected 3080; disassemble the lit shaders first)')
    work = Path(tempfile.mkdtemp(prefix='material-roles-'))
    ms = sorted((PAIRED / 'ms').glob('*.asm'))
    if len(ms) < 600:
        fail(f'paired corpus missing: {len(ms)} .asm in {PAIRED / "ms"} (Microsoft disassembly of pbr-diag1)')
    for path in ms:
        wine = PAIRED / 'wine' / path.name
        a, b = expected(path.read_text(errors='replace')), expected(wine.read_text(errors='replace'))
        if a != b:
            fail(f'{path.name}: roles depend on the disassembler: Microsoft {a} vs Wine {b}')
    for name, text in (('synth_lit', synth.LIT), ('synth_lit_ms', synth.LIT_MS), ('synth_effect', synth.EFFECT)):
        (work / f'{name}.asm').write_text(text)
    inputs = [work / 'synth_lit.asm', work / 'synth_lit_ms.asm', work / 'synth_effect.asm'] + files + ms
    (work / 'h.cpp').write_text(HARNESS)
    # The harness includes "material_roles.h": a candidate under another name is copied in under that name.
    (work / 'material_roles.h').write_text(HEADER.read_text())
    b = subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        '-I', str(work), str(work / 'h.cpp'), '-o', str(work / 'h')],
                       capture_output=True, text=True)
    if b.returncode:
        fail('compile:\n' + b.stderr)
    got = {}
    for i in range(0, len(inputs), 400):  # argv limits
        r = subprocess.run([str(work / 'h'), *map(str, inputs[i:i + 400])], capture_output=True, text=True, timeout=600)
        if r.returncode:
            fail('run:\n' + r.stderr)
        for line in r.stdout.splitlines():
            path, rest = line.split(' ', 1)
            got[path] = rest
    wrong = []
    for path in inputs:
        want = expected(path.read_text(errors='replace'))
        if got.get(str(path)) != want:
            wrong.append(f'{path.name}: got {got.get(str(path))} want {want}')
    if wrong:
        fail(f'{len(wrong)} of {len(inputs)} shaders differ:\n' + '\n'.join(wrong[:12]))
    print(json.dumps({'passed': True, 'shaders': len(inputs), 'note': 'identical to pbr_trace.py on every shader'}))


if __name__ == '__main__':
    main()
