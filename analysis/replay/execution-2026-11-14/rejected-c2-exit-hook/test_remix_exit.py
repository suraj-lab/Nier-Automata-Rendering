#!/usr/bin/env python3
"""Frozen gate (C2): opt-in orderly Remix teardown when the process calls ExitProcess.

Evidence for the design (analysis/replay/execution-2026-11-14/README.md, C2): with the real runtime the replayer
reaches atexit and ExitProcess, then never exits; a pre-exit watchdog proves the hang is after thread termination.
remixapi_Shutdown releases the D3D9 device to zero while the runtime's threads still run, so the proxy calls it on
the worker thread from a hook on the main executable's KERNEL32!ExitProcess import (NieR imports it directly).

Pins: default unchanged (no hook, no Shutdown); NIER_REMIX_EXIT=shutdown calls Shutdown on the worker thread before
the exit completes; a hanging Shutdown is bounded and the process still exits; Remix off installs nothing.
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

OUT = A / 'runtime' / 'remix-exit'
GPP = ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-static',
       '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor')]
KEYS = ['NIER_REMIX', 'NIER_REMIX_RUNTIME', 'NIER_REMIX_SCENE', 'NIER_REMIX_EXIT', 'MOCK_EXIT', 'MOCK_FRAME_MS',
        'FAKE_REMIX_SHUTDOWN_HANG']


def check():
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / 'wine' / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'wine' / 'xdg').chmod(0o700)
    os.environ.update(WINEPREFIX=str(OUT / 'wine/prefix'), HOME=str(OUT / 'wine/home'),
                      XDG_CACHE_HOME=str(OUT / 'wine/cache'), XDG_RUNTIME_DIR=str(OUT / 'wine/xdg'),
                      WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
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
            'NIER_REMIX_SCENE': 'Z:' + str(scene / 'scene.bin').replace('/', '\\'), 'MOCK_FRAME_MS': '40',
            'MOCK_EXIT': 'exitprocess'}

    def scenario(name, extra, remix=True):
        for key in KEYS:
            os.environ.pop(key, None)
        os.environ.update({**(live if remix else {'MOCK_EXIT': 'exitprocess'}), **extra})
        try:
            d, result, log = tmo.scenario(work, name, b'[Rendering]\r\nPreset=Custom75\r\n', True, (0, 0))
        finally:
            for key in KEYS:
                os.environ.pop(key, None)
        fake = (d / 'fake-remix.log').read_text() if (d / 'fake-remix.log').exists() else ''
        assert result.get('presented') == '80', f'{name}: {result}'
        assert result.get('exit_via') == 'exitprocess', f'{name}: mock did not exit through ExitProcess: {result}'
        return log, fake

    # 1. Default: today's exit. No hook, no Shutdown, no exit log line.
    log, fake = scenario('default', {})
    assert 'Startup' in fake, 'fake runtime never started'
    assert 'Shutdown' not in fake, 'default exit called Shutdown'
    assert 'remix: exit' not in log, 'default installed the exit hook'

    # 2. Opt-in: Shutdown runs, on the same thread that ran Startup (the worker), after the last Present.
    log, fake = scenario('shutdown', {'NIER_REMIX_EXIT': 'shutdown'})
    lines = fake.splitlines()
    shut = [i for i, l in enumerate(lines) if l.startswith('Shutdown')]
    assert len(shut) == 1, f'Shutdown calls: {len(shut)}'
    frames = [i for i, l in enumerate(lines) if l.startswith('Copy ')]  # the fake's per-frame record
    assert frames and frames[-1] < shut[0] and shut[0] == len(lines) - 1, 'runtime used after Shutdown'
    start_tid = re.search(r'^Startup-thread tid=(\d+)', fake, re.M)
    shut_tid = re.search(r'^Shutdown tid=(\d+)', fake, re.M)
    assert start_tid and shut_tid and start_tid.group(1) == shut_tid.group(1), \
        f'Shutdown not on the worker thread: {start_tid and start_tid.group(1)} vs {shut_tid and shut_tid.group(1)}'
    assert re.search(r'remix: exit requested', log), log[-800:]
    assert re.search(r'remix: shutdown complete in \d+ ms', log), log[-800:]

    # 3. A runtime whose Shutdown never returns: bounded, logged, and the process still exits through ExitProcess.
    log, fake = scenario('shutdown-hang', {'NIER_REMIX_EXIT': 'shutdown', 'FAKE_REMIX_SHUTDOWN_HANG': '1'})
    assert re.search(r'remix: shutdown timed out after \d+ ms', log), log[-800:]

    # 4. Remix off: the switch alone installs nothing.
    log, fake = scenario('remix-off', {'NIER_REMIX_EXIT': 'shutdown'}, remix=False)
    assert 'remix: exit' not in log and not fake, 'exit hook active without Remix'


def main():
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
