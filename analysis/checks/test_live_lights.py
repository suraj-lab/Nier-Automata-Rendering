#!/usr/bin/env python3
"""Frozen gate: the game's tiled-forward light array becomes Remix lights.

NieR is a tiled forward renderer: point lights live in a structured buffer bound at PS slot 20 (48-byte elements), spot
lights at 22, per-tile indices at 21. Today the live path creates one sun and one sky light once and never reads either
array, so the camp is lit by a single hand-made sun. The element layout is not a guess: it was read out of the game's
own light shader and is recorded in analysis/SHADER_DECLARATIONS.md.

What this gate pins, with the mock binding two known lights at slot 20:
  - two sphere lights are created with the array's positions, radii and colours;
  - they are submitted every frame (`DrawLightInstance`), not only once;
  - an empty array creates no sphere light (the red test: the numbers above cannot come from anywhere else);
  - the sun and sky lights the live path already creates still exist, i.e. the new path adds rather than replaces;
  - nothing is created twice per frame (no per-frame CreateLight churn).

Software mocks only. Real NieR light counts, the unidentified fields (bytes 16-27) and intensity scaling stay unproven
until a live run reports them.
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
OUT = A / 'runtime/live-lights'
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'FAKE_REMIX_LIGHT_LOG')


def sphere_lights(fake):
    out = []
    for line in fake.splitlines():
        if not line.startswith('CreateLight') or 'sphere' not in line:
            continue
        kv = dict(re.findall(r'(\w+)=([-\d.,]+)', line))
        if 'pos' not in kv:
            continue
        pos = [float(v) for v in kv['pos'].split(',')]
        rad = [float(v) for v in kv['radiance'].split(',')]
        out.append({'pos': pos, 'radius': float(kv['radius']), 'radiance': rad, 'hash': kv.get('hash')})
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
                'FAKE_REMIX_LIGHT_LOG': '1'}

        _, r, log, fake = tr.run(work, 'lights', {**base, 'MOCK_CAMERA': 'live-lights'})
        assert fake and 'VIOLATION' not in fake, fake
        lights = sphere_lights(fake)
        assert lights, f'no sphere light was created from the light array: {[l for l in fake.splitlines() if l.startswith("CreateLight")][:6]}'
        positions = [l['pos'] for l in lights]
        wanted = [[100.0, 20.0, 300.0], [-50.0, 5.0, 650.0]]
        for w in wanted:
            assert any(all(abs(a - b) < 0.01 for a, b in zip(pos, w)) for pos in positions), \
                f'light at {w} missing from {positions}'
        first = next(l for l in lights if l['pos'][0] == 100.0)
        # Physical conversion (light_convert.h, gated by test_light_convert.py): a small 0.1 emitter, never the game's
        # range as the sphere size; intensity puts the game colour at half the range: colour * (25/2)^2 / (pi 0.1^2).
        k = 12.5 ** 2 / (3.14159265 * 0.01)
        assert abs(first['radius'] - 0.1) < 1e-4, f'emitter radius must stay small, not the range: {first}'
        assert all(abs(v - c * k) <= 1e-3 * c * k for v, c in zip(first['radiance'], (3.0, 1.5, 0.5))), \
            f'radiance {first["radiance"]} != colour (offset 32) * range (offset 12) term {k:.1f}'
        results['positions'] = 'Two lights created with the array\'s positions; range and colour become a physical intensity.'

        # Add, not replace: the sun and sky the live path already made are still there.
        others = [l for l in fake.splitlines() if l.startswith('CreateLight') and 'sphere' not in l]
        assert others, f'the existing sun/sky lights disappeared: {fake.splitlines()[:8]}'
        results['existing'] = 'The sun and sky lights are still created.'

        # Per frame, not once: the mock runs ~90 frames and the lights must be submitted each frame, while
        # CreateLight stays bounded (no per-frame churn).
        drawn = [l for l in fake.splitlines() if l.startswith('DrawLightInstance')]
        assert len(drawn) > 20, f'lights are not submitted every frame: {len(drawn)} DrawLightInstance calls'
        frames_seen = {int(re.search(r'presented=(\d+)', l).group(1)) for l in drawn}
        assert len(frames_seen) > 20, f'lights only submitted on {len(frames_seen)} frames'
        assert len(lights) <= 4, f'CreateLight churn: {len(lights)} sphere lights for 2 lights'
        results['every_frame'] = 'Lights are submitted every frame without CreateLight churn.'

        # The mock binds slot 20 only after the frame's first (sky) draw, so the positions above already prove the
        # array is read from a later draw. From frame 50 the first light moves to x=110: Remix has no UpdateLight, so
        # the light must be recreated, with the same hash (the denoiser keys temporal history on it).
        # The moved array is bound through a BUFFEREX view (the old reader accepted BUFFER only).
        moved = [l for l in lights if abs(l['pos'][0] - 110.0) < 0.01]
        assert moved, f'the moved light (BUFFEREX view) was never recreated: {[l["pos"] for l in lights]}'
        assert moved[0]['hash'] == first['hash'], f'recreated light changed hash: {first["hash"]} -> {moved[0]["hash"]}'
        results['moved'] = 'A light that moves is recreated at its new position with the same hash.'

        # Red test: empty array, no sphere light. Without this the values above could come from anywhere.
        _, r, log, fake = tr.run(work, 'nolights', {**base, 'MOCK_CAMERA': 'live-nolights'})
        assert fake and 'VIOLATION' not in fake, fake
        assert not sphere_lights(fake), f'an empty light array produced lights: {sphere_lights(fake)[:3]}'
        results['empty'] = 'An empty light array creates no sphere light.'
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-3000:], 'results': results,
                                                         'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results,
              'dll_sha256': hashlib.sha256((tmo.DLL / 'd3d11.dll').read_bytes()).hexdigest(),
              'limits': 'Software-only mock, fake Remix. Pins the plumbing and the four verified fields, not real NieR '
                        'light counts, the fields at 16-27, or whether colour is already intensity-scaled.'}
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
