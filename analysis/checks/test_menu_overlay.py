#!/usr/bin/env python3
"""Offline end-to-end test of the in-game menu in the real proxy DLL, under an isolated Wine prefix + Xvfb.
A mock game loads the built d3d11.dll; a stub d3d11_dlaa.dll stands in for the existing mod layer and
hooks the same vtable slots first. Never touches the game folder or any other Wine prefix.
Scenarios: repair (invalid INI: Insert opens the panel, a click on Save repairs the file) and
no-fonts (overlay disables itself; frames still flow through every layer)."""
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime' / 'menu-overlay'
DLL = A / 'runtime' / 'menu-dll'
BACKGROUND, SURFACE = (29, 36, 34), (232, 227, 211)


def pixel(raw, x, y):
    width, height, fmt = struct.unpack_from('<3I', raw, 0)
    assert fmt == 28, fmt  # DXGI_FORMAT_R8G8B8A8_UNORM
    o = 12 + (y * width + x) * 4
    return tuple(raw[o:o + 3])


def near(a, b):
    return all(abs(x - y) <= 2 for x, y in zip(a, b))


def save_button_center():
    receipt = json.loads((A / 'runtime/menu-preview/render-validation.json').read_text())
    metrics = json.loads((A.parent / receipt['directory'] / 'invalid-file-1920x1080-1x/metrics.json').read_text())
    x0, y0, x1, y1 = metrics['save']
    return int((x0 + x1) / 2), int((y0 + y1) / 2)


def build(work):
    assert subprocess.run([sys.executable, str(C / 'build_menu_dll.py')], capture_output=True).returncode == 0, 'DLL build'
    gpp = ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-static', '-static-libgcc',
           '-static-libstdc++']
    subprocess.run([*gpp, '-shared', str(C / 'menu_overlay_stub_dlaa.cpp'), '-o', str(work / 'd3d11_dlaa.dll')], check=True)
    subprocess.run([*gpp, '-municode', str(C / 'menu_overlay_mock_game.cpp'), '-o', str(work / 'mock.exe')], check=True)  # D3DCompile loaded at runtime


def scenario(work, name, ini, fonts, click):
    d = work / name
    d.mkdir()
    for f in ('mock.exe', 'd3d11_dlaa.dll'):
        shutil.copy2(work / f, d / f)
    shutil.copy2(DLL / 'd3d11.dll', d / 'd3d11.dll')
    if fonts:
        shutil.copytree(DLL / 'nier_render_fonts', d / 'nier_render_fonts')
    (d / 'NIER_RENDER.ini').write_bytes(ini)
    p = subprocess.run(['wine', str(d / 'mock.exe'), str(click[0]), str(click[1])], cwd=d, capture_output=True,
                       text=True, timeout=180)
    (d / 'wine.log').write_text(p.stdout + p.stderr)
    assert p.returncode == 0, f'{name}: exit {p.returncode}, see {d}'
    result = dict(kv.split('=', 1) for line in (d / 'mock-result.txt').read_text().split()
                  for kv in [line] if '=' in kv)
    log = (d / 'NIER_SCALE.log').read_text(errors='replace') if (d / 'NIER_SCALE.log').exists() else ''
    return d, result, log


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    build(work)
    x0, y0 = 1920 - 32 - 552, 32  # panel at scale 1 (backbuffer height 1080)
    results = {}
    try:
        d, r, log = scenario(work, 'repair', b'[Rendering]\r\nPreset=Quality\r\n', True, save_button_center())
        assert r['presented'] == '80' and r['stub_presents'] == '80', r          # chain: menu -> stub -> Wine
        assert r['cs_lost'] == '0', r  # game pipeline state survives the overlay draw
        assert 'menu: ready' in log and 'hook Present slot 8 -> 0' in log, log
        assert 'menu: cursor released (panel open)' in log, log  # cursor capture is freed on open
        closed, opened = (d / 'capture-closed.raw').read_bytes(), (d / 'capture-open.raw').read_bytes()
        assert near(pixel(closed, x0 + 10, y0 + 20), BACKGROUND), pixel(closed, x0 + 10, y0 + 20)
        assert near(pixel(opened, x0 + 10, y0 + 20), SURFACE), pixel(opened, x0 + 10, y0 + 20)
        assert (d / 'NIER_RENDER.ini').read_bytes() == b'[Rendering]\r\nPreset=Native\r\n'
        assert 'menu: save Native -> outcome=0' in log, log
        results['repair'] = {'passed': True, 'foreground': r['foreground'], 'dir': str(d.relative_to(A.parent))}

        d, r, log = scenario(work, 'no-fonts', b'[Rendering]\r\nPreset=Custom75\r\n', False, (0, 0))
        assert r['presented'] == '80' and r['stub_presents'] == '80', r
        assert 'menu: disabled (fonts)' in log, log
        assert near(pixel((d / 'capture-open.raw').read_bytes(), x0 + 10, y0 + 20), BACKGROUND)
        assert (d / 'NIER_RENDER.ini').read_bytes() == b'[Rendering]\r\nPreset=Custom75\r\n'
        results['no-fonts'] = {'passed': True, 'dir': str(d.relative_to(A.parent))}
    except Exception as error:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(error)[:2000],
                                                         'results': results, 'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    receipt = {'passed': True, 'results': results, 'dll_sha256': json.loads((DLL / 'validation.json').read_text())['sha256'],
               'limits': 'Wine/wined3d + Xvfb mock game with a stub mod layer; not NieR, DXVK, WAX, Proton or native Windows'}
    (OUT / 'validation.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


def main():
    if sys.argv[1:] == ['--inside']:
        return inside()
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    assert not (OUT / 'prefix').is_symlink()
    env = os.environ.copy()
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 2560x1440x24', sys.executable, str(Path(__file__).resolve()),
                    '--inside'], env=env, cwd=OUT, check=True)


if __name__ == '__main__':
    main()
