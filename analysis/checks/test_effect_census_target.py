#!/usr/bin/env python3
"""Frozen E1.1b gate: the effect census says whether an effect draw's RT0 resource is the native-HUD handoff target.

Live 2026-11-14 (`e1-census-camp-live`): effects draw into R11G11B10 3440x1440 targets, the same format/size as the
HUD target. Whether it is the SAME resource decides the composite colour space (after vs before tone mapping).
Each census record gains "rt_resource" (hex pointer, session-local identity only) and "hud_target_resource" (the
handoff target last identified by the native-HUD path, "0x0" before any). Default census output stays opt-in.
"""
import json
import re
import os
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime' / 'effect-census-target'
sys.path.insert(0, str(C))
import test_menu_overlay as tmo
import test_nscn_scene as ts


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    fixture = A / 'runtime/hud-evidence/ps_1888250464.dxbc'
    assert fixture.is_file(), 'native HUD fixture unavailable; gate not exercised'
    tmo.build(work)
    r = subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-static',
                        '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                        str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake.dll')], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
    win = lambda p: 'Z:' + str(p).replace('/', '\\')
    results, logs = {}, {}
    for name, into_hud in [('scene-target', False), ('hud-target', True)]:
        saved = os.environ.copy()
        try:
            for key in list(os.environ):
                if key.startswith(('NIER_', 'MOCK_', 'FAKE_')): os.environ.pop(key)
            tex = work / (name + '-tex'); tex.mkdir()
            os.environ.update({'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_RUNTIME': win(work / 'fake.dll'),
                               'NIER_REMIX_SCENE': win(scene / 'scene.bin'), 'MOCK_FRAME_MS': '40', 'NIER_REMIX_LIVE_TEX': win(tex),
                               'MOCK_CAMERA': 'live-native-hud', 'MOCK_NATIVE_HUD_PS': win(fixture),
                               'MOCK_EFFECT_REGISTER': '27', 'MOCK_EFFECT_SMALL': '1', 'NIER_REMIX_LIVE_EFFECT_CENSUS': '1'})
            if into_hud: os.environ['MOCK_EFFECT_INTO_HUD'] = '1'
            _, result, log = tmo.scenario(work, name, b'[Rendering]\r\nPreset=Custom75\r\n', True, (0, 0))
        finally:
            os.environ.clear(); os.environ.update(saved)
        assert result.get('presented') == '80', result
        assert 'native HUD handoff' in log, 'handoff not exercised'
        rows = [json.loads(l.split('remix: effect-census ', 1)[1]) for l in log.splitlines() if 'remix: effect-census {' in l]
        assert rows, f'{name}: no census rows'
        for row in rows:
            assert isinstance(row.get('rt_resource'), str) and row['rt_resource'].startswith('0x'), 'rt_resource missing'
            assert isinstance(row.get('hud_target_resource'), str) and row['hud_target_resource'].startswith('0x'), 'hud_target_resource missing'
        known = [r for r in rows if r['hud_target_resource'] != '0x0']
        assert known, f'{name}: HUD target never identified for census rows'
        results[name] = known
        logs[name] = log
    scene_rows = results['scene-target']
    assert all(r['rt_resource'] != r['hud_target_resource'] for r in scene_rows), 'scene-target effect reported as HUD target'
    hud_rows = [r for r in results['hud-target'] if r['rt']['format'] == 26]
    assert hud_rows, 'effect drawn into the R11G11B10 HUD target was not censused'
    assert all(r['rt_resource'] == r['hud_target_resource'] for r in hud_rows), 'HUD-target effect not identified as HUD target'
    assert len({r['hud_target_resource'] for r in hud_rows}) >= 1
    # v2 (live e1-census-camp-live-2: census cap was spent 55 s before the first handoff, so no row knew the HUD
    # target): the handoff path itself logs each newly seen HUD target pointer, bounded to 8 lines per session.
    for name in results:
        logged = re.findall(r'remix: native HUD target (0x[0-9a-f]+) change (\d+)', logs[name])
        assert logged, f'{name}: HUD target pointer not logged'
        assert len(logged) <= 8, 'unbounded HUD target log'
        assert {p for p, _ in logged} >= {r['hud_target_resource'] for r in results[name]}, 'logged HUD target differs from census'


def main():
    if sys.argv[1:] == ['--inside']:
        return inside()
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    env = os.environ.copy()
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               GALLIUM_DRIVER='llvmpipe', WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    try:
        subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable, str(Path(__file__).resolve()), '--inside'],
                       env=env, check=True, cwd=C)
    finally:
        subprocess.run(['wineserver', '-k'], env=env, capture_output=True)


if __name__ == '__main__':
    try:
        main(); print(json.dumps({'passed': True}))
    except (Exception, SystemExit) as exc:
        print(json.dumps({'passed': False, 'error': str(exc)[:1800]})); sys.exit(1)
