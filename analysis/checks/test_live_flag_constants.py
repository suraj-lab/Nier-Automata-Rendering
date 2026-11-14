#!/usr/bin/env python3
"""Gate for item L3 steps 3-5 (PLAN_2026-11-13): the game's own material switches choose constants over textures.

NieR's lit shaders hold flags in cb1[0]: .y set -> albedo is cb1[4].xyz, .z -> gloss is cb1[5].x, .w -> metal is
cb1[5].y (runtime/pbr-re/lit/ps_1874571568.asm:91-99). Where a flag is set the mask the shader samples is a 32x32
placeholder, and sending it made metal 1 and gloss 1: chrome. Behind NIER_REMIX_LIVE_FLAG_CONSTANTS=1 (default off) the
live path reads the flags per draw and sends metallicConstant / roughnessConstant / albedoConstant instead.

Mock: MOCK_FLAG_PS=x,y,z,w binds that shader shape with cb1[4] = (0.2, 0.4, 0.6) and cb1[5] = (0.3, 0.8).
  - switch off, flags set: today's material (albedo, mask textures), nothing read from the flags;
  - switch on, flags set: no albedo / metal / roughness texture, constants 0.2,0.4,0.6 / 0.8 / 1 - 0.3 = 0.7;
  - switch on, flags clear: the textures, constants at the defaults;
  - switch on, gloss flag only: roughness constant, metal and albedo still textures.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-flag-constants'
sys.path.insert(0, str(C))
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'FAKE_REMIX_INSTANCE_LOG', 'MOCK_CAMERA',
                                    'MOCK_FLAG_PS', 'NIER_REMIX_LIVE_FLAG_CONSTANTS', 'NIER_REMIX_LIVE_STATS_EVERY',
                                    'MOCK_FLAG_TINT')


def field(line, key):
    return line.split(f'{key}=')[1].split()[0]


def main():
    work = Path(tempfile.mkdtemp(prefix='live-flags-'))
    tmo.build(work)
    subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                    '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                    str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))

    def run(name, flags, switch, extra=None):
        tex = work / f'tex-{name}'
        tex.mkdir()
        env = {'MOCK_CAMERA': 'live', 'MOCK_FRAME_MS': '60', 'MOCK_FLAG_PS': flags,
               'NIER_REMIX': '1', 'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'),
               'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'), 'NIER_REMIX_LIVE': '1',
               'NIER_REMIX_LIVE_TEX': tr.win(tex), 'FAKE_REMIX_INSTANCE_LOG': '1', 'NIER_REMIX_LIVE_STATS_EVERY': '10'}
        env['NIER_REMIX_LIVE_FLAG_CONSTANTS'] = '1' if switch else '0'   # on by default since 2026-11-13
        env.update(extra or {})
        _, result, log, fake = tr.run(work, name, env)
        assert fake and 'VIOLATION' not in fake, fake[-1500:]
        # The world mesh's material: the one named with the shader's own roles (the scene shell keeps its own).
        mats = [l for l in fake.splitlines() if l.startswith('CreateMaterial ') and 'hash=1000' not in l
                and 'hash=2000' not in l]
        assert mats, fake[-1500:]
        notes = [l.split('remix: ', 1)[1] for l in log.splitlines() if 'remix: material ps=' in l]
        counted = [l for l in log.splitlines() if 'remix: live flag_constants' in l]
        return mats[-1], notes, counted

    results = {}

    mat, _, counted = run('switch-off', '0,1,1,1', False)
    assert field(mat, 'path') != '-' and field(mat, 'metallic') != '-' and field(mat, 'roughness') != '-', mat
    assert field(mat, 'mconst') == '0.000' and field(mat, 'rconst') == '0.600', mat
    assert not counted, 'the switch is off: nothing may read the flags'
    results['switch-off'] = "default: today's material, mask textures, flags ignored"

    mat, notes, counted = run('flags-set', '0,1,1,1', True)
    assert field(mat, 'path') == '-', f'a constant albedo replaces the texture: {mat}'
    assert field(mat, 'metallic') == '-' and field(mat, 'roughness') == '-', f'constants replace the mask: {mat}'
    assert field(mat, 'aconst') == '0.200,0.400,0.600', mat
    assert field(mat, 'mconst') == '0.800', mat
    assert field(mat, 'rconst') == '0.700', f'roughness is 1 - gloss: {mat}'
    assert counted and int(field(counted[-1], 'draws')) > 0, counted
    results['flags-set'] = 'all three flags: constants 0.2,0.4,0.6 / metal 0.8 / roughness 0.7, no textures'

    mat, _, counted = run('flags-clear', '0,0,0,0', True)
    assert field(mat, 'path') != '-' and field(mat, 'metallic') != '-' and field(mat, 'roughness') != '-', mat
    assert field(mat, 'aconst') == '1.000,1.000,1.000' and field(mat, 'mconst') == '0.000', mat
    assert counted and int(field(counted[-1], 'draws')) == 0, counted
    results['flags-clear'] = 'flags clear: the textures, default constants'

    mat, _, _ = run('gloss-only', '0,0,1,0', True)
    assert field(mat, 'roughness') == '-' and field(mat, 'rconst') == '0.700', mat
    assert field(mat, 'metallic') != '-' and field(mat, 'path') != '-', mat
    results['gloss-only'] = 'one flag: only that role becomes a constant'

    # L8: the game tints the flag's constant albedo by cb8[0] * cb4[0] like the texture (hair shader, ps line 345).
    mat, _, _ = run('tinted', '0,1,1,1', True, {'MOCK_FLAG_TINT': '0.5,1,1'})
    assert field(mat, 'aconst') == '0.100,0.200,0.600', f'constant albedo must carry the tint (0.5,0.5,1): {mat}'
    results['tinted'] = 'flag albedo 0.2,0.4,0.6 x tint 0.5,0.5,1 = 0.1,0.2,0.6'

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
    OUT.mkdir(parents=True, exist_ok=True)
    if '--inside' in sys.argv:
        main()
    else:
        outside()
