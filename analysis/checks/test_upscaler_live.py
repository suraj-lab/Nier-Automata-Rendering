#!/usr/bin/env python3
"""Frozen gate: the proxy applies the P1 upscaler selection to the runtime, from the worker thread.

Drives the existing Wine mock + recording fake runtime (same harness as test_remix_live.py) and reads the fake
runtime's own call log. Pins: default no-op, exact ordered writes, an invalid value rejected without writes, and a
runtime without SetConfigVariable handled without a crash or a silent claim of success.
"""
import json
import sys
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
sys.path.insert(0, str(C))
import test_menu_overlay as tmo  # noqa: E402
import test_nscn_scene as ts  # noqa: E402  (NSCN writer)
GPP = ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-static',
       '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor')]
KEYS = ['NIER_REMIX', 'NIER_REMIX_RUNTIME', 'NIER_REMIX_SCENE', 'NIER_REMIX_LIVE_UPSCALER', 'FAKE_REMIX_NO_CONFIG',
        'FAKE_REMIX_CONFIG_FAIL', 'MOCK_FRAME_MS']
EXPECTED = {
    'balanced': [('rtx.dlssPreset', '2'), ('rtx.qualityDLSS', '2'), ('rtx.xess.preset', '2')],
}


def config_calls(fake):
    if not fake:
        return []
    out = []
    for line in fake.splitlines():
        if line.startswith('SetConfigVariable '):
            _, key, value = line.split(' ', 2)
            out.append((key, value))
    return out


def check():
    import os
    import subprocess
    import tempfile

    # A repo-local, already-warm Wine prefix: the suite sandboxes HOME, and provisioning a fresh prefix under 14
    # parallel lanes takes longer than the 180 s per-scenario timeout.
    prefix = tmo.OUT / 'wine/prefix'
    for name in ('home', 'cache', 'xdg'):
        (tmo.OUT / 'wine' / name).mkdir(parents=True, exist_ok=True)
    (tmo.OUT / 'wine' / 'xdg').chmod(0o700)
    os.environ.update(WINEPREFIX=str(prefix), HOME=str(tmo.OUT / 'wine/home'),
                      XDG_CACHE_HOME=str(tmo.OUT / 'wine/cache'),
                      XDG_RUNTIME_DIR=str(tmo.OUT / 'wine/xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='',
                      LIBGL_ALWAYS_SOFTWARE='1',
                      WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    work = Path(tempfile.mkdtemp(prefix='upscaler-', dir=tmo.OUT))
    tmo.build(work)
    built = subprocess.run([*GPP, '-shared', str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9',
                            '-o', str(work / 'fake_remix.dll')], capture_output=True, text=True)
    assert built.returncode == 0, 'fake runtime build:\n' + built.stderr[-2000:]
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
    live = {'NIER_REMIX': '1', 'NIER_REMIX_RUNTIME': 'Z:' + str(work / 'fake_remix.dll').replace('/', '\\'),
            'NIER_REMIX_SCENE': 'Z:' + str(scene / 'scene.bin').replace('/', '\\'), 'MOCK_FRAME_MS': '40'}

    def scenario(name, extra):
        for key in KEYS:
            os.environ.pop(key, None)
        os.environ.update({**live, **extra})
        try:
            d, result, log = tmo.scenario(work, name, b'[Rendering]\r\nPreset=Custom75\r\n', True, (0, 0))
        finally:
            for key in KEYS:
                os.environ.pop(key, None)
        fake = (d / 'fake-remix.log').read_text() if (d / 'fake-remix.log').exists() else None
        return result, log, fake

    # 1. Default: today's behaviour. No key is written, so whatever the runtime already has stays.
    result, log, fake = scenario('upscaler-unset', {})
    assert config_calls(fake) == [], f'unset wrote config: {config_calls(fake)}'
    assert 'upscaler selection' not in log.lower(), 'unset upscaler logged a selection'

    # 2. A named mode: exactly the ordered writes the native gate pins, nothing else.
    result, log, fake = scenario('upscaler-balanced', {'NIER_REMIX_LIVE_UPSCALER': 'balanced'})
    assert config_calls(fake) == EXPECTED['balanced'], config_calls(fake)

    # Each mode, once; all accepted config calls must be on the same thread as Startup, never the UI thread.
    import re
    for mode, value in [('ultra-performance', '0'), ('performance', '1'), ('quality', '3')]:
        result, log, fake = scenario('mode-' + mode, {'NIER_REMIX_LIVE_UPSCALER': mode})
        assert config_calls(fake) == [('rtx.dlssPreset', '2'), ('rtx.qualityDLSS', value), ('rtx.xess.preset', value)], (mode, config_calls(fake))
        owner = re.search(r'^Startup-thread tid=(\d+)$', fake, re.M)
        tids = re.findall(r'^Config-thread tid=(\d+)$', fake, re.M)
        assert owner and tids == [owner.group(1)] * 3, (mode, tids)

    # 3. Invalid value: refused, no partial writes, and said out loud.
    result, log, fake = scenario('upscaler-invalid', {'NIER_REMIX_LIVE_UPSCALER': 'ultra-super'})
    assert config_calls(fake) == [], f'invalid value still wrote: {config_calls(fake)}'
    assert 'upscaler selection' in log.lower() and 'ultra-super' in log, 'invalid value not reported'

    # 4. Runtime without SetConfigVariable: no crash, no writes, and the skip is reported rather than assumed.
    result, log, fake = scenario('upscaler-absent', {'NIER_REMIX_LIVE_UPSCALER': 'quality',
                                                     'FAKE_REMIX_NO_CONFIG': '1'})
    assert config_calls(fake) == [], config_calls(fake)
    assert 'SetConfigVariable' in log and 'upscaler selection' in log.lower(), 'missing API member not reported'


def main():
    # Same display handling as test_remix_live.py: the suite shim turns `-a` into a per-lane display, and wine needs one.
    if sys.argv[1:] == ['--inside']:
        return check()
    import os
    import subprocess
    if not os.environ.get('DISPLAY'):
        subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable,
                        str(Path(__file__).resolve()), '--inside'], check=True, cwd=Path(__file__).resolve().parent)
        return
    return check()


if __name__ == '__main__':
    try:
        main()
        print(json.dumps({'passed': True}))
    except (Exception, SystemExit) as exc:
        error = f'candidate exited early: {exc.code}' if isinstance(exc, SystemExit) else str(exc)
        print(json.dumps({'passed': False, 'error': error}))
        sys.exit(1)
