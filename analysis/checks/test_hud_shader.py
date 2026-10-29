#!/usr/bin/env python3
"""Gate for the native HUD handoff classifier; includes exact shipped shaders when capture artifacts exist."""
import json
import struct
import subprocess
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include <cstdio>
#include <iostream>
#include <iterator>
#include <vector>
#include "hud_shader.h"
int main(){std::vector<unsigned char>b((std::istreambuf_iterator<char>(std::cin)),{});
std::printf("%d\n",hud_shader::is_sprite(b.empty()?nullptr:b.data(),b.size())?1:0);}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='hud-shader-') as tmp:
        w = Path(tmp)
        (w / 'h.cpp').write_text(HARNESS)
        p = subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(C),
                            str(w / 'h.cpp'), '-o', str(w / 'h')], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr[-1500:]

        def check(b, expected):
            p = subprocess.run([str(w / 'h')], input=b, capture_output=True, check=True)
            assert int(p.stdout) == expected, (len(b), p.stdout, expected)

        b = bytearray(32)
        b[:4] = b'DXBC'
        struct.pack_into('<Q', b, 4, 0xA1B772527CEA5742)
        struct.pack_into('<I', b, 24, len(b))
        check(b, 1)
        check(b'', 0)
        check(b[:31], 0)
        check(b + b'0', 0)
        wrong = bytearray(b)
        wrong[4] ^= 1
        check(wrong, 0)
        wrong = bytearray(b)
        wrong[:4] = b'nope'
        check(wrong, 0)
        real = C.parent / 'runtime/hud-evidence'
        tested = 0
        for name, expected in [('ps_1888250464.dxbc', 1), ('ps_1794286272.dxbc', 0), ('ps_1753208400.dxbc', 0)]:
            p = real / name
            if p.exists():
                check(p.read_bytes(), expected)
                tested += 1
        print(json.dumps({'passed': True, 'synthetic': 6, 'real_shaders': tested}))


if __name__ == '__main__':
    try:
        main()
    except (AssertionError, subprocess.SubprocessError) as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        raise SystemExit(1)
