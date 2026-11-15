#!/usr/bin/env python3
"""Frozen E1.1 gate: opt-in bounded metadata for t27/t30 effects BEFORE the small-index rejection.

No effect submission/composite is authorized. Real shader/resource/state fixtures through Wine's D3D11 mock;
production emits `remix: effect-census <JSON>` on its worker. Limits: 256 records/session, 64/frame. Resource
metadata only (never Map/copy buffers). VS/PS SRV views carry slot/kind/stride/first/count, not guessed semantics.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime' / 'effect-census'
sys.path.insert(0, str(C))
import test_menu_overlay as tmo
import test_nscn_scene as ts
import dump_shader_decls as decls


def reference(src, dst, index_count):
    return {'version': 1, 'indices': index_count, 'instances': 1, 'small': index_count < 128,
            'topology': 4,
            'blend': {'enable': True, 'src': src, 'dst': dst, 'op': 1, 'src_alpha': 2,
                      'dst_alpha': 1, 'op_alpha': 1, 'write_mask': 15},
            'rt': {'format': 28, 'width': 1920, 'height': 1080, 'samples': 1},
            'depth': {'enabled': True, 'write': False, 'func': 5}}


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    tmo.build(work)
    gpp = ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
           '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor')]
    r = subprocess.run([*gpp, str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake.dll')],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
    def win(p):
        return 'Z:' + str(p).replace('/', '\\')
    base = {'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_RUNTIME': win(work / 'fake.dll'),
            'NIER_REMIX_SCENE': win(scene / 'scene.bin'), 'MOCK_FRAME_MS': '40',
            'NIER_REMIX_LIVE_STATS_EVERY': '2', 'NIER_REMIX_LIVE_TEX': win(work / 'textures')}
    (work / 'textures').mkdir()
    for name, camera, slot, count, enabled, blend in [
        ('off-small', 'live-blend', '27', 6, False, (5, 6)),
        ('negative-ordinary', 'live-blend', None, 192, True, (5, 6)),
        ('small-t27', 'live-blend', '27', 6, True, (5, 6)),
        ('small-t30', 'live-additive', '30', 6, True, (2, 2)),
        ('full-t27', 'live-blend', '27', 192, True, (5, 6)),
    ]:
        saved = os.environ.copy()
        try:
            for key in list(os.environ):
                if key.startswith(('NIER_', 'MOCK_', 'FAKE_')):
                    os.environ.pop(key)
            os.environ.update(base | {'MOCK_CAMERA': camera})
            if slot: os.environ['MOCK_EFFECT_REGISTER'] = slot
            if count == 6: os.environ['MOCK_EFFECT_SMALL'] = '1'
            if enabled: os.environ['NIER_REMIX_LIVE_EFFECT_CENSUS'] = '1'
            if name == 'full-t27': os.environ['MOCK_LIVE_DRAWS'] = '100'  # exercise per-frame and session bounds
            d, result, log = tmo.scenario(work, name, b'[Rendering]\r\nPreset=Custom75\r\n', True, (0, 0))
        finally:
            os.environ.clear()
            os.environ.update(saved)
        assert result.get('presented') == '80', result
        rows = [json.loads(line.split('remix: effect-census ', 1)[1]) for line in log.splitlines()
                if 'remix: effect-census ' in line]
        if not enabled or not slot:
            assert not rows, (name, 'census active by default or ordinary shader misclassified')
            continue
        assert rows, f'{name}: no effect census (small draws must be counted before rejection)'
        assert len(rows) <= 256, (name, 'unbounded session output', len(rows))
        assert max(Counter(r['frame'] for r in rows).values()) <= 64, 'unbounded per-frame metadata'
        # Independent bytecode identity: current fixture captures the shader bytes; FNV must match those bytes.
        codes = set()
        for f in (d / 'NIER_CAPTURE/shaders').glob('*.dxbc'):
            b = f.read_bytes()
            chunks = decls.chunks(b)
            if 'RDEF' not in chunks: continue
            _, resources = decls.declarations(chunks['RDEF'][0])
            if not any(x[1] == 'structured' and x[2] == int(slot) for x in resources): continue
            fnv = 0xcbf29ce484222325
            for byte in b: fnv = ((fnv ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
            codes.add(f'{fnv:016x}')
        assert codes, 'fixture shader bytecode not found'
        expected = reference(*blend, count)
        matched = []
        for row in rows:
            assert str(row['ps_code']).lower() in codes, 'census shader identity not verified by bytecode'
            if not all(row.get(k) == v for k, v in expected.items()): continue
            ps = row['srv_ps']; vs = row['srv_vs']
            if not any(x == {'slot': int(slot), 'kind': 'structured', 'stride': 48, 'first': 1, 'count': 2} for x in ps): continue
            if not any(x == {'slot': 31, 'kind': 'structured', 'stride': 80, 'first': 0, 'count': 1} for x in vs): continue
            matched.append(row)
        assert matched, f'{name}: wrong state/resource metadata: {rows[-1]}'


def main():
    if sys.argv[1:] == ['--inside']:
        return inside()
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    env = os.environ.copy()
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable, str(Path(__file__).resolve()), '--inside'],
                   env=env, check=True, cwd=C)


if __name__ == '__main__':
    try:
        main()
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)[:1800]}))
        sys.exit(1)
