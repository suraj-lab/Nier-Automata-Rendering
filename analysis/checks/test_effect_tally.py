#!/usr/bin/env python3
"""E1 diagnostic gate: dropped t27/t30 effect draws keep their observed blend/target metadata.

The mock compiles real SM5 structured-resource shaders; the same recording fake/runtime path as the live gates
produces the production per-shader log. Reporting only: NIER_REMIX_LIVE_EFFECTS remains off.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime' / 'effect-tally'
sys.path.insert(0, str(C))
import test_menu_overlay as tmo
import test_nscn_scene as ts


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    tmo.build(work)
    gpp = ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
           '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor')]
    r = subprocess.run([*gpp, str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake.dll')],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
    def win(p):
        return 'Z:' + str(p).replace('/', '\\')
    base = {'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_RUNTIME': win(work / 'fake.dll'),
            'NIER_REMIX_SCENE': win(scene / 'scene.bin'), 'MOCK_FRAME_MS': '40',
            'NIER_REMIX_LIVE_STATS_EVERY': '2', 'NIER_REMIX_LIVE_TEX': win(work / 'textures')}
    (work / 'textures').mkdir()
    for name, extra, effect, src, dst in [
        ('opaque-negative', {'MOCK_CAMERA': 'live-blend'}, False, 5, 6),
        ('t27-straight', {'MOCK_CAMERA': 'live-blend', 'MOCK_EFFECT_REGISTER': '27'}, True, 5, 6),
        ('t30-additive', {'MOCK_CAMERA': 'live-additive', 'MOCK_EFFECT_REGISTER': '30'}, True, 2, 2),
    ]:
        saved = os.environ.copy()
        try:
            for key in list(os.environ):
                if key.startswith(('NIER_', 'MOCK_', 'FAKE_')):
                    os.environ.pop(key)
            os.environ.update(base | extra)
            _, result, log = tmo.scenario(work, name, b'[Rendering]\r\nPreset=Custom75\r\n', True, (0, 0))
        finally:
            os.environ.clear()
            os.environ.update(saved)
        assert result.get('presented') == '80', result
        rows = re.findall(r'remix: shader ps=[0-9a-f]+ draws=(\d+) tris=(\d+) blend=(on|off):(\d+)>(\d+) alpha=(\d+) effect=(\d+) rt=(\d+)', log)
        selected = [r for r in rows if (int(r[6]) > 0) == effect and int(r[0]) > 0]
        assert selected, f'{name}: no shader rows matching effect={effect}'
        assert any(r[2] == 'on' and (int(r[3]), int(r[4])) == (src, dst) and int(r[7]) == 28 for r in selected), \
            f'{name}: raw blend/target lost: {selected[-3:]}'


def main():
    if sys.argv[1:] == ['--inside']:
        return inside()
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    env = os.environ.copy()
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable, str(Path(__file__).resolve()), '--inside'],
                   env=env, check=True, cwd=C)


if __name__ == '__main__':
    try:
        main()
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)[:1500]}))
        sys.exit(1)
