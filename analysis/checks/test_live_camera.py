#!/usr/bin/env python3
"""Live camera integration gate: real proxy + mock game + fake Remix, isolated Wine/Xvfb/llvmpipe.
Proves DrawIndexed/Instanced -> bounded CB0 readback -> decoder -> Remix SetupCamera, not real game compatibility.
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
OUT = A / 'runtime/live-camera'
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    results = {}
    try:
        # Verify every spy/hook slot against the installed SDK, not another reviewer's assertion.
        probe = work / 'slots.cpp'
        probe.write_text('''#define CINTERFACE
#include <d3d11.h>
#include <cstddef>
static_assert(offsetof(ID3D11DeviceContextVtbl, CopyResource)/sizeof(void*) == 47);
static_assert(offsetof(ID3D11DeviceContextVtbl, DrawIndexed)/sizeof(void*) == 12);
static_assert(offsetof(ID3D11DeviceContextVtbl, DrawIndexedInstanced)/sizeof(void*) == 20);
static_assert(offsetof(ID3D11DeviceContextVtbl, Map)/sizeof(void*) == 14);
static_assert(offsetof(ID3D11DeviceContextVtbl, Unmap)/sizeof(void*) == 15);
static_assert(offsetof(ID3D11DeviceContextVtbl, CopySubresourceRegion)/sizeof(void*) == 46);
static_assert(offsetof(ID3D11DeviceContextVtbl, UpdateSubresource)/sizeof(void*) == 48);
static_assert(offsetof(ID3D11DeviceVtbl, CreateBuffer)/sizeof(void*) == 3);
static_assert(offsetof(ID3D11DeviceVtbl, CreateInputLayout)/sizeof(void*) == 11);
''')
        subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-c', str(probe), '-o', str(work / 'slots.o')], check=True)
        tmo.build(work)
        subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                        str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
        scene = work / 'scene'
        (scene / 'scene_textures').mkdir(parents=True)
        (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
        on = {'NIER_REMIX': '1', 'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'),
              'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'), 'MOCK_FRAME_MS': '60',
              'MOCK_CAMERA': '1', 'FAKE_REMIX_CAMERA_LOG': '1'}
        _, r, _, fake = tr.run(work, 'off', {'MOCK_CAMERA': '1'})
        assert fake is None and r['camera_reads'] == '0' and r['geometry_reads'] == '0', r
        results['off'] = 'No constant/vertex/index-buffer readbacks with Remix disabled.'

        def run(name, mode='1', fonts=True, expected_presented=80):
            d, r, log, fake = tr.run(work, name, {**on, 'MOCK_CAMERA': mode}, fonts=fonts, expected_presented=expected_presented)
            assert fake and 'VIOLATION' not in fake, fake
            assert r['geometry_reads'] == '0' and r['cs_lost'] == '0', r
            assert fake.count('CreateMesh ') == 1, 'Camera changes must not rebuild meshes.'
            assert not any('disabled' in l for l in tr.remix_lines(log)), log
            assert tmo.near(tr.rgb((d / 'capture-after.raw').read_bytes(), *tr.PROBE), tr.REMIX), 'Remix output lost'
            samples = re.findall(r'Camera pos=([-\d.,]+) forward=([-\d.,]+) fov=([\d.]+) aspect=([\d.]+)', fake)
            assert samples, 'Fake runtime must observe actual SetupCamera inputs.'
            return r, samples

        def moving(name, mode='1', fonts=True, expected_presented=80):
            r, samples = run(name, mode, fonts, expected_presented)
            poses = {x[0] for x in samples}
            assert '10.000,2.000,30.000' in poses and '40.000,5.000,60.000' in poses, poses
            assert '999.000,999.000,999.000' not in poses, 'Downstream Present sentinel was captured as a game camera.'
            assert any(x[1] == '-0.000,-0.000,-1.000' and x[2] == '90.00' for x in samples), samples[-3:]
            assert all(abs(float(x[3]) - 1920 / 1080) < 1e-3 for x in samples)
            assert 20 <= int(r['camera_reads']) <= 79 and r['peak_camera_reads'] == '1', r
            results[name] = 'Both camera poses reach SetupCamera; <=1 CB readback per frame; no VB/IB reads or mesh rebuilds.'
            return r

        moving('indexed')
        moving('instanced', 'instanced')
        moving('no-fonts', fonts=False)  # live path must not depend on menu initialization succeeding
        moving('present-boundary', 'present-boundary')
        r = moving('present-fail', 'present-fail', expected_presented=79)
        assert r['reads_after_failed_present'] == '0', r
        results['present-fail'] = 'Failed Present does not rearm capture; downstream sentinel never reaches Remix.'
        d, r, log, fake = tr.run(work, 'fail-before-draw', {**on, 'MOCK_CAMERA': 'fail-before-draw'})
        assert r['failure_observed'] == '1' and r['reads_after_failure'] == '0', r
        assert fake and 'VIOLATION' not in fake and 'failing on request' in fake, fake
        assert tmo.near(tr.rgb((d / 'capture-after.raw').read_bytes(), *tr.PROBE), tr.BACKGROUND), 'Game fallback lost after worker failure.'
        results['fail-before-draw'] = 'Worker failure revokes an already-armed capture before the next game draw.'
        r, samples = run('invalid', 'invalid')
        assert all(x[2] == '50.00' for x in samples), samples[-3:]
        assert r['peak_camera_reads'] == '4' and int(r['camera_reads']) <= 4 * 79, r
        results['invalid'] = 'Malformed camera retains static scene camera; readbacks capped at 4 per frame.'
        r, samples = run('invalid-late', 'invalid-late')
        poses = {x[0] for x in samples}
        assert '10.000,2.000,30.000' in poses and '40.000,5.000,60.000' not in poses, poses
        assert all(x[0] == '10.000,2.000,30.000' for x in samples[-10:]), samples[-10:]
        assert r['peak_camera_reads'] == '4' and int(r['camera_reads']) <= 4 * 79, r
        results['invalid-late'] = 'Invalid later samples cannot overwrite the most recent valid camera.'
        d, r, log, fake = tr.run(work, 'bypass', {**on, 'MOCK_CAMERA': 'bypass'})
        assert tmo.near(tr.rgb((d / 'capture-closed.raw').read_bytes(), *tr.PROBE), tr.BACKGROUND), 'F10 must show original game frames.'
        assert tmo.near(tr.rgb((d / 'capture-open.raw').read_bytes(), 1920 - 32 - 552 + 10, 52), tr.SURFACE), 'Insert menu lost while bypassed.'
        assert tmo.near(tr.rgb((d / 'capture-after.raw').read_bytes(), *tr.PROBE), tr.REMIX), 'Second F10 must resume Remix.'
        assert r['reads_while_bypassed'] == '0' and r['geometry_reads'] == '0' and r['cs_lost'] == '0', r
        lines = tr.remix_lines(log)
        assert sum('F10 original-game view' in x for x in lines) == 2, lines
        assert fake.count('CreateMesh ') == 1 and 'VIOLATION' not in fake, fake
        results['bypass'] = 'F10 original view, no camera readbacks while bypassed, Insert intact, F10 resumes without rebuilding mesh.'
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-3000:], 'results': results, 'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results, 'dll_sha256': hashlib.sha256((tmo.DLL / 'd3d11.dll').read_bytes()).hexdigest(),
              'limits': 'Software-only Wine mock, fake Remix; not real game or live draw/pass selector validation.'}
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
