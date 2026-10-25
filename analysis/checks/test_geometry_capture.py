#!/usr/bin/env python3
"""Offline test for geometry_capture.h + input_layout_hook.h under an isolated Wine prefix.
Verifies raw vertex/index readback matches the uploaded bytes and the CreateInputLayout hook
recovered the vertex format (semantics/formats/offsets)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
OUT = C.parent / 'runtime' / 'geometry-capture'


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    exe = work / 'mock.exe'
    subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-municode',
                    '-static', '-I', str(C), str(C / 'geometry_capture_mock_game.cpp'),
                    '-o', str(exe), '-ld3d11'], check=True)
    p = subprocess.run(['wine', str(exe)], cwd=work, capture_output=True, text=True, timeout=180)
    (work / 'wine.log').write_text(p.stdout + p.stderr)
    # The mock game writes its files and prints the marker before ExitProcess. This Wine/wined3d build
    # SIGKILLs the process (exit 137) during device teardown AFTER the capture is complete, so the marker
    # + output files are the pass condition, not the exit code.
    assert 'draw capture written' in (p.stdout or ''), f'capture did not complete (rc={p.returncode}): {(p.stderr or "")[-500:]}'

    assert (work / 'capture_vb.bin').read_bytes() == (work / 'expected_vb.bin').read_bytes(), 'VB readback mismatch'
    assert (work / 'capture_ib.bin').read_bytes() == (work / 'expected_ib.bin').read_bytes(), 'IB readback mismatch'
    assert (work / 'capture_cb.bin').read_bytes() == (work / 'expected_cb.bin').read_bytes(), 'VS CB readback mismatch'
    meta = json.loads((work / 'capture.json').read_text())
    assert meta['index_count'] == 3 and meta['start_index'] == 0 and meta['base_vertex'] == 0 and meta['instanced'] == 0
    assert meta['vb_bytes'] == 96 and meta['ib_bytes'] == 6 and meta['vs_cbs'] == 1 and meta['cb_bytes'] == 64
    assert meta['layout_found'] == 1 and meta['layout_elements'] == 3
    els = meta['layout']
    assert [(e['semantic'], e['format'], e['offset']) for e in els] == [
        ('POSITION', 6, 0), ('NORMAL', 6, 12), ('TEXCOORD', 16, 24)]
    receipt = {'passed': True, 'draw': {'index_count': meta['index_count'], 'start_index': meta['start_index']},
               'vb_bytes': meta['vb_bytes'], 'ib_bytes': meta['ib_bytes'], 'vs_cb_bytes': meta['cb_bytes'],
               'layout': els, 'ib_format_R16_UINT': True,
               'wine_exit_code': p.returncode,
               'limits': 'Wine/wined3d readback + CreateInputLayout + DrawIndexed hooks only; no game, no world-matrix semantics. '
                         'Wine SIGKILLs at device teardown (after capture) — output files verified, exit code not trusted.'}
    (OUT / 'validation.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


def main():
    if sys.argv[1:] == ['--inside']:
        return inside()
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    env = os.environ.copy()
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               WINEDLLOVERRIDES='winemenubuilder.exe=d;mscoree,mshtml=')
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1280x720x24', sys.executable, str(Path(__file__).resolve()),
                    '--inside'], env=env, cwd=OUT, check=True)


if __name__ == '__main__':
    main()
