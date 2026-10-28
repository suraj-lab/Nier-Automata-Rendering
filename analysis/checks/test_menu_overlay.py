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
    subprocess.run([*gpp, '-municode', str(C / 'menu_overlay_mock_game.cpp'), '-ldinput8', '-ldxguid', '-o', str(work / 'mock.exe')], check=True)  # D3DCompile loaded at runtime


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
        # DirectInput mouse (NieR's camera path): untouched while closed, blanked while open, keyboard never blanked.
        assert 'menu: dinput mouse hook=1' in log, log
        assert r['di_mouse_closed'] == '0' and r['di_mouse_open'] == '1', r
        assert r['di_keyboard_open'] == '0' and r['di_slot9_in_proxy'] == '1', r
        closed, opened = (d / 'capture-closed.raw').read_bytes(), (d / 'capture-open.raw').read_bytes()
        assert near(pixel(closed, x0 + 10, y0 + 20), BACKGROUND), pixel(closed, x0 + 10, y0 + 20)
        assert near(pixel(opened, x0 + 10, y0 + 20), SURFACE), pixel(opened, x0 + 10, y0 + 20)
        assert (d / 'NIER_RENDER.ini').read_bytes() == b'[Rendering]\r\nPreset=Native\r\n'
        assert 'menu: save Native -> outcome=0' in log, log
        # F9 frame capture: two frames (panel closed, then open), each with exactly the one mesh draw.
        frames = sorted((d / 'NIER_CAPTURE').glob('frame_*'), key=lambda f: int(f.name[6:]))
        assert len(frames) == 2, frames
        for fr in frames:
            summary = json.loads((fr / 'frame.json').read_text())
            assert summary['draws'] == 2 and summary['written'] == 2 and summary['skipped'] == 0, (fr, summary)
            assert summary['link_fallbacks'] == 0, summary
            assert sorted(p.name for p in fr.iterdir() if p.is_dir()) == ['buffers', 'draw_0000', 'draw_0001', 'textures'], list(fr.iterdir())
            # shared static VB/IB: one file each under buffers/, hard-linked into both draws
            assert len(list((fr / 'buffers').iterdir())) == 2, list((fr / 'buffers').iterdir())
            for name in ('vb_0.bin', 'ib.bin'):
                assert os.path.samefile(fr / 'draw_0000' / name, fr / 'draw_0001' / name), name
        assert log.count('menu: frame captured') == 2, log
        # PS textures: static RGBA + BC1 written once each as DDS (DX10 header, 148 bytes); the render target is not.
        rgba = bytes((i * 7 + 3) & 0xff for i in range(64)); bc1 = bytes((i * 5 + 1) & 0xff for i in range(32))
        for fr in frames:
            summary = json.loads((fr / 'frame.json').read_text())
            assert summary['textures'] == 2 and summary['textures_written'] == 2, summary
            index = json.loads((fr / 'textures' / 'index.json').read_text())
            assert index == [{'id': 1, 'format': 28, 'width': 4, 'height': 4}, {'id': 2, 'format': 71, 'width': 8, 'height': 8}], index
            for tid, payload, fmt in ((1, rgba, 28), (2, bc1, 71)):
                dds = (fr / 'textures' / f'tex_{tid}.dds').read_bytes()
                assert dds[:4] == b'DDS ' and dds[84:88] == b'DX10' and struct.unpack_from('<I', dds, 128)[0] == fmt, tid
                assert dds[148:] == payload, (tid, dds[148:].hex(), payload.hex())
            for dname in ('draw_0000', 'draw_0001'):
                cap = json.loads((fr / dname / 'capture.json').read_text())
                assert cap['ps_textures'] == [{'slot': 0, 'id': 1}, {'slot': 2, 'id': 2}], cap['ps_textures']
        cd = frames[0] / 'draw_0000'
        cap = json.loads((cd / 'capture.json').read_text())
        assert cap['index_count'] == 192 and cap['instanced'] == 0 and cap['has_index'] == 1 and cap['ib_format'] == 57
        assert cap['vp_width'] == 64 and cap['vp_height'] == 64
        assert cap['layout_found'] == 1 and [(e['semantic'], e['offset'], e['slot']) for e in cap['layout']] == [('POSITION', 0, 0), ('COLOR', 12, 0)]
        assert cap['vs_cbs'] == [{'slot': 0, 'bytes': 64}]
        # Fixed render state, captured so a material decision never needs another game run. The mock binds
        # these deliberately; the numbers are the D3D11 enum values, not guesses -- COMPARISON_GREATER is 5
        # and CULL_FRONT is 2 (the lead's first expectations of 4 and 3 were wrong and the capture corrected
        # them). If this fails, either the getters or the JSON field order changed.
        assert cap['state'] == {'blend_enable': 1, 'src_blend': 5, 'dest_blend': 6, 'blend_op': 1,
                                'write_mask': 15, 'depth_enable': 1, 'depth_write': 0, 'depth_func': 5,
                                'cull_mode': 2, 'fill_mode': 2, 'dsv_format': 0}, cap.get('state')
        # v4: shader identity + pixel-shader constants, so a converter can group draws by shader and reach
        # per-material parameters instead of guessing the albedo slot from texture formats.
        assert cap['ps_cbs'] == [{'slot': 0, 'bytes': 64}], cap['ps_cbs']
        assert cap['vs_hash'] and cap['ps_hash'], (cap['vs_hash'], cap['ps_hash'])
        assert cap['vs_hash'] != cap['ps_hash'], 'vertex and pixel shader must not collide'
        ps_cb = (cd / 'ps_cb_0.bin').read_bytes()
        assert len(ps_cb) == 64 and ps_cb == bytes(((i * 17 + 3) & 0xff) for i in range(64)), ps_cb[:8].hex()
        # the VS buffer keeps its own name, so a shared slot cannot overwrite either file
        assert (cd / 'cb_0.bin').read_bytes() == ps_cb
        assert len((cd / 'vb_0.bin').read_bytes()) == 65 * 16 and len((cd / 'ib.bin').read_bytes()) == 192 * 2
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
