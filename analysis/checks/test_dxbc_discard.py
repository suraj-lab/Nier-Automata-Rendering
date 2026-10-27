#!/usr/bin/env python3
"""Frozen gate for shader cutout detection: compile fixtures, disassemble, find `discard`.

The capture DLL needs to tell a cutout shader (foliage, hair, grilles) from an opaque one so the
converter can set `alphaTestType` instead of guessing from texture statistics. Detecting it by parsing
DXBC opcodes by hand was tried on 2026-10-27 and abandoned: the instruction-length field is not a length
for declaration opcodes, and a plain token scan matched five different opcode values on these same
fixtures. The vendor's own decoder (d3dcompiler_47!D3DDisassemble) is the authority, so this gate pins the
end-to-end path: compile source with D3DCompile, disassemble with D3DDisassemble, and check the text.

Usage: test_dxbc_discard.py
Prints {"passed": true, "checks": [...]}. Needs mingw + wine; CPU only, no GPU context, no window.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHECKS = Path(__file__).resolve().parent
GPP = 'x86_64-w64-mingw32-g++'
STATIC = ['-O1', '-static', '-static-libgcc', '-static-libstdc++']


def build(work):
    for src, out in (('dxbc_compile.cpp', 'compile.exe'), ('dxbc_disasm.cpp', 'disasm.exe')):
        subprocess.run([GPP, *STATIC, str(CHECKS / src), '-o', str(work / out)], check=True,
                       capture_output=True, text=True, timeout=600)


def wine(work, prefix, exe, arg):
    """Wine refuses a prefix under a directory it does not own (/tmp is root-owned), so the prefix lives
    in $HOME -- that cost a debugging round on 2026-10-27."""
    env = {'WINEPREFIX': str(prefix), 'WINEDEBUG': '-all', 'PATH': '/usr/bin:/bin'}
    return subprocess.run(['wine', str(work / exe), arg], capture_output=True, text=True,
                          timeout=600, env=env, cwd=work)


def main():
    checks = []
    work = Path(tempfile.mkdtemp(prefix='dxbc-gate-'))
    prefix = Path.home() / '.wine-dxbc-gate'
    try:
        assert shutil.which('wine'), 'wine not installed'
        assert shutil.which(GPP), f'{GPP} not installed'
        build(work)
        out = work / 'out'
        out.mkdir()

        # 1. Compile three fixtures: opaque, one discard, two discards.
        r = wine(work, prefix, 'compile.exe', f'Z:{out}'.replace('/', '\\'))
        assert r.returncode == 0, f'dxbc_compile failed rc={r.returncode}: {r.stderr[-400:]}'
        blobs = sorted(p.name for p in out.glob('*.dxbc'))
        assert blobs == ['cutout.dxbc', 'cutout2.dxbc', 'opaque.dxbc'], f'unexpected fixtures: {blobs}'
        checks.append('three fixtures compiled with D3DCompile (opaque, 1 discard, 2 discards)')

        # 2. Disassemble and check the classification.
        r = wine(work, prefix, 'disasm.exe', f'Z:{out}'.replace('/', '\\'))
        assert r.returncode == 0, f'dxbc_disasm failed rc={r.returncode}: {r.stderr[-400:]}'
        verdicts = {}
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] == 'DISCARD':
                verdicts[parts[1]] = int(parts[2])
        assert verdicts == {'opaque': 0, 'cutout': 1, 'cutout2': 1}, f'classification wrong: {verdicts}'
        checks.append('opaque is not a cutout, both discard shaders are')

        # 3. The signal itself: the disassembly text contains the instruction once per discard.
        counts = {}
        for name in ('opaque', 'cutout', 'cutout2'):
            asm = (out / f'{name}.asm')
            assert asm.exists(), f'{asm.name} not written'
            counts[name] = asm.read_text(errors='replace').count('discard')
        assert counts == {'opaque': 0, 'cutout': 1, 'cutout2': 2}, f'discard token counts wrong: {counts}'
        checks.append('disassembly contains discard 0/1/2 times, matching the source')

        # 4. A file that is not a shader must be refused, not silently reported as opaque.
        (out / 'junk.dxbc').write_bytes(b'not a shader at all')
        r = wine(work, prefix, 'disasm.exe', f'Z:{out}'.replace('/', '\\'))
        assert r.returncode != 0, 'garbage input was accepted'
        assert 'disassemble failed' in r.stderr or 'disassemble failed' in r.stdout, \
            f'garbage input failed without a reason: {r.stderr[-300:]}'
        checks.append('garbage input exits non-zero with a reason')

        print(json.dumps({'passed': True, 'checks': checks}, indent=2))
    except AssertionError as e:
        print(json.dumps({'passed': False, 'error': str(e), 'checks_passed': checks}, indent=2))
        sys.exit(1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
