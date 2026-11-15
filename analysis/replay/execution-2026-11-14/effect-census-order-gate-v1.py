#!/usr/bin/env python3
"""Frozen E1.3b gate: effect census records the draw order relative to the native-HUD handoff.

Live e1-handoff-at-effect-1: the at-effect trigger never fired. Hypothesis: the game draws its 4 display-space effect
quads AFTER the first HUD sprite, so they already blend over Remix. Census records gain "after_hud_handoff" (the
native handoff already happened in this frame when the effect was sampled). NIER_REMIX_LIVE_EFFECT_CENSUS=handoff
defers sampling until the HUD target is known (run 2 spent the whole 256-record budget before the first handoff).
--- original docstring of the source gate follows ---

Live census (e1-census-camp-live-3): 4 effect quads/frame (t27 family, straight alpha, depth off) are drawn into the
display-encoded HUD target BEFORE the HUD sprites, and today's handoff (at the first sprite) erases them.
NIER_REMIX_LIVE_HANDOFF_AT_EFFECT=1 hands off at such an effect draw instead, so the game's own draw blends over the
Remix image (exact for this class: same target, same colour space). Default: unchanged.
Fixture: effect (1,0.5,0) alpha 0.5 at x 1632..1920, y ~270..900 (probe 1800,720: clear of the menu panel); sprites at the centre and x~96; Remix (200,40,120).
"""
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime' / 'effect-census-order'
sys.path.insert(0, str(C))
import test_menu_overlay as tmo
import test_nscn_scene as ts

REMIX = (200, 40, 120)
BLEND = tuple(round(0.5 * e * 255 + 0.5 * r) for e, r in zip((1, 0.5, 0), REMIX))   # (228, 84, 60)


def px(raw, x, y):
    width, height, fmt = struct.unpack_from('<3I', raw)
    o = 12 + (y * width + x) * 4
    c = raw[o:o + 3]
    return tuple(c[::-1]) if fmt in (87, 91) else tuple(c)


def near(a, b, tol=12):
    return max(abs(x - y) for x, y in zip(a, b)) <= tol


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

    def run(name, extra):
        saved = os.environ.copy()
        try:
            for key in list(os.environ):
                if key.startswith(('NIER_', 'MOCK_', 'FAKE_')): os.environ.pop(key)
            tex = work / (name + '-tex'); tex.mkdir()
            os.environ.update({'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_RUNTIME': win(work / 'fake.dll'),
                               'NIER_REMIX_SCENE': win(scene / 'scene.bin'), 'MOCK_FRAME_MS': '40', 'NIER_REMIX_LIVE_TEX': win(tex),
                               'MOCK_CAMERA': 'live-native-hud', 'MOCK_NATIVE_HUD_PS': win(fixture),
                               'MOCK_EFFECT_REGISTER': '27', 'MOCK_EFFECT_SMALL': '1'} | extra)
            d, result, log = tmo.scenario(work, name, b'[Rendering]\r\nPreset=Custom75\r\n', True, (0, 0))
        finally:
            os.environ.clear(); os.environ.update(saved)
        assert result.get('presented') == '80', (name, result)
        assert result.get('hud_state_lost') == '0' and result.get('cs_lost') == '0', (name, result)
        assert 'native HUD handoff' in log, f'{name}: handoff not exercised'
        return (d / 'capture-after.raw').read_bytes(), log

    def sprites_and_corner(raw, name):
        for point in [(960, 540), (96, 540)]:
            c = px(raw, *point)
            assert c[1] > 200 and c[0] < 60 and c[2] < 60, f'{name}: native sprite missing/erased at {point}: {c}'
        assert near(px(raw, 1900, 8), REMIX), f'{name}: corner is not the Remix image: {px(raw, 1900, 8)}'

    def rows(log):
        return [json.loads(l.split('remix: effect-census ', 1)[1]) for l in log.splitlines() if 'remix: effect-census {' in l]

    base = {'MOCK_EFFECT_INTO_HUD': '1', 'MOCK_EFFECT_COLOR': '1'}
    before, log = run('before-sprite', base | {'NIER_REMIX_LIVE_EFFECT_CENSUS': '1'})
    hud = [r for r in rows(log) if r['rt']['format'] == 26 and r['hud_target_resource'] != '0x0']
    assert hud, 'no HUD-target census rows'
    assert all(r.get('after_hud_handoff') is False for r in hud), 'effect drawn before the sprites reported after the handoff'
    assert near(px(before, 1800, 720), REMIX), 'before-sprite effect should be erased by today\'s handoff'

    after, log = run('after-sprite', base | {'NIER_REMIX_LIVE_EFFECT_CENSUS': '1', 'MOCK_EFFECT_AFTER_SPRITE': '1'})
    sprites_and_corner(after, 'after-sprite')
    hud = [r for r in rows(log) if r['rt']['format'] == 26 and r['hud_target_resource'] != '0x0']
    assert hud and all(r.get('after_hud_handoff') is True for r in hud), 'effect after the sprite handoff not reported as after'
    assert near(px(after, 1800, 720), BLEND), f'after-sprite effect should already survive today: {px(after, 1800, 720)}'

    deferred, log = run('deferred', base | {'NIER_REMIX_LIVE_EFFECT_CENSUS': 'handoff'})
    got = rows(log)
    assert got, 'deferred census produced nothing'
    assert all(r['hud_target_resource'] != '0x0' for r in got), 'deferred census sampled before the HUD target was known'
    assert all('after_hud_handoff' in r for r in got)
    _, log = run('census-off', base)
    assert not rows(log), 'census active by default'


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
