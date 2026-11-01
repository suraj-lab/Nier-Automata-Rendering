#!/usr/bin/env python3
"""Live material gate: each material input comes from the slot the draw's own pixel shader uses for it.

analysis/PBR_MAPPING.md: NieR's world shaders read albedo, a mask (R metal, G gloss), a normal map (slot 3 in the main
variants) and a 2-channel *detail* normal (slot 4); the effects shaders call slot 4 g_NormalTexture. The live path used
to send slot 4 as the normal map for every draw. Now material_roles.h reads the roles from the shader's disassembly.

What this pins (Wine mock, fake runtime):
  - a shader with no traceable roles gets no normal map and no PBR textures, even with a BC5 bound at slot 4;
  - a NieR-like shader (MOCK_PBR_PS) gets metallic = mask R and roughness = max(1 - mask G, floor) as R8 DDS files,
    named by its material; the floor defaults to 0.15 (NIER_REMIX_LIVE_ROUGHNESS_FLOOR=0 removes it);
  - with NIER_REMIX_LIVE_NORMAL=1 its normal map is the slot-3 texture (4x4, converted to octahedral), never the
    slot-4 detail map (8x8 BC5); NIER_REMIX_LIVE_PBR=0 sends no metallic/roughness.
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
                                    'MOCK_CAMERA', 'MOCK_PBR_PS', 'NIER_REMIX_LIVE_PBR', 'NIER_REMIX_LIVE_ROUGHNESS_FLOOR', 'MOCK_UV_PS',
                                    'MOCK_SMALL_DRAW', 'NIER_REMIX_LIVE_MIN_INDICES')

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

    def run(name, extra):
        tex = work / f'tex-{name}'
        tex.mkdir()
        env = {'MOCK_NORMAL_TEX': '1', 'MOCK_CAMERA': 'live-skinned', 'MOCK_FRAME_MS': '60',
               'NIER_REMIX': '1', 'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'),
               'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'), 'NIER_REMIX_LIVE': '1',
               'NIER_REMIX_LIVE_TEX': tr.win(tex), 'FAKE_REMIX_INSTANCE_LOG': '1', **extra}
        _, result, log, fake = tr.run(work, name, env)
        assert fake and 'VIOLATION' not in fake, fake
        mats = [line for line in fake.splitlines() if line.startswith('CreateMaterial ')]
        assert mats, fake[-800:]
        files = {f['name']: f for f in (dds(p) for p in sorted(tex.glob('*.dds')))}
        notes[name] = [line.split('remix: ', 1)[1] for line in log.splitlines() if 'remix: material ps=' in line]
        fakes[name] = fake
        smalls[name] = [line.split('remix: ', 1)[1] for line in log.splitlines() if 'remix: small ps=' in line]
        return files, mats

    def field(line, key):
        return line.split(f'{key}=')[1].split()[0]

    results = {}
    notes = {}
    fakes = {}
    smalls = {}
    # 1. No traceable roles: albedo only, whatever slot 4 holds.
    files, mats = run('plain', {'NIER_REMIX_LIVE_NORMAL': '1'})
    assert len(files) == 1 and next(iter(files.values()))['payload'] in (RGBA4, BC1), list(files)
    assert all(field(m, 'normal') == '-' and field(m, 'roughness') == '-' and field(m, 'metallic') == '-' for m in mats), mats[:2]
    results['plain'] = 'untraced shader: albedo only; the BC5 at slot 4 is not taken as a normal map'

    # 2. NieR-like shader, normals off: metallic and roughness from the mask, as R8, named by the material.
    files, mats = run('pbr', {'MOCK_PBR_PS': '1'})
    named = [m for m in mats if field(m, 'roughness') != '-']
    assert named, f'no material got PBR textures (shader roles not traced?): {mats[:2]}'
    for m in named:
        rough, metal = files[field(m, 'roughness')], files[field(m, 'metallic')]
        assert rough['format'] == 61 and metal['format'] == 61, (rough['format'], metal['format'])   # R8_UNORM
        assert (rough['width'], rough['height']) == (4, 4), rough
        assert rough['payload'][:16] == bytes([38] * 16), ('roughness = max(255 - 230, floor 38)', rough['payload'][:16])
        assert metal['payload'][:16] == bytes([200] * 16), ('metallic = mask R', metal['payload'][:16])
        assert field(m, 'normal') == '-', m
        assert field(m, 'path') not in (field(m, 'roughness'), field(m, 'metallic')), m
    results['pbr'] = 'mask R -> metallic R8 (200), 1 - mask G -> roughness R8 (25 -> floor 38), named by the material'

    # 3. Normals on: the slot-3 map (4x4 RGBA8, converted), never the slot-4 detail map (8x8 BC5).
    files, mats = run('pbr-normal', {'MOCK_PBR_PS': '1', 'NIER_REMIX_LIVE_NORMAL': '1'})
    named = [m for m in mats if field(m, 'normal') != '-']
    assert named, f'no normal map sent for a shader that decodes one: {mats[:2]}'
    for m in named:
        n = files[field(m, 'normal')]
        assert (n['width'], n['height'], n['format']) == (4, 4, 28), ('normal must be the slot-3 4x4 map', n['name'], n['width'], n['format'])
        assert n['payload'][2] == 0 and n['payload'][3] == 255, 'converted texels carry 0/255 in B/A'
    assert not any((f['width'], f['height']) == (8, 8) and f['format'] in (28, 83) for f in files.values()), \
        [(f['name'], f['width'], f['format']) for f in files.values()]
    results['normal'] = 'normal map from slot 3 (octahedral RGBA8 4x4); the slot-4 detail BC5 is never captured'

    # 4. No floor: roughness is exactly 255 - gloss.
    files, mats = run('pbr-nofloor', {'MOCK_PBR_PS': '1', 'NIER_REMIX_LIVE_ROUGHNESS_FLOOR': '0'})
    m = next(m for m in mats if field(m, 'roughness') != '-')
    assert files[field(m, 'roughness')]['payload'][:16] == bytes([25] * 16), files[field(m, 'roughness')]['payload'][:16]
    results['floor'] = 'NIER_REMIX_LIVE_ROUGHNESS_FLOOR=0 gives 255 - 230 = 25 exactly'

    # 5. PBR off: constants only.
    files, mats = run('pbr-disabled', {'MOCK_PBR_PS': '1', 'NIER_REMIX_LIVE_PBR': '0'})
    assert all(field(m, 'roughness') == '-' and field(m, 'metallic') == '-' for m in mats), mats[:2]
    results['disabled'] = 'NIER_REMIX_LIVE_PBR=0: no metallic/roughness textures'
    # 7. Texture repeat from the shader's constants (terrain): uv * cb1[5].xy = (4, 2) is baked into the mesh UVs.
    def last_uv(fake):
        out = {}
        for line in fake.splitlines():
            if line.startswith('CreateMesh '):
                out[line.split('v0=')[1].split()[0]] = tuple(float(x) for x in line.split('uvsum=')[1].split()[0].split(','))
        return out
    run('uv-off', {'MOCK_CAMERA': 'live'})              # the non-skinned live mesh: every vertex at uv (0.25, 0.75)
    run('uv-on', {'MOCK_CAMERA': 'live', 'MOCK_UV_PS': '1'})
    off, on = last_uv(fakes['uv-off']), last_uv(fakes['uv-on'])
    scaled = [(k, off[k], on[k]) for k in off if k in on and abs(off[k][0]) > 1e-3 and abs(off[k][1]) > 1e-3]
    assert scaled, (off, on)
    assert all(abs(b[0] - 4 * a[0]) < 1e-2 * max(1, abs(a[0])) and abs(b[1] - 2 * a[1]) < 1e-2 * max(1, abs(a[1]))
               for _, a, b in scaled), scaled[:3]
    assert any('uv:0:cb1[5].xy=4,2' in n for n in notes['uv-on']), notes['uv-on'][:3]
    assert not any(' uv:' in n for n in notes['uv-off']), notes['uv-off'][:3]
    results['uv'] = f'albedo repeat cb1[5].xy=(4,2) baked into mesh UVs: {scaled[0][1]} -> {scaled[0][2]}'
    # 8. The size filter: a 6-index draw in the scene image is dropped and reported (default 128), kept when lowered.
    run('small-default', {'MOCK_CAMERA': 'live', 'MOCK_SMALL_DRAW': '1'})
    run('small-all', {'MOCK_CAMERA': 'live', 'MOCK_SMALL_DRAW': '1', 'NIER_REMIX_LIVE_MIN_INDICES': '3'})
    six = lambda fake: [l for l in fake.splitlines() if l.startswith('CreateMesh ') and ' indices=6 ' in l]
    assert any('indices=6 ' in s and 'in_scene=1' in s for s in smalls['small-default']), smalls['small-default'][:3]
    assert not six(fakes['small-default']), six(fakes['small-default'])[:2]
    assert six(fakes['small-all']), 'NIER_REMIX_LIVE_MIN_INDICES=3 did not let the 6-index draw through'
    assert not any('indices=6 ' in s for s in smalls['small-all']), smalls['small-all'][:3]
    results['small'] = 'a 6-index scene draw is dropped and reported by default, uploaded with NIER_REMIX_LIVE_MIN_INDICES=3'
    # 6. One diagnostic line per pixel shader: its roles and what happened at each role's slot.
    assert any('roles=-' in n for n in notes['plain']), notes['plain'][:3]
    pbr = [n for n in notes['pbr'] if 'albedo=0.xyz' in n]
    assert pbr and all('metal=2.x' in n and 'gloss=2.y~' in n and ' 2:' in n for n in pbr), notes['pbr'][:3]
    assert all(len(set(notes[k])) == len(notes[k]) for k in notes), 'a shader was noted twice'
    results['notes'] = pbr[0]
    print(json.dumps({'passed': True, 'work': str(work), 'checks': results,
                      'limits': 'Wine mock: proves the slot choice, channel extraction and plumbing, not how it looks live.'},
                     indent=2))


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
