#!/usr/bin/env python3
"""Frozen W1.1 gate: opt-in sky-candidate census (NIER_REMIX_LIVE_SKY_CENSUS=1), diagnostic only.

At the world-extent decision (the only place the live path knows a draw is the background shell), log once per
geometry build a `remix: sky-census <JSON>` record for every candidate with world extent > 1000:
  version 1, frame, ps_code (FNV-1a 64 hex of the PS bytecode, like effect-census), indices, instances,
  extent (float), is_sky (extent > 5000, the existing rule), srv_ps (slot/kind/format plus width/height for
  textures), vs_cbs / ps_cbs ([{slot, bytes}] of bound constant buffers), rt {format,width,height}.
Bounded to 64 records per session. Default off: no records, no behaviour change (sky still submitted as SKY).
"""
import json
import re
import sys
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
sys.path.insert(0, str(C))
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts
import os
import subprocess
import tempfile

OUT = A / 'runtime' / 'sky-census'
tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE_SKY_CENSUS', 'NIER_REMIX_LIVE_TEX', 'FAKE_REMIX_INSTANCE_LOG')


def rows(log):
    return [json.loads(l.split('remix: sky-census ', 1)[1]) for l in log.splitlines() if 'remix: sky-census {' in l]


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    tmo.build(work)
    r = subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-static',
                        '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                        str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
    base = {'NIER_REMIX_LIVE_GREY_FIRST': '0', 'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'),
            'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'), 'MOCK_FRAME_MS': '40', 'MOCK_CAMERA': 'live',
            'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'FAKE_REMIX_INSTANCE_LOG': '1'}
    tex = work / 'tex-off'; tex.mkdir()
    _, _, log, fake_off = tr.run(work, 'off', base | {'NIER_REMIX_LIVE_TEX': tr.win(tex)})
    assert not rows(log) and 'remix: sky-census' not in log, 'sky census active by default'
    tex = work / 'tex-on'; tex.mkdir()
    _, _, log, fake_on = tr.run(work, 'on', base | {'NIER_REMIX_LIVE_TEX': tr.win(tex), 'NIER_REMIX_LIVE_SKY_CENSUS': '1'})
    got = rows(log)
    assert got, 'no sky-census records with the switch on'
    assert len(got) <= 64, 'unbounded'
    sky = [x for x in got if x['is_sky']]
    assert sky, 'the mock sky dome was not recorded as is_sky'
    for x in got:
        assert x['version'] == 1 and isinstance(x['frame'], int)
        assert re.fullmatch(r'[0-9a-f]{16}', x['ps_code']), x['ps_code']
        assert x['extent'] > 1000 and x['is_sky'] == (x['extent'] > 5000), x
        assert isinstance(x['indices'], int) and x['indices'] > 0 and x['instances'] >= 1
        for key in ('vs_cbs', 'ps_cbs'):
            assert isinstance(x[key], list) and all(set(c) == {'slot', 'bytes'} and c['bytes'] > 0 for c in x[key]), (key, x[key])
        assert all('slot' in s and 'kind' in s for s in x['srv_ps'])
        assert all(s['width'] > 0 and s['height'] > 0 for s in x['srv_ps'] if s['kind'] in ('texture2d', 'cube')), x['srv_ps']
        assert set(x['rt']) == {'format', 'width', 'height'}
    assert any(x['vs_cbs'] for x in sky), 'sky draw CB usage not recorded'
    # One record per geometry build, not one per frame (80 frames of the same dome).
    assert len(sky) <= 4, f'sky recorded per frame, not per build: {len(sky)}'
    # Diagnostic only: identical submissions with and without the census.
    norm = lambda f: sorted(l for l in (f or '').splitlines() if l.startswith(('CreateMesh', 'DrawInstance')))
    assert fake_on and fake_off and len(norm(fake_on)) == len(norm(fake_off)), 'census changed what is submitted'
    assert any('flags=' in l for l in fake_on.splitlines() if l.startswith('DrawInstance')), 'sky no longer submitted'


def main():
    if sys.argv[1:] == ['--inside']:
        return inside()
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    env = os.environ.copy()
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               GALLIUM_DRIVER='llvmpipe', WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    try:
        subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable, str(Path(__file__).resolve()), '--inside'],
                       env=env, check=True, cwd=C)
    finally:
        subprocess.run(['wineserver', '-k'], env=env, capture_output=True)


if __name__ == '__main__':
    try:
        main(); print(json.dumps({'passed': True}))
    except (Exception, SystemExit) as exc:
        print(json.dumps({'passed': False, 'error': str(exc)[:1800]})); sys.exit(1)
