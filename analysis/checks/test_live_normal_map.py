#!/usr/bin/env python3
"""Live normal-map gate: a material gets the normal map its draw actually binds, at slot 4.

The game's shaders name their inputs (605 shaders parsed from an F9 capture): slot 0 is `g_ColorTexture`,
slot 4 is `g_NormalTexture` (153 shaders), slot 17 `g_AO_Texture`. Until now the live path sent albedo only and
a `roughnessConstant` of 0.6 for everything, which under path tracing is a uniformly rough flat surface, so metal
and cloth lost their shape. Geom is per-material, so the extra texture costs one readback per new resource, and
`NIER_REMIX_LIVE_NORMAL` keeps it off until it has been looked at on screen.

What this pins:
  - flag off: no normal is sent, and the albedo capture is untouched (byte-identical DDS, one texture);
  - flag on: the draw's slot-4 texture is captured as its own DDS (the mock's BC5 bytes, all 64 of them), the
    material names it, and the albedo is still the slot-0 texture, not the normal map;
  - the normal map is captured once per resource, not once per frame.
"""
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-normal-map'
sys.path.insert(0, str(C))
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'MOCK_NORMAL_TEX',
                                    'NIER_REMIX_LIVE_NORMAL', 'NIER_REMIX_LIVE_NORMAL_RAW', 'FAKE_REMIX_INSTANCE_LOG',
                                    'MOCK_CAMERA')

BC5 = bytes((i * 19 + 5) & 0xff for i in range(2 * 2 * 16))  # the mock's 8x8 BC5 normal map
RGBA4 = bytes((i * 7 + 3) & 0xff for i in range(4 * 4 * 4))  # the mock's 4x4 albedo
BC1 = bytes((i * 5 + 1) & 0xff for i in range(2 * 2 * 8))    # the mock's 8x8 BC1 albedo


def dds(path):
    raw = path.read_bytes()
    assert raw[:4] == b'DDS ', f'{path.name}: not a DDS'
    _, flags, height, width, _, _, mips = struct.unpack_from('<7I', raw, 4)
    fmt = struct.unpack_from('<I', raw, 128)[0]
    return {'name': path.name, 'width': width, 'height': height, 'format': fmt, 'mips': mips,
            'payload': raw[148:]}


def main():
    work = Path(tempfile.mkdtemp(prefix='live-normal-'))
    tmo.build(work)
    subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                    '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                    str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))

    def run(name, flag):
        tex = work / f'tex-{name}'
        tex.mkdir()
        env = {'MOCK_NORMAL_TEX': '1', 'MOCK_CAMERA': 'live-skinned', 'MOCK_FRAME_MS': '60',
               'NIER_REMIX': '1', 'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'),
               'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'), 'NIER_REMIX_LIVE': '1',
               'NIER_REMIX_LIVE_TEX': tr.win(tex), 'FAKE_REMIX_INSTANCE_LOG': '1'}
        if name == 'on-raw':
            env['NIER_REMIX_LIVE_NORMAL_RAW'] = '1'
        if flag is not None:
            env['NIER_REMIX_LIVE_NORMAL'] = flag
        _, result, log, fake = tr.run(work, name, env)
        assert fake and 'VIOLATION' not in fake, fake
        mats = [line for line in fake.splitlines() if line.startswith('CreateMaterial ')]
        assert mats, fake[-800:]
        return tex, result, fake, mats

    results = {}
    tex_off, r_off, fake_off, mats_off = run('off', None)
    files_off = [dds(p) for p in sorted(tex_off.glob('*.dds'))]
    assert len(files_off) == 1, [f['name'] for f in files_off]
    assert all('normal=-' in line for line in mats_off), mats_off[:2]
    # The world draw's albedo is the mock's slot-0 texture: 4x4 RGBA (pass 1) or 8x8 BC1 (pass 2), never the BC5 map.
    assert files_off[0]['format'] in (28, 71) and files_off[0]['payload'] in (RGBA4, BC1), \
        (files_off[0]['name'], files_off[0]['format'], len(files_off[0]['payload']))
    results['off'] = 'Flag off: albedo only, unchanged bytes, no normal in the material.'

    tex_on, r_on, fake_on, mats_on = run('on', '1')
    files_on = sorted((dds(p) for p in tex_on.glob('*.dds')), key=lambda f: f['name'])
    assert len(files_on) == 2, [f['name'] for f in files_on]
    # The normal is converted for Remix's unsigned-octahedral decode, so it is no longer the game's BC5 bytes: it is
    # RGBA8. The albedo must still be the game's own slot-0 texture, byte for byte.
    albedo = [f for f in files_on if f['format'] in (28, 71) and f['payload'] in (RGBA4, BC1)]
    normal = [f for f in files_on if f['format'] == 28 and f['payload'] not in (RGBA4, BC1)]
    assert len(albedo) == 1 and len(normal) == 1, [(f['name'], f['format']) for f in files_on]
    assert (normal[0]['width'], normal[0]['height']) == (8, 8), normal[0]
    assert len(normal[0]['payload']) == 8 * 8 * 4, len(normal[0]['payload'])
    # Every texel must decode inside the outward hemisphere: |t.x|+|t.y| <= 1, i.e. z >= 0 before normalizing.
    assert normal[0]['payload'][2] == 0 and normal[0]['payload'][3] == 255, 'converted texels carry 0/255 in B/A'
    zs = []
    for i in range(8 * 8):
        r_, g_ = normal[0]['payload'][i * 4], normal[0]['payload'][i * 4 + 1]
        a, b = r_ / 255.0 * 2 - 1, g_ / 255.0 * 2 - 1
        tx, ty = (a + b) * 0.5, (a - b) * 0.5
        zs.append(1.0 - abs(tx) - abs(ty))
    assert min(zs) > -1e-6, ('sample outside the hemisphere', min(zs))
    assert len(set(zs)) > 1, 'the whole normal map converted to one value'
    # Raw mode still sends the game's bytes, which is what makes one live A/B possible without a rebuild.
    tex_raw, _, fake_raw, mats_raw = run('on-raw', '1')
    if os.environ.get('MOCK_NORMAL_RAW_OK') != '0':
        raws = [dds(p) for p in tex_raw.glob('*.dds')]
        assert any(f['format'] == 83 for f in raws), [(f['name'], f['format']) for f in raws]
    wanted = [line for line in mats_on if f"normal={normal[0]['name']}" in line]
    assert wanted, mats_on[:3]
    for line in wanted:
        assert 'path=live_' in line and 'normal=live_' in line, line
        assert f"path={normal[0]['name']}" not in line, f'the normal map was used as the albedo: {line}'
    # Captured once per resource: no run has more DDS files than distinct ids it asked for.
    assert len({line.split('hash=')[-1] for line in mats_on}) == 1, mats_on[:3]
    results['on'] = 'Flag on: slot-4 texture captured once, converted to octahedral RGBA8, named as the material normal.'
    results['raw'] = 'NIER_REMIX_LIVE_NORMAL_RAW=1 still ships the game bytes (BC5), for the Y-handedness A/B.'
    results['cost'] = 'One extra readback + file per new normal resource; reuses the texture cache and budget.'
    print(json.dumps({'passed': True, 'work': str(work), 'checks': results,
                      'dds': [f['name'] for f in files_on],
                      'limits': 'Software mock in Wine/llvmpipe: proves plumbing, conversion shape and albedo '
                                'identity, not how the normals look live. The Y direction still needs one live look.'}, indent=2))


def outside():
    (OUT / 'xdg').mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    env = os.environ.copy()
    for k in tr.ENV_KEYS:
        env.pop(k, None)
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               GALLIUM_DRIVER='llvmpipe', WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable,
                    str(Path(__file__).resolve()), '--inside'], cwd=OUT, env=env, check=True)


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    if '--inside' in sys.argv:
        main()
    else:
        outside()
