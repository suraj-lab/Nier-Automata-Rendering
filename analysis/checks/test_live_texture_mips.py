#!/usr/bin/env python3
"""Live-texture gate: the DDS we hand Remix carries the game's own mip chain, not mip 0 alone.

Remix logs "suboptimal replacement texture" for a one-level replacement and then has no mip pyramid to
filter with, so world textures shimmer and alias. The game's texture already holds every level on the GPU,
so the fix is to copy them all rather than to invent a filter (NieR's materials are BC1/BC3, and block
formats cannot be resized without a codec).

What this pins: a four-level 8x8 RGBA texture becomes a DDS with MipLevels = 4, the DDSD_MIPMAPCOUNT and
DDSCAPS_MIPMAP flags, correct per-level sizes, and the exact bytes the mock filled in at every level.
Bytes, not a header alone: a writer that declares four levels but copies one fails.
"""
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-texture-mips'
sys.path.insert(0, str(C))
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'MOCK_TEX_MIPS',
                                    'FAKE_REMIX_INSTANCE_LOG', 'MOCK_CAMERA')

MOCK = {  # what menu_overlay_mock_game.cpp fills in when MOCK_TEX_MIPS=1
    m: bytes((i * 11 + 29 * m) & 0xff for i in range(sizes * sizes * 4))
    for m, sizes in enumerate((8, 4, 2, 1))
}


def read_dds(path):
    raw = path.read_bytes()
    assert raw[:4] == b'DDS ', f'{path.name}: not a DDS'
    size, flags, height, width, pitch, depth, mips = struct.unpack_from('<7I', raw, 4)
    fourcc = struct.unpack_from('<I', raw, 84)[0]
    caps2 = struct.unpack_from('<I', raw, 112)[0]
    assert fourcc == 0x30315844, f'{path.name}: expected a DX10 header'
    fmt, dim = struct.unpack_from('<2I', raw, 128)
    payload = raw[148:]
    return {'flags': flags, 'caps2': caps2, 'width': width, 'height': height, 'mips': mips,
            'format': fmt, 'payload': payload}


def main():
    work = Path(tempfile.mkdtemp(prefix='live-texture-mips-'))
    tmo.build(work)
    subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                    '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                    str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
    tex = work / 'live-textures'
    tex.mkdir()
    env = {'MOCK_TEX_MIPS': '1', 'NIER_REMIX': '1', 'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'),
           'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'),
           'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex), 'FAKE_REMIX_INSTANCE_LOG': '1',
           'MOCK_CAMERA': 'live-skinned', 'MOCK_FRAME_MS': '60'}
    _, result, _, fake = tr.run(work, 'mips', env)
    assert fake and 'VIOLATION' not in fake, fake

    # The 8x8 four-level texture is the only one with the mock's mip patterns; identify it by content.
    candidates = []
    for path in sorted(tex.glob('live_*.dds')):
        d = read_dds(path)
        if d['width'] == 8 and d['height'] == 8 and d['format'] == 28:  # DXGI_FORMAT_R8G8B8A8_UNORM
            candidates.append((path, d))
    assert len(candidates) == 1, f'expected one 8x8 RGBA DDS, got {[p.name for p, _ in candidates]}'
    path, dds = candidates[0]

    assert dds['mips'] == 4, f"{path.name}: DDS declares {dds['mips']} levels, the texture has 4"
    assert dds['flags'] & 0x20000, f"{path.name}: DDSD_MIPMAPCOUNT not set (flags 0x{dds['flags']:x})"
    assert dds['caps2'] & 0x400000, f"{path.name}: DDSCAPS2_MIPMAP not set (caps2 0x{dds['caps2']:x})"
    expected_size = sum(len(v) for v in MOCK.values())
    assert len(dds['payload']) == expected_size, \
        f"{path.name}: {len(dds['payload'])} payload bytes, four levels need {expected_size}"

    offset = 0
    for level, want in MOCK.items():
        got = dds['payload'][offset:offset + len(want)]
        assert got == want, f'{path.name}: level {level} is not the game\'s level {level} (first mismatch at ' \
                            f'{next(i for i in range(len(want)) if got[i] != want[i])})'
        offset += len(want)

    # A one-rendered mip 0 only file is the failure this gate exists for; say so if we ever see it.
    assert result.get('texture_reads', 1) >= 1, result
    print(json.dumps({
        'passed': True, 'work': str(work), 'dds': path.name, 'mips': dds['mips'],
        'levels': {level: len(want) for level, want in MOCK.items()},
        'limits': 'Software mock in Wine/llvmpipe: proves the copy/header logic, not BC block formats or real '
                  'NieR texture sets, and not what Remix does with the chain.',
    }, indent=2))


def outside():
    """Wine under Xvfb with llvmpipe, as every live gate does."""
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
