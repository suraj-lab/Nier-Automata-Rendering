#!/usr/bin/env python3
"""FROZEN gate for geometry_convert.h: native ASan/UBSan test + two-TU link + MinGW cross-build."""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

C = pathlib.Path(__file__).resolve().parent
OUT = C.parent / 'runtime' / 'geometry-convert' / 'gates'
FLAGS = ['-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
         '-fno-sanitize-recover=all']
SECOND_TU = '#include "geometry_convert.h"\n'
SECOND_TU += 'bool second_tu(const unsigned char* b, std::size_t n, unsigned s,\n'
SECOND_TU += '               const std::vector<geometry_convert::Element>& e, std::vector<geometry_convert::Vertex>& v)\n'
SECOND_TU += '{ return geometry_convert::convert(b, n, s, e, v); }\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidate', type=pathlib.Path, default=C / 'geometry_convert.h')
    candidate = ap.parse_args().candidate.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    gate = pathlib.Path(tempfile.mkdtemp(prefix='gate-', dir=OUT))
    shutil.copy(candidate, gate / 'geometry_convert.h')
    shutil.copy(C / 'geometry_convert_test.cpp', gate / 'geometry_convert_test.cpp')
    (gate / 'second_tu.cpp').write_text(SECOND_TU)
    steps = [
        ('native-build', ['g++', *FLAGS, 'geometry_convert_test.cpp', 'second_tu.cpp', '-o', 'test']),
        ('native-test', ['./test']),
        ('windows-cross-build', ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                                 '-static', 'geometry_convert_test.cpp', 'second_tu.cpp', '-o', 'test.exe']),
    ]
    result = {'passed': True, 'candidate_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(),
              'artifacts': str(gate), 'steps': []}
    for name, cmd in steps:
        p = subprocess.run(cmd, cwd=gate, capture_output=True, text=True, timeout=600)
        (gate / (name + '.log')).write_text(p.stdout + p.stderr)
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
