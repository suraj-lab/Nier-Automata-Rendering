#!/usr/bin/env python3
"""Frozen gate: the game's HUD pass is captured for replay instead of being dropped.

The HUD is 56 alpha-blended sprite draws into the final image. The scene filter correctly keeps them out of the world,
which is why the HUD is missing from the pathtraced picture. This gate pins the first half of the fix: those draws are
recognised and captured with their transform and texture, separately from the world scene.

What it pins:
  - with the mock drawing an indexed, alpha-blended quad into the backbuffer (live-hud), the capture reports hud > 0;
  - the two scene geometries are still captured (the HUD pass does not replace them);
  - in a run with no HUD draws (`live`), hud stays 0 — so the counter cannot pass by accident.

Not pinned yet: the replay itself (drawing the captured quads over the Remix image). That needs the composite capture
hook and a pixel probe; until then this gate only proves capture.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-hud'
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'FAKE_REMIX_INSTANCE_LOG',
                                     'NIER_REMIX_CAPTURE_COMPOSITE')


def hud_counts(log):
    out = []
    for line in tr.remix_lines(log):
        if 'live draws=' in line:
            m = re.search(r'hud=(\d+)', line)
            if m:
                out.append(int(m.group(1)))
    return out


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
                'FAKE_REMIX_INSTANCE_LOG': '1'}

        composite = work / 'composite.raw'
        _, r, log, fake = tr.run(work, 'hud', {**base, 'MOCK_CAMERA': 'live-hud',
                                              'NIER_REMIX_CAPTURE_COMPOSITE': tr.win(composite)})
        assert fake and 'VIOLATION' not in fake, fake
        counts = hud_counts(log)
        assert counts, f'the stats line never reported hud=; did the build change? {tr.remix_lines(log)[-4:]}'
        assert max(counts) > 0, f'the HUD pass was dropped, not captured: hud={counts[-1]}'
        draws = [int(m.group(1)) for line in tr.remix_lines(log) if 'live draws=' in line
                 for m in [re.search(r'draws=(\d+)', line)] if m]
        assert draws and max(draws) > 0, f'the scene disappeared: draws={draws[-3:]}'
        results['captured'] = 'HUD draws are captured while the scene keeps drawing.'

        # The replay: what actually reached the screen must be the Remix frame with the green HUD quad on top of it.
        assert composite.exists() and composite.stat().st_size > 1000, 'the composite was never captured'
        raw = composite.read_bytes()
        width, height = 1920, 1080
        def pixel(x, y):
            i = (y * width + x) * 4
            return raw[i], raw[i + 1], raw[i + 2]
        centre = pixel(width // 2, height // 2)
        corner = pixel(8, 8)
        # CB11 moves the quad from x -1.3..-0.1 to -0.7..0.5: green at the centre needs the translation, and the
        # untranslated left edge (x = -0.9) must show the Remix frame.
        left = pixel(int(width * 0.05), height // 2)
        assert not (left[1] > 200 and left[0] < 60), f'the HUD quad was drawn without its CB11 translation: left={left}'
        assert centre[1] > 200 and centre[0] < 60 and centre[2] < 60, f'HUD quad missing from the composite: centre={centre}'
        assert max(abs(a - b) for a, b in zip(corner, tr.REMIX)) < 24, \
            f'the composite is not the Remix frame at the edge: corner={corner} expected~{tr.REMIX}'
        results['replay'] = 'The composed frame is the Remix image with the HUD drawn over it, moved by its CB11.'
        assert r.get('hud_state_lost') == '0', f'the replay changed the game state across Present: {r.get("hud_state_lost")} frames'
        log_lines = [x for x in tr.remix_lines(log) if 'hud replay draws=' in x]
        assert log_lines and not log_lines[0].split('draws=')[1].startswith('0 '), \
            f'the one-shot replay line must describe a frame that carried a HUD: {log_lines[:1]}'
        results['state'] = 'Depth view, blend factor and sample mask survive the replay.'

        # Rollback switch: NIER_REMIX_LIVE_NO_HUD=1 neither captures nor replays the HUD.
        tex3 = work / 'live-textures-nohud'
        tex3.mkdir()
        composite3 = work / 'composite-nohud.raw'
        _, r, log, fake = tr.run(work, 'nohud', {**base, 'MOCK_CAMERA': 'live-hud', 'NIER_REMIX_LIVE_TEX': tr.win(tex3),
                                                'NIER_REMIX_LIVE_NO_HUD': '1', 'NIER_REMIX_CAPTURE_COMPOSITE': tr.win(composite3)})
        assert fake and 'VIOLATION' not in fake, fake
        off = hud_counts(log)
        assert off and max(off) == 0, f'NIER_REMIX_LIVE_NO_HUD still captured the HUD: hud={max(off)}'
        results['nohud'] = 'NIER_REMIX_LIVE_NO_HUD turns HUD capture and replay off.'

        tex2 = work / 'live-textures-plain'
        tex2.mkdir()
        _, r, log, fake = tr.run(work, 'plain', {**base, 'MOCK_CAMERA': 'live', 'NIER_REMIX_LIVE_TEX': tr.win(tex2)})
        plain = hud_counts(log)
        assert plain and max(plain) == 0, f'a run with no HUD draws reported hud={max(plain)}'
        results['none'] = 'A run without HUD draws reports hud=0.'
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-3000:], 'results': results,
                                                         'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results,
              'dll_sha256': hashlib.sha256((tmo.DLL / 'd3d11.dll').read_bytes()).hexdigest(),
              'limits': 'Software mock, fake Remix: pins that the HUD is captured and drawn over the composed image. Says '
                        'nothing about NieR\'s real HUD looking right.'}
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
