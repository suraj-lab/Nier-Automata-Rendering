#!/usr/bin/env python3
"""Frozen gate: while the game draws no world (a loading screen), the game's own frame is shown, not the last Remix image.

Live 2026-11-04 (frametime2): a fast travel drew no scene for 16 s (928 game frames, no Remix frame submitted), and
the path-traced transporter room stayed on screen behind the loading text, because the Present hook composites the
newest Remix frame however old it is.

What this gate pins (mock, fake Remix that renders a flat (200,40,120)):
  - load: 18 frames with no 3D draws. Two frames before the world returns the screen is the game's own background,
    and after it returns Remix is composited again. The log says when the world went and when it came back.
  - short: a 6-frame gap is not a load. Neither is an empty frame every 10 frames. Both keep compositing and log
    nothing, so a threshold of one empty frame (a flickering picture) fails here.

Software mocks only: this pins the rule, not NieR's real loading screens.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-world-gone'
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'MOCK_LOAD')


def probe(d, name):
    return tr.rgb((d / name).read_bytes(), *tr.PROBE)


def notes(log):
    return [x for x in tr.remix_lines(log) if x.startswith('remix: world ')]


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    results = {}
    try:
        tmo.build(work)
        subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                        str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
        scene = work / 'scene'
        (scene / 'scene_textures').mkdir(parents=True)
        (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
        tex = work / 'live-textures'
        tex.mkdir()
        base = {'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'), 'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'),
                'MOCK_FRAME_MS': '40', 'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex),
                'MOCK_CAMERA': 'live'}

        # A loading screen: frames 26..43 draw nothing in 3D; frame 42 is captured.
        d, r, log, fake = tr.run(work, 'load', {**base, 'MOCK_LOAD': '26,44'})
        assert fake and 'VIOLATION' not in fake, fake
        assert tmo.near(probe(d, 'capture-load.raw'), tr.BACKGROUND), \
            f'loading screen: the last Remix image stayed on screen instead of the game frame: {probe(d, "capture-load.raw")}'
        assert tmo.near(probe(d, 'capture-after.raw'), tr.REMIX), \
            f'after the load Remix must be composited again: {probe(d, "capture-after.raw")}'
        n = notes(log)
        assert len(n) == 2 and n[0].startswith('remix: world gone') and n[1].startswith('remix: world back'), n
        results['load'] = 'No world for 18 frames: the game frame is shown, then Remix again; both transitions logged.'

        # Not a load: a 6-frame gap (frame 30 captured inside it) and single empty frames every 10 frames.
        d, r, log, fake = tr.run(work, 'short', {**base, 'MOCK_LOAD': '26,32'})
        assert tmo.near(probe(d, 'capture-load.raw'), tr.REMIX), \
            f'a 6-frame gap must not drop Remix: {probe(d, "capture-load.raw")}'
        assert not notes(log), notes(log)
        d, r, log, fake = tr.run(work, 'scattered', {**base, 'MOCK_EMPTY_EVERY': '10'})
        assert tmo.near(probe(d, 'capture-after.raw'), tr.REMIX), probe(d, 'capture-after.raw')
        assert not notes(log), notes(log)
        results['short'] = 'A 6-frame gap and scattered empty frames keep Remix on screen and log nothing.'
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-3000:], 'results': results,
                                                         'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results,
              'dll_sha256': hashlib.sha256((tmo.DLL / 'd3d11.dll').read_bytes()).hexdigest(),
              'limits': 'Software-only Wine mock, fake Remix; real loading screens still need one live look.'}
    (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def main():
    if sys.argv[1:] == ['--inside']:
        return inside()
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    assert not (OUT / 'prefix').is_symlink()
    env = os.environ.copy()
    for k in tr.ENV_KEYS:
        env.pop(k, None)
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               GALLIUM_DRIVER='llvmpipe', WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable, str(Path(__file__).resolve()), '--inside'],
                   cwd=OUT, env=env, check=True)


if __name__ == '__main__':
    main()
