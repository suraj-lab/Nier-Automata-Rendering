#!/usr/bin/env python3
"""Frozen W1.3 gate, part 2: the sky draw's per-layer inputs reach the material it is submitted with.

W1.3 step 1 (PLAN_2026-11-14) folds three inputs the game's sky shader multiplies into its base colour -- the layer's
`g_IntensityParam.y`, the `g_AlbedoParam` override when `.w > 0`, and `g_MeshColor` -- into the material of a
sky-classified draw, behind `NIER_REMIX_LIVE_SKY_LAYERS` (default off). checks/sky_layer.h finds those three by their
RDEF names and the draw's own bindings; this gate pins what the path then submits, in the fake runtime's own log of
`CreateMaterial` (`path=`, `aconst=`).

What is asserted, and why each case exists:
  - default (unset) and `=0` submit byte-identical materials: with the switch off nothing about this path changes, and
    the sky draw keeps today's material (the layer texture, `aconst` 1,1,1);
  - on, `g_AlbedoParam.w = 1`: the sky material becomes a constant colour = albedo * intensity * mesh with no albedo
    texture (Remix's albedoConstant replaces a texture, it does not multiply one), while the *world* draw of the same
    mock frame -- same shader, same texture -- keeps today's material, so the fold is bound to sky classification;
  - on, `g_AlbedoParam.w = 0`: the base colour is t0 * factor, which `albedoConstant` cannot express (it replaces a
    texture). With a factor of 1 nothing changes; with any other factor the material names `sky_<id>_<factor>.dds`, a copy
    of the layer holding the product (W1.3 step 1b). Never a silent flat sky and never a dropped texture;
  - on, a shader that does not declare the members: nothing folded, counted as unresolved (never a zero-filled guess);
  - on, `g_IntensityParam.y = 0` and mesh 1: the constant colour is 0 -> exactly the shader's own base colour.
"""
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-sky-layers'
sys.path.insert(0, str(C))
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'FAKE_REMIX_INSTANCE_LOG', 'MOCK_CAMERA',
                                    'MOCK_SKY_PS', 'NIER_REMIX_LIVE_SKY_LAYERS', 'NIER_REMIX_LIVE_STATS_EVERY',
                                    'NIER_REMIX_LIVE_GREY_FIRST', 'MOCK_SKY_PS_ANIM', 'MOCK_SKY_PS_ANIM_BASE')


def field(line, key):
    return line.split(f'{key}=')[1].split()[0]


# Today's material constants: 1,1,1 for a textured surface, 0.5,0.5,0.5 for the grey one a file has not landed under
# (live_scene's grey_first). Anything else is a colour this path folded in.
TODAY = ('1.000,1.000,1.000', '0.500,0.500,0.500')


def folded(materials):
    return [l for l in materials if field(l, 'aconst') not in TODAY]


def dds_decoded(path):
    """Mean of what the runtime gets out of an albedo mip 0: one pow(x, 2.2) over the stored bytes, RGB only.

    The live path writes every albedo untagged (remix_runtime's albedo_unorm), and Remix's shader decodes albedo itself
    (replay/research-2026-11-12/remix_material_api.md), so the stored bytes are sRGB-encoded art and this is the colour
    the shader actually uses. A copy that multiplies that colour by f must have bytes scaled by f^(1/2.2)."""
    raw = path.read_bytes()
    height, width = struct.unpack_from('<2I', raw, 12)
    fmt = struct.unpack_from('<I', raw, 128)[0]
    assert fmt == 28, f'{path.name}: unexpected format {fmt}'   # untagged: the one decode the runtime then does is right
    texels = raw[148:148 + width * height * 4]
    assert len(texels) == width * height * 4, f'{path.name}: short payload'
    return sum((texels[i] / 255.0) ** 2.2 for i in range(len(texels)) if i % 4 != 3) / (width * height * 3)


def without_ids(materials):
    """The fake runtime prints each material's runtime id, which is its own allocator's: compare the rest."""
    return [l.split(' id=')[0] + ' ' + l.split(' id=')[1].split(' ', 1)[1] for l in materials]


def main():
    work = Path(tempfile.mkdtemp(prefix='live-sky-layer-'))
    tmo.build(work)
    subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                    '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                    str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))

    def run(name, sky_ps, switch, extra=None):
        tex = work / f'tex-{name}'
        tex.mkdir()
        env = {'MOCK_CAMERA': 'live', 'MOCK_FRAME_MS': '60', 'NIER_REMIX': '1',
               'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'),
               'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'), 'NIER_REMIX_LIVE': '1',
               'NIER_REMIX_LIVE_TEX': tr.win(tex), 'FAKE_REMIX_INSTANCE_LOG': '1',
               # grey_first off: a material then appears once, with its texture, instead of twice while the file lands,
               # so two runs of this gate submit the same material list (the parity check below needs that).
               'NIER_REMIX_LIVE_GREY_FIRST': '0', 'NIER_REMIX_LIVE_STATS_EVERY': '10'}
        if sky_ps:
            env['MOCK_SKY_PS'] = sky_ps
        if switch is not None:
            env['NIER_REMIX_LIVE_SKY_LAYERS'] = switch
        env.update(extra or {})
        _, result, log, fake = tr.run(work, name, env)
        assert fake and 'VIOLATION' not in fake, fake[-1500:]
        materials = [l for l in fake.splitlines() if l.startswith('CreateMaterial ')]
        counted = [l for l in log.splitlines() if 'remix: live sky_layers' in l]
        return materials, counted, log, fake

    results = {}
    sky_ps = '5,1,0.713,0.55,1,1,1,1'   # intensity 5, albedo (1,0.713,0.55) with w = 1 (the constant wins), mesh 1
    # 1. Default: nothing about the sky path changes, and the switch is not even read.
    default_materials, counted, _, _ = run('default', sky_ps, None)
    assert not counted, f'the switch is off by default: nothing may be counted (\n{chr(10).join(counted)})'
    sky_default = [l for l in default_materials if field(l, 'path') != '-' and field(l, 'aconst') == '1.000,1.000,1.000']
    assert sky_default, f'today\'s sky material is the layer texture with no constant colour:\n' + \
                        '\n'.join(default_materials[-6:])
    assert not folded(default_materials), 'with the switch off no material may carry a folded colour:\n' + \
        '\n'.join(folded(default_materials))
    results['default'] = 'switch off: the layer texture, aconst 1,1,1, nothing counted'
    # 2. An explicit 0 is the same program as unset: byte parity of every material the run submits.
    zero_materials, counted, _, _ = run('zero', sky_ps, '0')
    assert not counted, 'explicit 0 must not be read as "on"'
    assert without_ids(zero_materials) == without_ids(default_materials), (
        'NIER_REMIX_LIVE_SKY_LAYERS=0 must submit exactly what it submits unset:\n' +
        '\n'.join(sorted(set(without_ids(zero_materials)) ^ set(without_ids(default_materials)))))
    results['zero-parity'] = 'unset and =0 submit the same materials, byte for byte'
    # 3. On, g_AlbedoParam.w = 1: the sky layer becomes the shader's own constant colour, the world draw does not.
    on_materials, counted, _, _ = run('on-albedo', sky_ps, '1')
    assert counted, 'the switch is on: the folded draws must be counted'
    assert int(field(counted[-1], 'folded')) >= 1, counted[-1]
    assert int(field(counted[-1], 'unresolved')) == 0, counted[-1]
    sky = folded(on_materials)
    assert len(sky) == 1, f'exactly one folded material (the sky draw):\n' + '\n'.join(on_materials)
    # 1 * 5, 0.713 * 5, 0.55 * 5
    assert field(sky[0], 'aconst') == '5.000,3.565,2.750', sky[0]
    assert field(sky[0], 'path') == '-', f'the constant replaces the albedo texture: {sky[0]}'
    world = [l for l in on_materials if field(l, 'aconst') == '1.000,1.000,1.000']
    assert world, 'the world draw of the same frame keeps today\'s material:\n' + '\n'.join(on_materials)
    results['on-albedo'] = 'w=1: sky material = albedo*intensity*mesh (5, 3.565, 2.75), no albedo texture; world unchanged'
    # 4. On, g_AlbedoParam.w = 0 with an intensity of 1: there is nothing to scale, so the layer keeps today's material
    #    byte for byte (the case that must stay untouched when a later item turns the switch on by default).
    unity_off, _, _, _ = run('unity-off', '1,0.5,0.5,0.5,0,1,1,1', None)
    unity_on, counted, _, _ = run('unity-on', '1,0.5,0.5,0.5,0,1,1,1', '1')
    assert counted and int(field(counted[-1], 'scaled')) == 0, counted[-1]
    assert int(field(counted[-1], 'textured')) >= 1, counted[-1]
    assert not folded(unity_on), 'a textured sky layer must keep its texture, not become a flat constant:\n' + \
        '\n'.join(unity_on)
    assert without_ids(unity_on) == without_ids(unity_off), \
        'with nothing to scale, a textured sky layer submits today\'s material'
    results['on-unity'] = 'w=0, intensity 1: today\'s material, counted as textured, no copy'
    # 5. On, g_AlbedoParam.w = 0 with intensity 0.5: the layer is t0 * 0.5, which albedoConstant cannot express (it
    #    replaces a texture), so the material names a scaled copy whose mip 0 is the layer's mip 0 times the factor.
    scaled_materials, counted, _, _ = run('on-scaled', '0.5,0.5,0.5,0.5,0,1,1,1', '1')
    assert counted and int(field(counted[-1], 'folded')) == 0, counted[-1]
    assert int(field(counted[-1], 'scaled')) >= 1, counted[-1]
    assert int(field(counted[-1], 'textured')) == 0, counted[-1]
    assert int(field(counted[-1], 'copies')) == 1, counted[-1]
    assert int(field(counted[-1], 'copy_refused')) == 0, counted[-1]
    copies = sorted((work / 'tex-on-scaled').glob('sky_*.dds'))
    assert len(copies) == 1, [p.name for p in copies]
    sky = [l for l in scaled_materials if field(l, 'path').startswith('sky_')]
    assert len(sky) == 1, 'exactly one material names the copy:\n' + '\n'.join(scaled_materials)
    assert field(sky[0], 'path') == copies[0].name, (sky[0], copies[0].name)
    assert field(sky[0], 'aconst') == '1.000,1.000,1.000', sky[0]
    tex_id = copies[0].name.split('_')[1]
    assert copies[0].name == f'sky_{tex_id}_500.dds', copies[0].name
    layer = work / 'tex-on-scaled' / f'live_{tex_id}.dds'
    assert layer.exists(), f'the layer texture the copy was made from is {layer}'
    got, want = dds_decoded(copies[0]), dds_decoded(layer) * 0.5
    assert abs(got - want) < 5 / 255, f'the copy decodes to the layer\'s colour times 0.5: {got:.4f} vs {want:.4f}'
    world = [l for l in scaled_materials if field(l, 'path').startswith('live_')]
    assert world, 'the world draw of the same frame keeps its own texture:\n' + '\n'.join(scaled_materials)
    results['on-scaled'] = (f'w=0, intensity 0.5: material names {copies[0].name}, decoded mean {got:.4f} = '
                            f'{dds_decoded(layer):.4f} * 0.5; world draw unchanged')
    # 5. On, a shader that declares none of the members (the plain mock PS): unresolved, nothing folded.
    plain, counted, _, _ = run('on-plain', None, '1')
    assert counted and int(field(counted[-1], 'unresolved')) >= 1, counted[-1]
    assert int(field(counted[-1], 'folded')) == 0, counted[-1]
    assert not folded(plain), 'nothing may fold without the members'
    results['on-unresolved'] = 'no members in the shader: unresolved, nothing folded'
    # 6. The folded constants are part of the surface: a changed layer value rebuilds the sky mesh, and with the switch
    #    off the same animation changes nothing (the value never reached the material in the first place).
    def rebuilds(log):
        lines = [l for l in log.splitlines() if 'remix: live rebuilds' in l]
        assert lines, 'the stats line with the rebuild counts is missing'
        tail = lines[-1].split('rebuilds', 1)[1]
        keys = ('first', 'unknown', 'buffer', 'pose', 'texture', 'evicted')
        return sum(int(re.search(rf'{k}=(\d+)', tail).group(1)) for k in keys)
    anim = {'MOCK_SKY_PS_ANIM': '1'}
    anim_on, counted_on, log_on, _ = run('anim-on', sky_ps, '1', anim)
    anim_off, _, log_off, _ = run('anim-off', sky_ps, '0', anim)
    assert rebuilds(log_on) > rebuilds(log_off), (
        f'a changed layer value must rebuild the sky mesh with the fold on ({rebuilds(log_on)}) and not with it off '
        f'({rebuilds(log_off)})')
    # A rebuild is not enough: the new colour has to reach a *new material*. The mock cycles the intensity through 1, 2
    # and 3, so three constant colours must be submitted -- a stale mesh would keep the first one and pass the count above.
    expected = ('1.000,0.713,0.550', '2.000,1.426,1.100', '3.000,2.139,1.650')
    folded_on = {field(l, 'aconst') for l in folded(anim_on)}
    assert set(expected) <= folded_on, f'the animated layer must submit all three colours, got {sorted(folded_on)}'
    assert not folded(anim_off), 'with the fold off the animated value may not reach any material'
    results['anim'] = (f'a changed intensity rebuilds the sky mesh and resubmits all three colours only with the fold on '
                       f'({rebuilds(log_on)} vs {rebuilds(log_off)} rebuilds)')
    # 7. On, w = 0 with the intensity animated: the factors 1, 2 and 3 of the cycle must reach their own copies -- a
    #    material stuck at its first one would name no sky_ file at all.
    anim_scaled, counted, _, _ = run('anim-scaled', '2,0.5,0.5,0.5,0,1,1,1', '1',
                                     {'MOCK_SKY_PS_ANIM': '1', 'MOCK_SKY_PS_ANIM_BASE': '2'})
    names = {field(l, 'path') for l in anim_scaled if field(l, 'path').startswith('sky_')}
    assert names == {'sky_1_2000.dds', 'sky_1_3000.dds', 'sky_1_4000.dds'}, (names, counted[-1])
    assert int(field(counted[-1], 'copies')) == 3 and int(field(counted[-1], 'copy_refused')) == 0, counted[-1]
    results['anim-scaled'] = f'an animated textured layer submits one copy per factor: {sorted(names)}'
    print('\n'.join(f'PASS {k}: {v}' for k, v in results.items()))


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
    if '--inside' in sys.argv:
        main()
    else:
        outside()
