#!/usr/bin/env python3
"""Gate: the buffer mirror does not read the game's writes back out of the driver's mapping.

Replay of a real 3,382-draw frame under Proton (2026-11-12, analysis/replay): 55 ms of every 73 ms game frame went into
the Unmap hook, which copied each written constant buffer out of the mapping the driver handed the game. Under DXVK
that mapping is write-combined video memory. A WRITE_DISCARD map of a small buffer is now redirected: the game writes
into our memory and Unmap copies it into the mapping once.

What this pins, in the Wine mock with the fake runtime:
  - default: the mock's discard maps are redirected and nothing is read back (`remix: live maps redirected=N
    read_back_kb=0`), and the scene is the one the old mirror produces (the same meshes: counts, first vertex, UV sum);
  - NIER_REMIX_LIVE_MAP_REDIRECT=0: the old mirror, redirected=0 and read_back_kb > 0 (the counter is live, and the
    rollback switch works).
A redirect that lost the game's bytes fails every other live gate (camera, transforms and skinning all come from
buffers the mock writes through discard maps), so this gate only adds the counters and the switch.
Limits: Wine's software D3D11 has no write-combined memory, so the cost itself is measured in replay, not here.
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
OUT = A / 'runtime/live-map-redirect'
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE_STATS_EVERY', 'NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX',
                                     'NIER_REMIX_LIVE_MAP_REDIRECT', 'FAKE_REMIX_INSTANCE_LOG', 'NIER_REMIX_LIVE_MAX_WRITE_KB',
                                     'NIER_REMIX_LIVE_TEARDOWN_AT_MAP', 'MOCK_MAP_TWICE', 'MOCK_VERIFY_MAPS')


def counters(log):
    lines = [x for x in tr.remix_lines(log) if x.startswith('remix: live maps ')]
    assert lines, 'no "remix: live maps" line: ' + '\n'.join(tr.remix_lines(log)[-8:])
    last = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', lines[-1])}
    # The line is written by the worker while the game thread may be inside a Map, so one sample can read open=1
    # (seen once under suite load, 2026-11-13). A leak never returns to 0: take the lowest of the last windows.
    last['open'] = min(int(re.search(r'open=(\d+)', x).group(1)) for x in lines[-4:])
    return last


def scene(fake):
    """Geometry as built, without the capture key (it hashes buffer pointers, which differ between two processes)."""
    shapes = set()
    for line in fake.splitlines():
        if line.startswith('CreateMesh'):
            kv = dict(re.findall(r'(\w+)=(\S+)', line))
            shapes.add((kv['verts'], kv['indices'], kv['skinned'], kv['v0'], kv['uvsum'], kv['materials']))
    return shapes, max((int(m) for m in re.findall(r'instances=(\d+)', fake)), default=0)


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    results = {}
    try:
        tmo.build(work)
        subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                        str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
        scene_dir = work / 'scene'
        (scene_dir / 'scene_textures').mkdir(parents=True)
        (scene_dir / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
        out = {}
        cases = (('redirect', {}), ('readback', {'NIER_REMIX_LIVE_MAP_REDIRECT': '0'}),
                 ('big', {'NIER_REMIX_LIVE_MAX_WRITE_KB': '1'}), ('twice', {'MOCK_MAP_TWICE': '1'}),
                 ('teardown', {'NIER_REMIX_LIVE_TEARDOWN_AT_MAP': '30'}),
                 ('teardown-twice', {'MOCK_MAP_TWICE': '1', 'NIER_REMIX_LIVE_TEARDOWN_AT_MAP': '30'}))
        for name, extra in cases:
            tex = work / f'tex-{name}'
            tex.mkdir()
            _, r, log, fake = tr.run(work, name, {
                'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'), 'NIER_REMIX_SCENE': tr.win(scene_dir / 'scene.bin'),
                'MOCK_FRAME_MS': '40', 'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex),
                'MOCK_CAMERA': 'live-skinned', 'NIER_REMIX_LIVE_STATS_EVERY': '10', 'FAKE_REMIX_INSTANCE_LOG': '1',
                'MOCK_VERIFY_MAPS': '1', **extra})
            assert fake and 'VIOLATION' not in fake, fake
            out[name] = (counters(log), scene(fake), r)
            # Every case: the driver's palette buffer holds the bytes the game wrote, every frame, whatever the proxy
            # did with the mapping, and no redirected map is left open.
            assert int(r['map_mismatches']) == 0 and int(r['map_verified']) >= 60, f'{name}: game bytes lost: {r}'
            assert out[name][0]['open'] == 0, f'{name}: redirected maps left open: {out[name][0]}'
        on, off = out['redirect'], out['readback']
        assert on[0]['redirected'] > 0 and on[0]['read_back_kb'] == 0, f'default still reads mappings back: {on[0]}'
        assert off[0]['redirected'] == 0 and off[0]['read_back_kb'] > 0, f'rollback switch: {off[0]}'
        assert on[1][0] and on[1][0] == off[1][0], f'geometry differs: {sorted(on[1][0] ^ off[1][0])}'
        results['redirect'] = 'Discard maps redirected (%d), 0 KiB read back; %d geometries, the same as the old mirror.' % (
            on[0]['redirected'], len(on[1][0]))
        results['readback'] = 'NIER_REMIX_LIVE_MAP_REDIRECT=0 restores the read-back mirror (%d KiB).' % off[0]['read_back_kb']
        # A discard map of a non-constant buffer above the shadow limit is not redirected: the mapping goes to the game and
        # the write only drops the mirror (the vertex buffer is read again). The scene is unchanged.
        big = out['big']
        assert big[0]['redirected'] > 0 and big[1][0] == on[1][0], f'big buffers: {big[0]} {sorted(big[1][0] ^ on[1][0])}'
        results['big'] = 'Discard maps over NIER_REMIX_LIVE_MAX_WRITE_KB keep the driver pointer; same geometry; %s' % big[0]
        # A second discard map before the Unmap: the first redirect is flushed then, not leaked (open=0 above).
        twice = out['twice']
        if int(twice[2]['double_maps']):
            assert twice[1][0] == on[1][0], f'double map: geometry differs: {sorted(twice[1][0] ^ on[1][0])}'
            results['twice'] = 'Mapped twice before Unmap on %s frames: bytes intact, nothing open.' % twice[2]['double_maps']
        else:
            results['twice'] = "Wine's d3d11 refused every second map, so the case is not reached here (DXVK allows it)."
        # Teardown (live capture revoked) between a redirected Map and its Unmap: the game's bytes still reach the
        # driver, and every later map goes straight to the driver.
        # A map that is redirected, then torn down, then mapped AGAIN before its Unmap: the second map is the one whose
        # bytes belong in the driver. The gate's *_verified check above covers it for every case.
        # The counter's last line is the last stats window before the worker stopped, so it reads below 30 (the redirect
        # count the teardown was armed at); a run without the switch redirects ~200 in the same 80 frames.
        down = out['teardown']
        assert 0 < down[0]['redirected'] < 60, f'teardown at map 30 did not stop the redirects: {down[0]}'
        results['teardown'] = 'Teardown inside map 30: redirects stopped at %d, bytes intact for %s frames, nothing open.' % (
            down[0]['redirected'], down[2]['map_verified'])
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-3000:], 'results': results,
                                                         'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results,
              'dll_sha256': hashlib.sha256((tmo.DLL / 'd3d11.dll').read_bytes()).hexdigest(),
              'limits': 'Wine mock, fake Remix: pins the mechanism and the switch, not the time saved (see analysis/replay).'}
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
