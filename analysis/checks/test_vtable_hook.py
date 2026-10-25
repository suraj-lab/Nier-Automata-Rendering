#!/usr/bin/env python3
"""FROZEN gate for vtable_hook.h. Usage: test_vtable_hook.py [--candidate PATH/vtable_hook.h]
Isolated copy; ASan/UBSan and TSan -Werror native tests; two-TU link; MinGW x64 build. Writes result.json."""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

C = pathlib.Path(__file__).resolve().parent
OUT = C.parent / 'runtime' / 'vtable-hook' / 'gates'
BASE = ['-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-pthread']
SECOND_TU = ('#include "vtable_hook.h"\n'
             'vtable_hook::Result second_tu(void** t, std::atomic<void*>& o, vtable_hook::Protect p)'
             ' { return vtable_hook::hook(t, 0, t, o, p); }\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidate', type=pathlib.Path, default=C / 'vtable_hook.h')
    candidate = ap.parse_args().candidate.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    gate = pathlib.Path(tempfile.mkdtemp(prefix='gate-', dir=OUT))
    shutil.copy(candidate, gate / 'vtable_hook.h')
    shutil.copy(C / 'vtable_hook_test.cpp', gate / 'vtable_hook_test.cpp')
    (gate / 'second_tu.cpp').write_text(SECOND_TU)
    steps = [
        ('asan-build', ['g++', *BASE, '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        'vtable_hook_test.cpp', 'second_tu.cpp', '-o', 'asan_test']),
        ('asan-test', ['./asan_test']),
        ('tsan-build', ['g++', *BASE, '-fsanitize=thread', 'vtable_hook_test.cpp', 'second_tu.cpp', '-o', 'tsan_test']),
        ('tsan-test', ['./tsan_test']),
        ('windows-cross-build', ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                                 '-static', 'vtable_hook_test.cpp', 'second_tu.cpp', '-o', 'test.exe']),
    ]
    result = {'passed': True, 'candidate_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(),
              'artifacts': str(gate), 'steps': []}
    for name, cmd in steps:
        p = subprocess.run(cmd, cwd=gate, capture_output=True, text=True, timeout=600)
        (gate / f'{name}.log').write_text(p.stdout + p.stderr)
        result['steps'].append({'name': name, 'exit': p.returncode})
        if p.returncode:
            result['passed'] = False
            print(f'FAIL {name}\n' + (p.stdout + p.stderr)[-3000:])
            break
    (gate / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
