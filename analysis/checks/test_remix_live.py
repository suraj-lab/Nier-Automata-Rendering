#!/usr/bin/env python3
"""Gate for the in-game Remix host (remix_live.cpp) in the real proxy DLL, without a GPU.

Same harness as test_menu_overlay.py (mock game + stub mod layer, isolated Wine prefix + Xvfb, wined3d), plus a fake
Remix runtime (remix_live_fake_runtime.cpp) whose D3D9 side is Wine's real d3d9 and whose "frame" is a ColorFill of
(200,40,120). The stub layer captures exactly what our Present hook passes down, so a pixel proves the whole chain:
runtime -> copy -> readback -> byte order -> game backbuffer, with the menu still drawn on top.

Scenarios: off (unset and NIER_REMIX=0 must be byte-identical), RGBA and BGRA backbuffers, a mid-run ResizeBuffers,
and four failures (missing runtime, relative path, bad scene, copy failing mid-run) that must all fall back to the
game's own frames without losing one. Never touches the game folder or any other Wine prefix.
"""
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime' / 'remix-live'
sys.path.insert(0, str(C))
import test_menu_overlay as tmo  # noqa: E402  (build + scenario runner shared with the menu gate)
import test_nscn_scene as ts  # noqa: E402  (NSCN writer)

BACKGROUND, SURFACE, REMIX = tmo.BACKGROUND, tmo.SURFACE, (200, 40, 120)
PROBE = (100, 100)  # left of the menu panel at every size used here
ENV_KEYS = ('NIER_REMIX', 'NIER_REMIX_CHEAP_GAME', 'NIER_REMIX_RUNTIME', 'NIER_REMIX_SCENE', 'MOCK_BGRA', 'MOCK_FRAME_MS', 'MOCK_RESIZE_AT', 'MOCK_RESIZE_TO',
            'MOCK_START', 'MOCK_CAMERA', 'FAKE_REMIX_FAIL', 'FAKE_REMIX_CAMERA_LOG', 'MOCK_SCENE_FULL', 'MOCK_EMPTY_EVERY',
            'NIER_REMIX_LIVE_NO_HUD', 'NIER_REMIX_LIVE_NO_SKY', 'MOCK_SKY_ONLY_UNTIL', 'MOCK_PREPASS', 'MOCK_CUTOUT_PS')


def rgb(raw, x, y):
    width, height, fmt = struct.unpack_from('<3I', raw, 0)
    o = 12 + (y * width + x) * 4
    p = tuple(raw[o:o + 3])
    if fmt == 87:  # B8G8R8A8_UNORM
        return p[2], p[1], p[0]
    assert fmt == 28, fmt
    return p


def size(raw):
    return struct.unpack_from('<2I', raw, 0)


def win(path):
    return 'Z:' + str(path).replace('/', '\\')


def run(work, name, env, fonts=True, expected_presented=80):
    for k in ENV_KEYS:
        os.environ.pop(k, None)
    os.environ.update(env)
    try:
        d, r, log = tmo.scenario(work, name, b'[Rendering]\r\nPreset=Custom75\r\n', fonts, (0, 0))
    finally:
        for k in ENV_KEYS:
            os.environ.pop(k, None)
    fake = (d / 'fake-remix.log').read_text() if (d / 'fake-remix.log').exists() else None
    assert r['presented'] == str(expected_presented) and r['stub_presents'] == '80', f'{name}: frames lost {r}'
    return d, r, log, fake


def remix_lines(log):
    return [line.split(' ', 2)[-1] for line in log.splitlines() if ' remix:' in line]


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    results = {}
    try:
        tmo.build(work)
        gpp = ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-static', '-static-libgcc',
               '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor')]
        r = subprocess.run([*gpp, '-shared', str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')],
                           capture_output=True, text=True)
        assert r.returncode == 0, 'fake runtime build:\n' + r.stderr[-3000:]
        scene_dir = work / 'scene'
        (scene_dir / 'scene_textures').mkdir(parents=True)
        (scene_dir / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
        (scene_dir / 'broken.bin').write_bytes(b'NSCN' + b'\0' * 40)
        on = {'NIER_REMIX': '1', 'NIER_REMIX_RUNTIME': win(work / 'fake_remix.dll'),
              'NIER_REMIX_SCENE': win(scene_dir / 'scene.bin'), 'MOCK_FRAME_MS': '40'}
        x0, y0 = 1920 - 32 - 552, 32  # menu panel at 1920x1080 (test_menu_overlay.py)

        # 1. Off: unset and "0" are the same program -- nothing logged, nothing loaded, identical frames.
        d_unset, r_unset, log_unset, fake = run(work, 'off-unset', {})
        assert fake is None and not remix_lines(log_unset), (fake, remix_lines(log_unset))
        # Off means no live-capture hooks at all (review 2026-10-29: they were installed on every launch).
        assert r_unset.get('ctx_map_in_proxy') == '0', f'Remix off, yet Map is hooked: {r_unset.get("ctx_map_in_proxy")}'
        d_zero, _, log_zero, fake = run(work, 'off-zero', {'NIER_REMIX': '0', 'NIER_REMIX_RUNTIME': on['NIER_REMIX_RUNTIME']})
        assert fake is None and not remix_lines(log_zero), (fake, remix_lines(log_zero))
        for cap in ('capture-closed.raw', 'capture-open.raw', 'capture-after.raw'):
            assert (d_unset / cap).read_bytes() == (d_zero / cap).read_bytes(), f'NIER_REMIX=0 changed {cap}'
        assert rgb((d_zero / 'capture-closed.raw').read_bytes(), *PROBE) == BACKGROUND
        results['off'] = 'unset and NIER_REMIX=0: no remix log line, runtime never loaded, all three captures byte-identical'

        # 2. On, RGBA backbuffer: Remix's frame replaces the game's, the menu is drawn on top of it.
        d, r, log, fake = run(work, 'on-rgba', on)
        lines = remix_lines(log)
        assert 'VIOLATION' not in fake, fake
        assert not any('disabled' in x for x in lines), lines
        f = fake.splitlines()
        # Material creation now logs too; the contract is the order of the lifecycle calls, not adjacency.
        lifecycle = ('InitializeLibrary', 'CreateD3D9', 'Register', 'Startup', 'CreateMesh')
        order = [x.split()[0] for x in f if x.split()[0] in lifecycle]
        assert order[:5] == list(lifecycle), f
        assert 'version_minor=6' in f[0], f[0]
        register = next(x for x in f if x.startswith('Register '))
        startup = next(x for x in f if x.startswith('Startup '))
        mesh = next(x for x in f if x.startswith('CreateMesh '))
        assert register == 'Register 1920x1080 started=0', f'device created at the game backbuffer size before Startup: {register}'
        assert startup == 'Startup hwnd_visible=0 combineGui=1 registered=1', f'hidden window, after Register: {startup}'
        assert mesh.startswith('CreateMesh hash=2 surfaces=4 verts=15 indices=0 materials=4'), mesh
        assert 'SetupCamera aspect=1.7778 fov=50.00' in f, 'camera aspect follows the backbuffer, fov the scene'
        assert 'Copy 1920x1080' in f, f
        sink = [x for x in f if x.startswith('Sink rect=')]
        assert sink, 'fake runtime did not create its input-sink window'
        sl, st, sr_, sb = map(int, sink[0].split('=')[1].split(','))
        assert sr_ <= 0 or sb <= 0, f'Remix input-sink window copies our window rect and must land off every monitor: {sink[0]}'
        # Focus is NOT asserted here: under Xvfb with no window manager any new visible window takes the foreground.
        # On the real desktop the off-screen sink leaves focus with the game (run_live_mock.sh prints foreground=).
        assert 'Window after show attempt visible=0 size=1920x1080' in f, \
            f'the runtime shows/resizes its window (real one went fullscreen white over the desktop); the host must keep it hidden at size: {[x for x in f if x.startswith("Window")]}'
        assert any(x.startswith('remix: started 1920x1080 startup=5 surfaces=4 sky_skipped=1 untextured=1') for x in lines), lines
        assert 'remix: first frame ready' in lines and 'remix: composited first frame 1920x1080' in lines, lines
        after = (d / 'capture-after.raw').read_bytes()
        assert tmo.near(rgb(after, *PROBE), REMIX), f'Remix frame not composited: {rgb(after, *PROBE)}'
        assert tmo.near(rgb((d / 'capture-open.raw').read_bytes(), x0 + 10, y0 + 20), SURFACE), 'menu must draw over Remix'
        assert r['cs_lost'] == '0', r
        results['on-rgba'] = 'call order Init > CreateD3D9 > Register(1920x1080) > Startup(hidden, ALREADY_EXISTS) > mesh; frame composited; menu on top'

        # 3. BGRA backbuffer: same colour, other byte order.
        d, r, log, fake = run(work, 'on-bgra', {**on, 'MOCK_BGRA': '1'})
        after = (d / 'capture-after.raw').read_bytes()
        assert struct.unpack_from('<3I', after, 0)[2] == 87, 'mock did not create a BGRA swapchain'
        assert tmo.near(rgb(after, *PROBE), REMIX), f'BGRA byte order wrong: {rgb(after, *PROBE)}'
        assert 'VIOLATION' not in fake, fake
        results['on-bgra'] = 'B8G8R8A8 backbuffer gets the same colour'

        # 4a. NieR's intro runs at 720x480 for many seconds, then the swapchain goes to the monitor size. Resetting a live
        #     Remix device froze/crashed NieR (2026-10-28) and a "stable for 5 s" start picked 720x480, so Remix starts once
        #     at the monitor size and the game's own frames are shown until the backbuffer matches it.
        d, r, log, fake = run(work, 'on-intro', {**on, 'MOCK_START': '720x480', 'MOCK_RESIZE_AT': '20', 'MOCK_RESIZE_TO': '1920x1080'})
        assert r.get('resize_hr') == '0x00000000', f'mock ResizeBuffers failed (a backbuffer reference was kept?): {r}'
        f = fake.splitlines()
        assert 'Register 1920x1080 started=0' in f, f'Remix must start once, at the monitor size: {f[:4]}'
        lines = remix_lines(log)
        assert any(x.startswith('remix: starting at monitor size 1920x1080 (game backbuffer 720x480 ') for x in lines), lines
        closed = (d / 'capture-closed.raw').read_bytes()
        assert size(closed) == (1920, 1080) and tmo.near(rgb(closed, *PROBE), REMIX), (size(closed), rgb(closed, *PROBE))
        assert any(x.startswith('remix: resumed at 1920x1080') for x in lines) or not any('paused' in x for x in lines), lines
        assert not any('resized' in x or 'disabled' in x for x in lines), lines
        results['on-intro'] = 'intro at 720x480: Remix starts at the monitor size, game frames until the swapchain matches, then Remix'
        # 4b. A resize after Remix started pauses it (game frames shown) instead of resetting the device.
        d, r, log, fake = run(work, 'on-late-resize', {**on, 'MOCK_RESIZE_AT': '65'})
        assert r.get('resize_hr') == '0x00000000', r
        lines = remix_lines(log)
        assert any(x.startswith('remix: paused (game backbuffer 1280x720, Remix 1920x1080)') for x in lines), lines
        assert not any('resized' in x or 'disabled' in x for x in lines), lines
        after = (d / 'capture-after.raw').read_bytes()
        assert size(after) == (1280, 720) and tmo.near(rgb(after, *PROBE), BACKGROUND), f'paused: game frame expected {rgb(after, *PROBE)}'
        assert 'VIOLATION' not in fake, fake
        results['on-late-resize'] = 'resize after start: Remix paused with one log line, game frames shown, no reset'

        # 5-8. Failures fall back to the game's frames, with one explicit log line, without losing a frame.
        def fallback(name, env, reason, runtime_loaded):
            d, r, log, fake = run(work, name, env)
            lines = remix_lines(log)
            assert sum('disabled' in x for x in lines) == 1 and any(reason in x for x in lines), f'{name}: {lines}'
            assert (fake is not None) == runtime_loaded, f'{name}: runtime loaded={fake is not None}'
            assert tmo.near(rgb((d / 'capture-after.raw').read_bytes(), *PROBE), BACKGROUND), f'{name}: game frame not shown'
            assert tmo.near(rgb((d / 'capture-open.raw').read_bytes(), x0 + 10, y0 + 20), SURFACE), f'{name}: menu lost'
            return lines, fake
        fallback('fail-missing', {**on, 'NIER_REMIX_RUNTIME': 'C:\\nope\\d3d9.dll'}, 'disabled (runtime load', False)
        fallback('fail-relative', {**on, 'NIER_REMIX_RUNTIME': 'd3d9.dll'}, 'NIER_REMIX_RUNTIME must be an absolute path', False)
        fallback('fail-scene', {**on, 'NIER_REMIX_SCENE': win(scene_dir / 'broken.bin')}, 'disabled (scene file missing or invalid', False)
        lines, fake = fallback('fail-copy', {**on, 'FAKE_REMIX_FAIL': 'copy:20'}, 'disabled (CopyRenderingOutput 1', True)
        assert 'Copy 20 failing on request' in fake, fake
        assert 'remix: first frame ready' in lines, 'copy failure must come after frames were already shown'
        # A runtime that never returns (seen in NieR 2026-10-28: Remix stuck in its first frame, game frozen) must not
        # stall the game, and the watchdog must say where the worker is stuck.
        d, r, log, fake = run(work, 'hang-present', {**on, 'FAKE_REMIX_FAIL': 'hang:present', 'MOCK_FRAME_MS': '120'})  # 9.6 s: past the 5 s watchdog
        lines = remix_lines(log)
        assert 'Present hanging on request' in fake, fake
        dog = [x for x in lines if x.startswith('remix: watchdog')]
        assert dog and "worker in 'present'" in dog[0] and 'game presents=' in dog[0], f'watchdog must name the stuck stage: {lines}'
        assert r['presented'] == '80', r
        results['hang-present'] = f'runtime hangs in Present at frame 3: game keeps presenting (80/80), watchdog: {dog[0][:90]}'
        # A Remix window of the game's own process taking focus makes NieR drop to its focus-lost 720x480 window; the host
        # gives focus back to the game (only from windows of its own process, never from other applications).
        d, r, log, fake = run(work, 'steal-focus', {**on, 'FAKE_REMIX_FAIL': 'steal-focus'})
        lines = remix_lines(log)
        assert 'Sink took focus' in fake, fake
        assert any(x.startswith('remix: focus returned to the game from') for x in lines), lines
        assert r['foreground'] == '1', f'the game must end up with focus: {r}'
        results['steal-focus'] = 'Remix window takes focus: host returns it to the game window, logged'
        results['fallbacks'] = 'missing runtime, relative path, broken scene, copy failing at frame 20: one log line, game frames back, menu intact'
    except Exception as error:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(error)[:3000], 'results': results,
                                                         'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    receipt = {'passed': True, 'results': results,
               'dll_sha256': json.loads((tmo.DLL / 'validation.json').read_text())['sha256'],
               'limits': 'Wine/wined3d + Xvfb, fake runtime (ColorFill frame); not the Remix runtime, DXVK, Proton or NieR'}
    (OUT / 'validation.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


def main():
    if sys.argv[1:] == ['--inside']:
        return inside()
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    assert not (OUT / 'prefix').is_symlink()
    env = os.environ.copy()
    for k in ENV_KEYS:
        env.pop(k, None)
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    # 1920x1080 is the mock's "monitor": Remix starts at this size.
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable, str(Path(__file__).resolve()),
                    '--inside'], env=env, cwd=OUT, check=True)


if __name__ == '__main__':
    main()
