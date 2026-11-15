#!/usr/bin/env python3
"""Frozen gate: P1 upscaler persistence, precedence, failed key, live menu pick and Config-after-write.

Same Wine mock + recording fake runtime as test_upscaler_live.py. The menu row's button rectangles are read from
the proxy's own log in a first no-click run, then the mock clicks one of them (the mock clicks once, at frame 50,
after Insert opens the panel at frame 30).
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
sys.path.insert(0, str(C))
import test_menu_overlay as tmo  # noqa: E402
import test_nscn_scene as ts  # noqa: E402  (NSCN writer)

OUT = A / 'runtime' / 'upscaler-menu'  # own suite lane and own warm Wine prefix (test_upscaler_live uses menu-overlay/wine)
GPP = ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-static',
       '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor')]
KEYS = ['NIER_REMIX', 'NIER_REMIX_RUNTIME', 'NIER_REMIX_SCENE', 'NIER_REMIX_LIVE_UPSCALER', 'FAKE_REMIX_NO_CONFIG',
        'FAKE_REMIX_CONFIG_FAIL', 'MOCK_FRAME_MS', 'MOCK_UPSCALER_KEY']
RENDER_INI = b'[Rendering]\r\nPreset=Custom75\r\n'
NAMES = ['config', 'ultra-performance', 'performance', 'balanced', 'quality']


def trio(value):
    return [('rtx.dlssPreset', '2'), ('rtx.qualityDLSS', value), ('rtx.xess.preset', value)]


def config_calls(fake):
    out = []
    for line in (fake or '').splitlines():
        if line.startswith('SetConfigVariable '):
            _, key, value = line.split(' ', 2)
            if key != 'REFUSED':  # the fake's refusal record, not an accepted write
                out.append((key, value))
    return out


def check():
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / 'wine' / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'wine' / 'xdg').chmod(0o700)
    os.environ.update(WINEPREFIX=str(OUT / 'wine/prefix'), HOME=str(OUT / 'wine/home'),
                      XDG_CACHE_HOME=str(OUT / 'wine/cache'),
                      XDG_RUNTIME_DIR=str(OUT / 'wine/xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='',
                      LIBGL_ALWAYS_SOFTWARE='1',
                      WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    tmo.build(work)
    built = subprocess.run([*GPP, '-shared', str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9',
                            '-o', str(work / 'fake_remix.dll')], capture_output=True, text=True)
    assert built.returncode == 0, 'fake runtime build:\n' + built.stderr[-2000:]
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
    live = {'NIER_REMIX': '1', 'NIER_REMIX_RUNTIME': 'Z:' + str(work / 'fake_remix.dll').replace('/', '\\'),
            'NIER_REMIX_SCENE': 'Z:' + str(scene / 'scene.bin').replace('/', '\\'), 'MOCK_FRAME_MS': '40'}

    def scenario(name, extra, saved=None, click=(0, 0)):
        for key in KEYS:
            os.environ.pop(key, None)
        os.environ.update({**live, **extra})
        files = {'NIER_REMIX.ini': saved} if saved is not None else None
        try:
            d, result, log = tmo.scenario(work, name, RENDER_INI, True, click, files=files)
        finally:
            for key in KEYS:
                os.environ.pop(key, None)
        fake = (d / 'fake-remix.log').read_text() if (d / 'fake-remix.log').exists() else None
        assert (d / 'NIER_RENDER.ini').read_bytes() == RENDER_INI, f'{name}: NIER_RENDER.ini changed'
        saved_now = (d / 'NIER_REMIX.ini').read_bytes() if (d / 'NIER_REMIX.ini').exists() else None
        return log, fake, saved_now

    # 1. Saved relaunch: NIER_REMIX.ini alone selects the mode at startup.
    log, fake, _ = scenario('saved-performance', {}, b'upscaler = performance\r\n')
    assert config_calls(fake) == trio('1'), config_calls(fake)

    # 2. Precedence: the environment beats the saved file.
    log, fake, _ = scenario('env-over-saved', {'NIER_REMIX_LIVE_UPSCALER': 'balanced'}, b'upscaler = performance\r\n')
    assert config_calls(fake) == trio('2'), config_calls(fake)

    # 3. Invalid saved value: nothing written, the value is named, the file is left for the user to see.
    log, fake, saved = scenario('saved-invalid', {}, b'upscaler = turbo\r\n')
    assert config_calls(fake) == [], config_calls(fake)
    assert 'upscaler selection' in log.lower() and 'turbo' in log, 'invalid saved value not reported'
    assert saved == b'upscaler = turbo\r\n', 'invalid saved file rewritten at startup'

    # 4. Refused Custom preset: the quality writes would be silently overridden, so none are sent and it is logged.
    log, fake, _ = scenario('preset-refused', {'NIER_REMIX_LIVE_UPSCALER': 'quality',
                                                'FAKE_REMIX_CONFIG_FAIL': 'rtx.dlssPreset'})
    assert config_calls(fake) == [], f'quality written after the preset was refused: {config_calls(fake)}'
    assert 'SetConfigVariable REFUSED rtx.dlssPreset' in (fake or ''), fake
    assert re.search(r'upscaler selection .*rtx\.dlssPreset.*refused', log), 'refusal not logged by the proxy'
    # Review 25271ddb finding 3: the row must not show a mode that never applied.
    assert 'remix: upscaler now quality' not in log, 'refused mode reported as current'
    assert 'remix: upscaler now config' in log, 'current mode after a refusal not reported'

    # Finding 7: "config" in the environment is a valid choice (send nothing), not a rejected value.
    log, fake, _ = scenario('env-config', {'NIER_REMIX_LIVE_UPSCALER': 'config'}, b'upscaler = quality\r\n')
    assert config_calls(fake) == [], config_calls(fake)
    assert 'rejected' not in log, 'env config logged as rejected'
    assert 'remix: upscaler now config' in log, log[-600:]

    # A failed quality key is not a successfully applied mode, even if Custom was accepted.
    log, fake, _ = scenario('quality-refused', {'NIER_REMIX_LIVE_UPSCALER': 'quality',
                                               'FAKE_REMIX_CONFIG_FAIL': 'rtx.qualityDLSS'})
    assert 'SetConfigVariable REFUSED rtx.qualityDLSS' in (fake or ''), fake
    assert 'remix: upscaler now quality' not in log, 'partially refused mode reported as applied'
    assert config_calls(fake) == [('rtx.dlssPreset', '2')], 'writes continued after first refused quality key'
    assert 'partial override' in log and 'restart' in log, 'partial override recovery not reported'

    # 5. The live row: rectangles are published once, one per mode, in display order.
    log, fake, _ = scenario('row-geometry', {})
    rows = re.findall(r'menu: upscaler row (\S+) (-?\d+),(-?\d+),(-?\d+),(-?\d+)', log)
    assert [r[0] for r in rows[:5]] == NAMES, f'row geometry not logged in order: {rows[:5]}'
    rect = {r[0]: tuple(int(v) for v in r[1:]) for r in rows[:5]}
    assert config_calls(fake) == [], 'opening the panel wrote config'

    def centre(name):
        x0, y0, x1, y1 = rect[name]
        assert x1 > x0 and y1 > y0, (name, rect[name])
        return (x0 + x1) // 2, (y0 + y1) // 2

    # 6. Click Quality: applied live by the worker and saved for next launch; nothing else written.
    log, fake, saved = scenario('pick-quality', {}, click=centre('quality'))
    assert config_calls(fake) == trio('3'), config_calls(fake)
    assert saved is not None and re.search(rb'^upscaler\s*=\s*quality\s*$', saved, re.M), saved
    assert 'menu: upscaler quality requested' in log, log[-800:]
    assert 'remix: upscaler now quality' in log, 'applied mode not reported as current'

    # Finding 5: with the environment overriding the file, the saved pick will not apply next launch; say so.
    log, fake, saved = scenario('pick-under-env', {'NIER_REMIX_LIVE_UPSCALER': 'balanced'}, click=centre('quality'))
    assert config_calls(fake) == trio('2') + trio('3'), config_calls(fake)
    assert 'menu: upscaler quality requested queued=1 saved=1 env_override=1' in log, log[-800:]

    # Keyboard after mouse focus: Left from Quality, Enter -> Balanced (not just a decorative button highlight).
    log, fake, saved = scenario('keyboard-balanced', {'MOCK_UPSCALER_KEY': '1'}, click=centre('quality'))
    assert config_calls(fake) == trio('3') + trio('2'), ('keyboard selection', config_calls(fake))
    assert saved is not None and re.search(rb'^upscaler\s*=\s*balanced\s*$', saved, re.M), saved

    # 7. Back to Config after a live write: nothing is sent (no runtime "reset" exists), restart is stated, saved.
    log, fake, saved = scenario('pick-config', {}, b'upscaler = quality\r\n', click=centre('config'))
    assert config_calls(fake) == trio('3'), f'Config sent writes: {config_calls(fake)}'
    assert 'restart' in log.lower() and 'upscaler' in log.lower(), 'restart requirement not stated'
    assert saved is not None and not re.search(rb'quality', saved), saved
    assert 'remix: upscaler now config' not in log, 'Config shown as effective before restart'



def main():
    # Same display handling as test_remix_live.py: wine needs a display; the suite shim gives each lane its own.
    if sys.argv[1:] == ['--inside'] or os.environ.get('DISPLAY'):
        return check()
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable,
                    str(Path(__file__).resolve()), '--inside'], check=True, cwd=C)


if __name__ == '__main__':
    try:
        main()
        print(json.dumps({'passed': True}))
    except (Exception, SystemExit) as exc:
        error = f'candidate exited early: {exc.code}' if isinstance(exc, SystemExit) else str(exc)
        print(json.dumps({'passed': False, 'error': error[:1500]}))
        sys.exit(1)
