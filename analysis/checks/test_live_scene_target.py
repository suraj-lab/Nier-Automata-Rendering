#!/usr/bin/env python3
"""Frozen gate: only the scene's render target becomes the Remix scene.

Measured on a real captured NieR frame (2436 draws): 1375 draws into a 2580x1080 scene target, 920 into a
4096x4096 shadow atlas, 58 bloom passes and 58 HUD sprites. Submitting the atlas and the post passes makes Remix
ray trace the scene two or three times over, which is why path-traced fps doubles when little is on screen.

What this gate pins:
  - with several render targets in play, the scene target is the display aspect at the engine's internal scale;
  - draws into any other target never become instances (and never become meshes);
  - `NIER_REMIX_LIVE_ALL_TARGETS=1` disables the filter, and then exactly those draws reappear: the assertion above
    can fail, so it is a test and not a tautology;
  - the proxy reports the choice and the skip count, so a run can be checked without a debugger.

Software mocks only: this is not evidence about real NieR passes; it pins the rule, not the game.
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
OUT = A / 'runtime/live-scene-target'
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'NIER_REMIX_LIVE_ALL_TARGETS',
                                     'FAKE_REMIX_INSTANCE_LOG')


def instances_per_frame(fake):
    counts = {}
    for line in fake.splitlines():
        if not line.startswith('DrawInstance'):
            continue
        m = re.search(r'presented=(\d+)', line)
        if m:
            counts[int(m.group(1))] = counts.get(int(m.group(1)), 0) + 1
    return counts


def meshes(fake):
    return [x for x in fake.splitlines() if x.startswith('CreateMesh')]


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
                'MOCK_FRAME_MS': '40', 'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1',
                'NIER_REMIX_LIVE_TEX': tr.win(tex), 'FAKE_REMIX_INSTANCE_LOG': '1'}

        # Reference run: one render target, so nothing may be skipped.
        _, r, log, fake = tr.run(work, 'single', {**base, 'MOCK_CAMERA': 'live'})
        assert fake and 'VIOLATION' not in fake, fake
        single = instances_per_frame(fake)
        single_meshes = meshes(fake)
        assert single, 'the live scene must draw instances'
        assert not any('skipped' in x and 'draws into other targets' in x for x in tr.remix_lines(log)), \
            f'nothing to skip with one target: {tr.remix_lines(log)[-6:]}'
        results['single'] = 'One render target: every draw is submitted, no skips reported.'

        # The same run plus a 256x256 shadow-pass stand-in drawing the same mesh twice per frame.
        _, r, log, fake = tr.run(work, 'passes', {**base, 'MOCK_CAMERA': 'live-passes'})
        assert fake and 'VIOLATION' not in fake, fake
        passes = instances_per_frame(fake)
        report = [x for x in tr.remix_lines(log) if 'draws into other targets skipped' in x]
        assert report, f'the proxy must report the choice and the skips: {tr.remix_lines(log)[-8:]}'
        assert '960x540 of 1920x1080' in report[0], report[0]
        assert int(re.search(r'; (\d+) draws into other targets', report[0]).group(1)) >= 2, report[0]
        # Frames after the choice is established (frame 1 submits everything, the histogram decides from frame 2).
        steady = range(5, 39)  # before the second pass appears at mock frame 40
        for frame in steady:
            assert passes.get(frame, 0) == single.get(frame, 0), \
                f'frame {frame}: shadow-pass draws reached the scene ({passes.get(frame)} vs {single.get(frame)})'
        # The atlas draws use the same geometry, so a mesh count that grew would mean the decoders ran on them.
        assert len(meshes(fake)) == len(single_meshes), f'pass draws built meshes: {len(meshes(fake))} vs {len(single_meshes)}'
        results['passes'] = 'Shadow-pass draws into another target never reach Remix; the proxy reports the choice.'

        # Red test: with the filter disabled, exactly those draws come back. Without this the assertion above could
        # pass for any reason at all.
        _, r, log, fake = tr.run(work, 'passes-off', {**base, 'MOCK_CAMERA': 'live-passes',
                                                      'NIER_REMIX_LIVE_ALL_TARGETS': '1'})
        assert fake and 'VIOLATION' not in fake, fake
        off = instances_per_frame(fake)
        assert off.get(10, 0) == single.get(10, 0) + 2, \
            f'filter disabled: the two 256x256 draws must appear as instances ({off.get(10)} vs {single.get(10)})'
        results['off'] = 'Filter disabled: the shadow-pass draws reappear, so the gate can fail.'

        # Wrong pick must not blank the picture. live-odd renders into a square target: no aspect rule can recognise it
        # as the scene, so the filter skips it, sees three empty frames and latches itself off. The scene must come
        # back, and the run must survive.
        _, r, log, fake = tr.run(work, 'odd', {**base, 'MOCK_CAMERA': 'live-odd', 'FAKE_REMIX_INSTANCE_LOG': '1'})
        assert fake and 'VIOLATION' not in fake, fake
        odd = instances_per_frame(fake)
        driven = {f for f in odd if f >= 10}
        assert len(driven) >= 25, f'an unrecognised scene target must not blank the picture: frames drawn {sorted(driven)[:5]}'
        assert any('filter latched off' in x for x in tr.remix_lines(log)), \
            f'the latch must be logged once: {tr.remix_lines(log)[-6:]}'
        results['odd'] = 'A scene target the rule cannot recognise latches the filter off instead of blanking the frame.'

        # Scattered empty frames (loading screens, a resize) are not a wrong pick: only three in a row latch the filter.
        # Every 10th frame here draws only the shadow-pass stand-in; a cumulative counter latches at frame 30 and the
        # shadow-pass draws then reach Remix for the rest of the run.
        _, r, log, fake = tr.run(work, 'flicker', {**base, 'MOCK_CAMERA': 'live-passes', 'MOCK_EMPTY_EVERY': '10'})
        assert fake and 'VIOLATION' not in fake, fake
        assert r.get('ctx_map_in_proxy') == '1', f'live run without the capture hooks: {r.get("ctx_map_in_proxy")}'
        flicker = instances_per_frame(fake)
        late = [n for f, n in flicker.items() if f >= 45]
        ceiling = max(n for f, n in single.items() if f >= 45)
        assert late and max(late) <= ceiling, \
            f'scattered empty frames latched the filter: {max(late) if late else None} instances vs {ceiling} without passes'
        assert not any('filter latched off' in x for x in tr.remix_lines(log)), [x for x in tr.remix_lines(log) if 'latched' in x]
        results['flicker'] = 'Non-consecutive empty frames do not latch the filter off.'

        # NieR's depth pre-pass: every opaque mesh is drawn first with a POSITION-only layout into the scene target,
        # then again with its full layout (all four real captures: 38-42% of scene draws, 2622 of 2622 with a full twin
        # later in the frame; analysis/checks/test_prepass_rule_captures.py). The pre-pass copy has no UVs or normals:
        # submitted, it is a flat shell on top of every object (the beige haze of the 2026-10-29 live run) and doubles
        # the mesh set. The live output with the pre-pass must equal the output without it.
        _, r, log, fake = tr.run(work, 'prepass', {**base, 'MOCK_CAMERA': 'live', 'MOCK_PREPASS': '1'})
        assert fake and 'VIOLATION' not in fake, fake
        pre = instances_per_frame(fake)
        for frame in range(5, 39):  # before the mock's second mesh appears (frame 40); after it, compare the ceiling
            assert pre.get(frame, 0) == single.get(frame, 0), \
                f'frame {frame}: pre-pass draws reached Remix ({pre.get(frame)} instances vs {single.get(frame)} without)'
        assert max(n for f, n in pre.items() if f >= 45) == max(n for f, n in single.items() if f >= 45), \
            'pre-pass draws reached Remix after the second mesh appeared'
        assert len(meshes(fake)) == len(single_meshes), f'pre-pass draws built meshes: {len(meshes(fake))} vs {len(single_meshes)}'
        counts = [int(m.group(1)) for x in tr.remix_lines(log) for m in [re.search(r' prepass=(\d+)', x)] if m]
        assert counts and max(counts) > 0, f'the stats line must report the skipped pre-pass draws: {counts}'
        results['prepass'] = 'POSITION-only pre-pass draws are skipped; the scene is unchanged and reported as prepass=N.'

        # Native scale: the scene target is as large as the final image. Blended scene draws into it are world
        # geometry; taking them for HUD sprites would empty the scene without ever tripping the latch.
        _, r, log, fake = tr.run(work, 'full', {**base, 'MOCK_CAMERA': 'live-blend', 'MOCK_SCENE_FULL': '1'})
        assert fake and 'VIOLATION' not in fake, fake
        full = {f for f, n in instances_per_frame(fake).items() if f >= 10 and n}
        assert len(full) >= 25, f'a final-sized scene target lost its blended draws: frames drawn {sorted(full)[:5]}'
        huds = [int(m.group(1)) for x in tr.remix_lines(log) for m in [re.search(r' hud=(\d+)', x)] if m]
        assert huds and max(huds) == 0, f'scene draws were taken for the HUD: hud={huds}'
        results['full'] = 'A scene target the size of the final image keeps its blended draws as world geometry.'
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-3000:], 'results': results,
                                                         'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results,
              'dll_sha256': hashlib.sha256((tmo.DLL / 'd3d11.dll').read_bytes()).hexdigest(),
              'limits': 'Software-only Wine mock, fake Remix; the real draw mix is described in '
                        'analysis/PLAYABILITY_PLAN.md and still needs one live run to confirm the pick.'}
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
