#!/usr/bin/env python3
"""Wine mock gate: CPU skinning updates with CB11 and keeps two simultaneous poses of shared geometry distinct."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-skinning-capture'
import test_live_geometry as tg
tr, tmo, ts = tg.tr, tg.tmo, tg.ts


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    try:
        tmo.build(work)
        subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                        str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
        scene = work / 'scene'
        (scene / 'scene_textures').mkdir(parents=True)
        (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
        tex = work / 'textures'
        tex.mkdir()
        _, r, log, fake = tr.run(work, 'poses', {'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'),
            'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'), 'MOCK_FRAME_MS': '40', 'MOCK_CAMERA': 'live-skin-poses',
            'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex), 'FAKE_REMIX_INSTANCE_LOG': '1'})
        assert fake and 'VIOLATION' not in fake, (fake or log)[-2000:]
        meshes = [l for l in fake.splitlines() if l.startswith('CreateMesh') and 'indices=192 ' in l]
        assert meshes and all('skinned=0 ' in l for l in meshes), 'GPU skinning data still submitted: ' + str(meshes[:2])
        by_pose = {}
        for l in meshes:
            x = float(re.search(r'v0=([-\d.]+),', l).group(1))
            by_pose.setdefault(x, set()).add(re.search(r'hash=(\d+)', l).group(1))
        assert set(by_pose) == {0, 10, 20, 30}, f'pose updates or simultaneous characters lost: {by_pose}'
        assert len(set.union(*by_pose.values())) == 4, 'different poses alias a mesh key'
        assert len(meshes) <= 5, f'unchanged poses rebuilt every frame: {len(meshes)}'
        draws = [l for l in fake.splitlines() if l.startswith('DrawInstance')]
        assert draws and all('bones=0 ' in l and 'row0=1.000,0.000,0.000,0.000' in l for l in draws), 'double transform/GPU palette'
        assert int(r['geometry_reads']) <= 3, f'CPU skinning introduced per-frame geometry readback: {r}'
        report = {'passed': True, 'work': str(work), 'poses': sorted(by_pose), 'meshes': len(meshes),
                  'limits': 'Real proxy in a software Wine mock, not the real Remix runtime or live game.'}
        (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'work': str(work), 'error': str(exc)[-2200:]}) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)


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
