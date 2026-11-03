#!/usr/bin/env python3
"""Gate: converting and writing new texture files must not stall the Remix worker, and no material may name a file
that is not completely on disk.

Why (evidence/remix-current/2026-11-01/frametime1-attribution.md): the worker converted every new normal / mask
texture (octahedral RGBA8, R8 channels) and wrote its DDS inline, outside every timed stage, so streamed-in content
froze the Remix image for 0.8-1.7 s. The work moved there from the game thread on 2026-10-31 (1.1 s game freezes);
it has to leave the render loop, not just change threads again.

Wine mock with the fake Remix runtime, a NieR-like PBR shader (albedo + octahedral normal + metallic + roughness, so
every conversion path runs), a second geometry with its own albedo from frame 40 (MOCK_LATE_TEXTURE: streamed in
mid-run, when a stall is visible between Presents) and NIER_REMIX_LIVE_TEX_WRITE_DELAY_MS making each texture write slow:
  1. `sync` (no delay) is the reference: which complete material each world geometry ends with.
  2. `slow` (300 ms per texture file):
     a. the fake runtime records no VIOLATION, which now includes "CreateMaterial names a live_*.dds that is missing
        or incomplete on disk" (remix_live_fake_runtime.cpp, check_on_disk): a path is handed to Remix only once its
        file is written;
     b. Remix keeps presenting while files are written: no gap over 250 ms between Presents after frame 5 (the
        fake logs "Present gap"); inline writes give >= 300 ms gaps;
     c. the game thread is not stalled either (worst game frame < 250 ms, as test_live_read_counters case 8);
     d. the world geometries' LAST meshes carry the same complete materials (albedo, normal, roughness, metallic file
        names) as in `sync`;
     e. no extra builds: each geometry is built no more often than in `sync` (an upload waits for its files, it is
        not built bare and rebuilt).
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-texture-writer'
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'NIER_REMIX_LIVE_STATS_EVERY',
                                     'NIER_REMIX_LIVE_TEX_WRITE_DELAY_MS', 'NIER_REMIX_LIVE_NORMAL', 'MOCK_PBR_PS',
                                     'MOCK_NORMAL_TEX', 'MOCK_CAMERA', 'FAKE_REMIX_INSTANCE_LOG', 'MOCK_LATE_TEXTURE')
GAP_MS = 250
DELAY_MS = 300


def final_materials(fake):
    """World geometry capture key -> (material of its last mesh, number of builds). Background shell (|x| > 5000) excluded."""
    materials, last, builds = {}, {}, {}
    for line in fake.splitlines():
        kv = dict(re.findall(r'(\w+)=(\S+)', line))
        if line.startswith('CreateMaterial '):
            materials[kv['id']] = (kv['path'], kv['normal'], kv['roughness'], kv['metallic'])
        elif line.startswith('CreateMesh '):
            if abs(float(kv['v0'].split(',')[0])) > 5000:
                continue
            last[kv['key']] = materials.get(kv['mat'], ('-',) * 4) if kv['mat'] != '0' else ('-',) * 4
            builds[kv['key']] = builds.get(kv['key'], 0) + 1
    return last, builds


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

        def run(name, extra):
            tex = work / f'tex-{name}'
            tex.mkdir()
            env = {'MOCK_NORMAL_TEX': '1', 'MOCK_CAMERA': 'live', 'MOCK_FRAME_MS': '60', 'MOCK_PBR_PS': '1',
                   'MOCK_LATE_TEXTURE': '1', 'NIER_REMIX': '1', 'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'),
                   'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'), 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_NORMAL': '1',
                   'NIER_REMIX_LIVE_TEX': tr.win(tex), 'NIER_REMIX_LIVE_STATS_EVERY': '10', **extra}
            _, r, log, fake = tr.run(work, name, env)
            assert fake, f'{name}: no fake-remix.log'
            return r, log, fake, tex

        # 1. Reference: synchronous, no delay.
        _, log, fake, tex = run('sync', {})
        assert 'VIOLATION' not in fake, [x for x in fake.splitlines() if 'VIOLATION' in x][:3]
        last, builds_sync = final_materials(fake)
        # Capture keys differ between runs (pointers), so runs are compared as the multiset of final materials.
        want = sorted(last.values())
        want_builds = sorted(builds_sync.values())
        assert len(want) == 2, f'expected two world geometries (one from frame 40, MOCK_LATE_TEXTURE), got {last}'
        assert len(set(want)) == 2, f'the frame-40 geometry did not get its own albedo: {want}'
        for key, mat in last.items():
            assert '-' not in mat, f'reference geometry {key} lacks a complete PBR material {mat}: fixture changed?'
        gaps = [x for x in fake.splitlines() if x.startswith('Present gap')]
        assert not gaps, f'the reference run already has Present gaps (mock too slow for this gate): {gaps[:3]}'
        results['sync'] = {'materials': want}

        # 2. Slow disk.
        _, log, fake, tex = run('slow', {'NIER_REMIX_LIVE_TEX_WRITE_DELAY_MS': str(DELAY_MS)})
        violations = [x for x in fake.splitlines() if 'VIOLATION' in x]
        assert not violations, f'2a: {violations[:3]}'
        gaps = [x for x in fake.splitlines() if x.startswith('Present gap')]
        long_gaps = [x for x in gaps if int(x.split()[2]) > GAP_MS]
        assert not long_gaps, f'2b: the Remix worker stalled while texture files were written: {long_gaps[:4]}'
        lines = [x for x in tr.remix_lines(log) if x.startswith('remix: live rebuilds ')]
        assert lines, tr.remix_lines(log)[-6:]
        worst = max(int(dict(re.findall(r'(\w+)=(\d+)', x))['game_max_ms']) for x in lines)
        assert worst < 250, f'2c: a texture write stalled the game thread: worst game frame {worst} ms'
        last, builds = final_materials(fake)
        got = sorted(last.values())
        assert got == want, f'2d: final materials differ from the synchronous run: got {got}, want {want}'
        assert sorted(builds.values()) == want_builds, f'2e: build counts {builds} differ from the synchronous run {builds_sync}'
        results['slow'] = {'present_gaps': gaps, 'worst_game_ms': worst, 'builds': builds,
                           'dds': sorted(p.name for p in tex.glob('live_*.dds'))}
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-3000:], 'results': results,
                                                         'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results,
              'limits': 'Wine mock with a fake Remix and an injected write delay: pins that conversion and file writes '
                        'leave the render loop and that materials stay complete, not the real game\'s frame times.'}
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
