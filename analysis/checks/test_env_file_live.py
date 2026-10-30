#!/usr/bin/env python3
"""Gate: NIER_ENV.ini beside the proxy turns on Remix exactly like the environment does, and the environment wins.

Why: a Windows Steam launch cannot set environment variables, and a direct launch brings the Steam overlay in
regardless of the per-game toggle (laptop, 2026-10-30). Three runs of the mock game with the fake runtime:
  file only            -> Remix starts (fake runtime sees Startup); log "3 settings applied, 0 already set"
  file + NIER_REMIX=0  -> Remix stays off; log "2 settings applied, 1 already set"
  neither (control)    -> Remix stays off, no NIER_ENV.ini line
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/env-file-live'
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts


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
        env_ini = ('# settings for a Steam launch\r\nNIER_REMIX=1\r\n'
                   f'NIER_REMIX_RUNTIME={tr.win(work / "fake_remix.dll")}\r\n'
                   f'NIER_REMIX_SCENE={tr.win(scene / "scene.bin")}\r\n').encode()

        def run(name, env, files):
            for k in tr.ENV_KEYS:
                os.environ.pop(k, None)
            os.environ.update({'MOCK_FRAME_MS': '40', **env})
            try:
                d, r, log = tmo.scenario(work, name, b'[Rendering]\r\nPreset=Custom75\r\n', True, (0, 0), files)
            finally:
                for k in tr.ENV_KEYS:
                    os.environ.pop(k, None)
            fake = (d / 'fake-remix.log').read_text() if (d / 'fake-remix.log').exists() else ''
            line = next((x for x in log.splitlines() if 'NIER_ENV.ini' in x), '')
            return fake, line

        fake, line = run('file', {}, {'NIER_ENV.ini': env_ini})
        assert 'Startup' in fake and 'VIOLATION' not in fake, f'Remix did not start from NIER_ENV.ini: {fake[:300]!r}'
        assert '3 settings applied, 0 already set' in line, line
        results['file'] = line.split(' ', 2)[-1]

        fake, line = run('env-wins', {'NIER_REMIX': '0'}, {'NIER_ENV.ini': env_ini})
        assert 'Startup' not in fake, 'NIER_ENV.ini overrode NIER_REMIX=0 from the environment'
        assert '2 settings applied, 1 already set' in line, line
        results['env-wins'] = line.split(' ', 2)[-1]

        fake, line = run('control', {}, {})
        assert 'Startup' not in fake and not line, 'Remix started with neither file nor environment'
        results['control'] = 'no file, no environment: Remix off'
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-2000:], 'results': results,
                                                         'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results, 'limits': 'Wine mock + fake runtime; not a real Steam launch.'}
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
