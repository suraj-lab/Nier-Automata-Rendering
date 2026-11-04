#!/usr/bin/env python3
"""Gate: we never hand Remix a DDS its loader divides by zero on.

frametime2-demo2 (2026-11-04) crashed in d3d9_a64ec.dll+0x447e08 with STATUS_INTEGER_DIVIDE_BY_ZERO, 150 ms after we
wrote a 4096x4096 DXGI_FORMAT_A8_UNORM DDS. remix-1.6.1 sizes a DDS's mips as (extent + block - 1) / block, where block
comes from gli's table (rtx_asset_data_manager.cpp:175-182). gli has no DX10 entry for A8_UNORM or any TYPELESS
format, so the block extent is 0.

A. texture_capture::remix_loads (compiled with mingw and run under Wine, as shipped) equals exactly the formats gli
   maps with a non-zero block extent, intersected with the formats we can capture (format_info). GLI_OK is the
   output of gli_dds_probe.cpp, built against the remix-1.6.1 tag's include/gli (dx.inl sha256
   010ebf0c..., format.inl ba53f576...). If that tree is present, the probe is rebuilt and must still agree.
B. Live, Wine mock: an A8 albedo is not written. The refusal is logged once, no DDS with format 65 lands, and the
   mesh is still built (untextured).
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
OUT = A / 'runtime/remix-dds-formats'
GLI = A / 'runtime/src/dxvk-remix/include'
sys.path.insert(0, str(C))
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'MOCK_TEX_A8',
                                    'FAKE_REMIX_INSTANCE_LOG', 'MOCK_CAMERA')

GLI_OK = {2, 3, 4, 6, 7, 8, 10, 11, 12, 13, 14, 16, 17, 18, 20, 24, 25, 26, 28, 29, 30, 31, 32, 34, 35, 36, 37, 38, 40,
          41, 42, 43, 45, 49, 50, 51, 52, 54, 55, 56, 57, 58, 59, 61, 62, 63, 64, 67, 71, 72, 74, 75, 77, 78, 80, 81,
          83, 84, 85, 86, 87, 88, 91, 93, 95, 96, 98, 99, 115}

TABLE = r'''
#include <windows.h>
#include <d3d11.h>
#include <cstdio>
#include "texture_capture.h"
int main() {
    for (unsigned v = 1; v <= 132; ++v) {
        const DXGI_FORMAT f = static_cast<DXGI_FORMAT>(v);
        std::printf("%u %u %d\n", v, texture_capture::format_info(f).bytes, texture_capture::remix_loads(f) ? 1 : 0);
    }
}
'''


def table(work):
    if (GLI / 'gli/gli.hpp').exists():  # the pinned list must still be what gli says
        subprocess.run(['g++', '-std=c++17', '-w', '-I', str(GLI), str(C / 'gli_dds_probe.cpp'),
                        '-o', str(work / 'probe')], check=True)
        probe = subprocess.run([str(work / 'probe')], capture_output=True, text=True, check=True).stdout
        live = {int(v) for v, g, x, y in (l.split() for l in probe.splitlines()) if int(x) > 0 and int(y) > 0}
        assert live == GLI_OK, f'gli changed: +{sorted(live - GLI_OK)} -{sorted(GLI_OK - live)}'
    (work / 'table.cpp').write_text(TABLE)
    subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-static',
                    '-I', str(C), str(work / 'table.cpp'), '-o', str(work / 'table.exe')], check=True)
    out = subprocess.run(['wine', str(work / 'table.exe')], capture_output=True, text=True, check=True).stdout
    rows = [tuple(map(int, l.split())) for l in out.splitlines() if l.strip()]
    capturable = {v for v, b, _ in rows if b}
    allowed = {v for v, _, ok in rows if ok}
    assert allowed == capturable & GLI_OK, \
        f'remix_loads wrong: crashes Remix {sorted(allowed - GLI_OK)}, refused though loadable ' \
        f'{sorted((capturable & GLI_OK) - allowed)}'
    assert 65 in capturable and 65 not in allowed and 70 not in allowed, 'A8 / BC1_TYPELESS must be refused'
    return sorted(allowed)


def main():
    work = Path(tempfile.mkdtemp(prefix='dds-formats-', dir=OUT))
    allowed = table(work)
    tmo.build(work)
    subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                    '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                    str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
    scene = work / 'scene'
    (scene / 'scene_textures').mkdir(parents=True)
    (scene / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
    tex = work / 'live-textures'
    tex.mkdir()
    env = {'MOCK_TEX_A8': '1', 'NIER_REMIX': '1', 'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'),
           'NIER_REMIX_SCENE': tr.win(scene / 'scene.bin'), 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex),
           'FAKE_REMIX_INSTANCE_LOG': '1', 'MOCK_CAMERA': 'live-skinned', 'MOCK_FRAME_MS': '60'}
    _, _, log, fake = tr.run(work, 'a8', env)
    assert fake and 'VIOLATION' not in fake, fake
    lines = tr.remix_lines(log)
    refused = [x for x in lines if 'not loadable by Remix' in x]
    assert len(refused) == 1 and 'format 65 ' in refused[0] and '(8x8)' in refused[0], refused or lines[-10:]
    formats = [struct.unpack_from('<I', p.read_bytes(), 128)[0] for p in tex.glob('live_*.dds')]
    assert 65 not in formats and all(f in allowed for f in formats), formats
    assert any(x.startswith('CreateMesh') for x in fake.splitlines()), 'the mesh must still be built, untextured'
    print(json.dumps({'passed': True, 'work': str(work), 'allowed': allowed, 'written_formats': sorted(set(formats)),
                      'refused': refused[0],
                      'limits': 'Wine mock and fake runtime; the real loader is pinned by source (gli at remix-1.6.1), '
                                'not run.'}, indent=2))


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
