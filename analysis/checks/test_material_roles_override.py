#!/usr/bin/env python3
"""FROZEN gate for L3 (PLAN_2026-11-13): material_roles.h must report the game's cb1 flag overrides, like pbr_trace.py.

In the suite (renamed from gate_material_roles_override.py once the port landed, 2026-11-13): the C++ port was
written against this gate by a cloud `worker` and rerun by the lead, then mutation-checked (disabling the override
recording moves 41 of the first 60 shaders).

Usage: test_material_roles_override.py [--candidate PATH/material_roles.h] [--limit N]

Reference: `pbr_trace.roles()` (Python, patched 2026-11-13; `replay/wip-pbr-trace-overrides.patch`, applied). The
Python half is already covered by `test_pbr_trace.py` (hand-read flags on a real game shader) and
`test_roles_coverage.py` (605 shaders unchanged).

What the header must add (no Windows headers, header-only, C++17):

    struct Flag { int cb = -1; int reg = -1; char lane = 0; const char* test = ""; };   // "ne" (lane != 0) or "gt"
    struct Constant { bool present = false; Flag flag; int cb = -1; int reg = -1; std::string lanes; };
    struct Channel { int slot = -1; std::string channels; bool invert = false;
                     Constant override;    // albedo / metal / gloss: the constant that replaces the texture channels
                     Flag enable; };       // normal / detail_normal: the flag the map's sampling sits under

Expected on the game's own lit family (read by hand in runtime/pbr-re/lit/ps_1874571568.asm:91-99):
`ne r10.xyz, l(0), cb1[0].yzw` -> albedo constant cb1[4].xyz under cb1[0].y, gloss cb1[5].x under cb1[0].z,
metal cb1[5].y under cb1[0].w; the normal sample sits under cb1[0].x and the detail blend under cb1[2].z.
Coverage over the 605-shader live set: albedo 88/104, metal 101/102, gloss 88/94, normal 100/111.

Limits: proves the tracer agrees with the Python reference on disassembly text. It says nothing about what the draws
do with the values; that is `live_capture.h` and the mock gate that follows (L3 step 5).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
sys.path.insert(0, str(C))
import pbr_trace  # noqa: E402

HEADER = Path(sys.argv[sys.argv.index('--candidate') + 1]) if '--candidate' in sys.argv else C / 'material_roles.h'
LIMIT = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 0
CORPORA = [A / 'runtime' / 'pbr-re' / 'all_lit', A / 'runtime' / 'pbr-re' / 'meta']
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
        for (int k = 0; k < 5; ++k) {
            std::printf(" %d:%s:%d", c[k]->slot, c[k]->slot < 0 ? "-" : c[k]->channels.c_str(), c[k]->invert ? 1 : 0);
            if (c[k]->override.present)
                std::printf(" o=%d:%d:%c:%s>%d:%d:%s", c[k]->override.flag.cb, c[k]->override.flag.reg,
                            c[k]->override.flag.lane, c[k]->override.flag.test, c[k]->override.cb, c[k]->override.reg,
                            c[k]->override.lanes.c_str());
            if (c[k]->enable.cb >= 0)
                std::printf(" e=%d:%d:%c:%s", c[k]->enable.cb, c[k]->enable.reg, c[k]->enable.lane, c[k]->enable.test);
        }
        std::printf("\n");
    }
    return 0;
}
'''


def expected(text):
    r = pbr_trace.roles(text)
    out = []
    for k in ROLES:
        if k not in r:
            out.append('-1:-:0')
            continue
        role = r[k]
        s = f"{role['slot']}:{role['channels']}:{1 if role.get('invert') else 0}"
        if o := role.get('override'):
            f = o['flag']
            s += f" o={f['cb']}:{f['register']}:{f['lane']}:{f['test']}>{o['cb']}:{o['register']}:{o['lanes']}"
        if e := role.get('enable'):
            s += f" e={e['cb']}:{e['register']}:{e['lane']}:{e['test']}"
        out.append(s)
    return ' '.join(out)


def fail(msg):
    print(json.dumps({'passed': False, 'error': msg[-3000:]}))
    sys.exit(1)


def main():
    if not HEADER.exists():
        fail(f'missing {HEADER}')
    files = []
    for corpus in CORPORA:
        if not corpus.exists():
            fail(f'corpus missing: {corpus}')
        files += sorted(corpus.glob('*.asm'))
    if len(files) < 3000:
        fail(f'corpus too small: {len(files)} .asm files (expected the 3,080 lit plus the 605 live set)')
    if LIMIT:
        files = files[:LIMIT]
    work = Path(tempfile.mkdtemp(prefix='roles-override-'))
    (work / 'h.cpp').write_text(HARNESS)
    (work / 'material_roles.h').write_text(HEADER.read_text())
    b = subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(work),
                        str(work / 'h.cpp'), '-o', str(work / 'h')], capture_output=True, text=True)
    if b.returncode:
        fail('compile: the header does not report overrides yet:\n' + b.stderr)
    got = {}
    for i in range(0, len(files), 400):
        r = subprocess.run([str(work / 'h'), *map(str, files[i:i + 400])], capture_output=True, text=True, timeout=900)
        if r.returncode:
            fail('run:\n' + r.stderr)
        for line in r.stdout.splitlines():
            path, rest = line.split(' ', 1)
            got[path] = rest
    wrong = [f'{p.name}: got {got.get(str(p))} want {expected(p.read_text(errors="replace"))}'
             for p in files if got.get(str(p)) != expected(p.read_text(errors='replace'))]
    if wrong:
        fail(f'{len(wrong)} of {len(files)} shaders differ:\n' + '\n'.join(wrong[:10]))
    print(json.dumps({'passed': True, 'shaders': len(files),
                      'note': 'C++ override and enable fields identical to pbr_trace.py on every shader'}))


if __name__ == '__main__':
    main()
