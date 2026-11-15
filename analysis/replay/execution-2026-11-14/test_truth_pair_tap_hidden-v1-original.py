#!/usr/bin/env python3
"""Hidden T1.1 gate (lead review): the tap's game camera must be the camera of the game frame being tapped,
not the camera the Remix frame was built from. MOCK_CAMERA_DRIFT moves the game camera every frame, so the
published Remix frame (built from an earlier camera) never matches: every record must be rejected-camera."""
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime' / 'truth-pair-tap'
sys.path.insert(0, str(C))
import test_menu_overlay as tmo
import test_nscn_scene as ts
from game_run_safety import cleanup, prepare_private_prefix


def check():
    work = Path(os.environ['T1_GATE_SESSION']) / 'work'
    work.mkdir()
    fixture = A / 'runtime/hud-evidence/ps_1888250464.dxbc'
    assert fixture.is_file(), 'native HUD fixture unavailable; gate not exercised'
    tmo.build(work)
    r = subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-static',
                        '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                        str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake.dll')], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1600:]
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
    win = lambda p: 'Z:' + str(p).replace('/', '\\')
    pairs = work / 'drift-pairs'; pairs.mkdir()
    tex = work / 'textures'; tex.mkdir()
    for key in list(os.environ):
        if key.startswith(('NIER_', 'MOCK_', 'FAKE_')) and key != 'NIER_RUN_TOKEN': os.environ.pop(key)
    os.environ.update({'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_RUNTIME': win(work / 'fake.dll'),
                       'NIER_REMIX_SCENE': win(scene / 'scene.bin'), 'MOCK_FRAME_MS': '40', 'MOCK_CAMERA': 'live-native-hud',
                       'MOCK_NATIVE_HUD_PS': win(fixture), 'NIER_REMIX_LIVE_TEX': win(tex),
                       'NIER_REMIX_LIVE_TRUTH_PAIR_DIR': win(pairs), 'MOCK_CAMERA_DRIFT': '1'})
    _, result, log = tmo.scenario(work, 'drift', b'[Rendering]\r\nPreset=Custom75\r\n', True, (0, 0))
    assert result.get('presented') == '80', result
    assert 'native HUD handoff' in log and 'live camera first sample' in log, 'drift scenario never exercised the tap'
    records = [json.loads(f.read_text()) for f in sorted(pairs.glob('*.json'))]
    assert 1 <= len(records) <= 4, ('tap did not run under a moving game camera', len(records))
    for m in records:
        assert m['status'] == 'rejected-camera' and m['camera_matched'] is False, \
            f"game camera taken from the Remix frame's input, not the tapped game frame: {m['status']}"
        assert m['game_camera_sequence'] > m['remix_camera_sequence'], 'camera sequences not from distinct sources'
    assert not list(pairs.glob('*.raw')), 'raw files written for a rejected pair'


def main():
    if sys.argv[1:] == ['--inside']:
        return check()
    OUT.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix='hidden-', dir=OUT))
    template = OUT / 'template'; template.mkdir(exist_ok=True)
    token = uuid.uuid4().hex
    prefix = prepare_private_prefix(template, session / 'prefix', token)
    for name in ['home', 'cache', 'xdg']:
        (session / name).mkdir()
    (session / 'xdg').chmod(0o700)
    env = os.environ.copy()
    env.update(T1_GATE_SESSION=str(session), WINEPREFIX=str(prefix), NIER_RUN_TOKEN=token,
               STEAM_COMPAT_DATA_PATH=str(prefix), HOME=str(session / 'home'), XDG_CACHE_HOME=str(session / 'cache'),
               XDG_RUNTIME_DIR=str(session / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               GALLIUM_DRIVER='llvmpipe', WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    try:
        subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable,
                        str(Path(__file__).resolve()), '--inside'], env=env, check=True, cwd=C)
    finally:
        cleanup(token, prefix)


if __name__ == '__main__':
    try:
        main(); print(json.dumps({'passed': True}))
    except (Exception, SystemExit) as exc:
        print(json.dumps({'passed': False, 'error': str(exc)[:1800]})); sys.exit(1)
