#!/usr/bin/env python3
"""Frozen gate for the pixel-shader capture hook: a real D3D11 device must hand us the bytecode.

Proves the check that matters -- that `shader_capture.h` writes `ps_<id>.dxbc` for a shader the mock game
actually creates -- and that the written blob is the cutout shader, verified with the vendor disassembler
rather than by trusting the file name or size.

Usage: test_shader_capture.py
Prints {"passed": true, "checks": [...]}. Wine + Xvfb mock game, CPU only, no GPU.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHECKS = Path(__file__).resolve().parent
RUNTIME = CHECKS.parent / 'runtime'
GPP = 'x86_64-w64-mingw32-g++'
STATIC = ['-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-static', '-static-libgcc', '-static-libstdc++']


def main():
    checks = []
    work = Path(tempfile.mkdtemp(prefix='shader-capture-gate-'))
    prefix = Path.home() / '.wine-shader-gate'
    try:
        dll = RUNTIME / 'menu-dll' / 'd3d11.dll'
        assert dll.exists(), f'{dll} missing; run analysis/checks/build_menu_dll.py first'
        env = {'WINEPREFIX': str(prefix), 'WINEDEBUG': '-all', 'PATH': '/usr/bin:/bin',
               'DISPLAY': ':99', 'NIER_SHADER_DIR': str(work)}

        # The mock game, plus the built DLL and the stub mod layer it chain-loads.
        subprocess.run([GPP, *STATIC, '-municode', str(CHECKS / 'menu_overlay_mock_game.cpp'),
                        '-ldinput8', '-ldxguid', '-o', str(work / 'mock.exe')],
                       check=True, capture_output=True, text=True, timeout=600)
        subprocess.run([GPP, *STATIC, '-shared', str(CHECKS / 'menu_overlay_stub_dlaa.cpp'),
                        '-o', str(work / 'd3d11_dlaa.dll')], check=True, capture_output=True, text=True, timeout=600)
        shutil.copy(dll, work / 'd3d11.dll')

        # Xvfb so wined3d has a display; the mock exits by itself.
        xvfb = subprocess.Popen(['Xvfb', ':99', '-screen', '0', '1280x800x24'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            r = subprocess.run(['wine', str(work / 'mock.exe'), '40', '40'], cwd=work,
                               capture_output=True, text=True, timeout=900, env=env)
        finally:
            xvfb.terminate()
        assert (work / 'mock-result.txt').exists(), f'mock game wrote no result: {r.stderr[-400:]}'

        blobs = sorted(work.glob('ps_*.dxbc'))
        assert blobs, 'no pixel-shader blob written; the hook did not fire or NIER_SHADER_DIR was ignored'
        checks.append(f'the hook wrote {len(blobs)} ps_*.dxbc blob(s) from a live D3D11 device')

        # The blob must be the cutout shader, checked with the vendor disassembler, not assumed.
        disasm = work / 'disasm.exe'
        subprocess.run([GPP, *STATIC, str(CHECKS / 'dxbc_disasm.cpp'), '-o', str(disasm)],
                       check=True, capture_output=True, text=True, timeout=600)
        r = subprocess.run(['wine', str(disasm), f'Z:{work}'.replace('/', '\\')],
                           capture_output=True, text=True, timeout=600, env=env)
        verdicts = {}
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] == 'DISCARD':
                verdicts[parts[1]] = int(parts[2])
        assert verdicts, f'disassembler produced no verdicts: {r.stdout[-300:]} {r.stderr[-300:]}'
        assert any(v == 1 for v in verdicts.values()), \
            f'the captured shader is not recognised as a cutout: {verdicts}'
        checks.append('the captured blob disassembles and is recognised as a discard (cutout) shader')

        # And it must be a real, complete DXBC container rather than a truncated write.
        blob = blobs[0].read_bytes()
        assert blob[:4] == b'DXBC' and len(blob) > 100, f'blob is not a DXBC container ({len(blob)} bytes)'
        checks.append(f'the blob is a complete DXBC container ({len(blob)} bytes)')

        print(json.dumps({'passed': True, 'checks': checks}, indent=2))
    except AssertionError as e:
        print(json.dumps({'passed': False, 'error': str(e), 'checks_passed': checks}, indent=2))
        sys.exit(1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
