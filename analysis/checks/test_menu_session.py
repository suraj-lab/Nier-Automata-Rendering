#!/usr/bin/env python3
"""FROZEN gate for menu_session.h. Usage: test_menu_session.py [--candidate PATH/menu_session.h]
Isolated copy, ASan/UBSan -Werror native test, two-TU link, MinGW x64 build. Writes result.json."""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

C = pathlib.Path(__file__).resolve().parent
OUT = C.parent / 'runtime' / 'menu-session' / 'gates'
FLAGS = ['-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
         '-fno-sanitize-recover=all']
SECOND_TU = ('#include "menu_session.h"\n'
             'render_menu::SessionMode second_tu(const startup_status::Snapshot& s)'
             ' { return menu_session::from_status(s).mode; }\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidate', type=pathlib.Path, default=C / 'menu_session.h')
    candidate = ap.parse_args().candidate.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    gate = pathlib.Path(tempfile.mkdtemp(prefix='gate-', dir=OUT))
    shutil.copy(candidate, gate / 'menu_session.h')
    for name in ('render_settings.h', 'menu_state.h', 'startup_status.h', 'menu_session_test.cpp'):
        shutil.copy(C / name, gate / name)
    (gate / 'second_tu.cpp').write_text(SECOND_TU)
    steps = [
        ('native-build', ['g++', *FLAGS, 'menu_session_test.cpp', 'second_tu.cpp', '-o', 'test']),
        ('native-test', ['./test']),
        ('windows-cross-build', ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                                 '-static', 'menu_session_test.cpp', 'second_tu.cpp', '-o', 'test.exe']),
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
