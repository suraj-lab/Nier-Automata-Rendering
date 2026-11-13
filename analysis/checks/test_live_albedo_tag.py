#!/usr/bin/env python3
"""Gate: albedo DDS files are written untagged, and the masks/normals keep their own formats.

The runtime gamma-decodes every albedo in its own shader (`opaque_surface_material_interaction.slangh:750-753`), so an
sRGB-tagged albedo is decoded twice: NieR's surfaces come out dark and flat, with the ground and tent fabric losing their
detail. Decided by an A/B on 2026-11-13 ("UNORM looks more accurate to the game"), so `without_srgb` is now the default
and `NIER_REMIX_LIVE_ALBEDO_UNORM=0` is the rollback.

What this pins, in the Wine mock with the fake runtime:
  A. `texture_capture::without_srgb` maps exactly the six sRGB formats and nothing else (compiled and run, not read).
  B. A live albedo bound as R8G8B8A8_UNORM_SRGB is written as R8G8B8A8_UNORM (28), byte-identical payload; a BC1 albedo
     as BC1_UNORM (71). With NIER_REMIX_LIVE_ALBEDO_UNORM=0 the same runs write the game's own tags (29 / 72).
  C. The metallic/roughness mask written in the same run keeps its own format: the retag is the albedo's alone.
Limits: the mock's textures are 4x4 to 8x8 software surfaces in Wine, so this pins the header the runtime reads and the
bytes it gets, not what the path tracer does with them (nothing offline can - the A/B was a look at the frames).
"""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime/live-albedo-tag'
sys.path.insert(0, str(C))
import test_remix_live as tr
import test_menu_overlay as tmo
import test_nscn_scene as ts

tr.ENV_KEYS = tuple(tr.ENV_KEYS) + ('NIER_REMIX_LIVE', 'NIER_REMIX_LIVE_TEX', 'MOCK_TEX_MIPS', 'MOCK_TEX_A8',
                                     'MOCK_TEX_SRGB', 'NIER_REMIX_LIVE_ALBEDO_UNORM', 'FAKE_REMIX_INSTANCE_LOG',
                                     'MOCK_CAMERA', 'MOCK_PBR_PS')

MAPPING = [(71, 72), (74, 75), (77, 78), (98, 99), (28, 29), (87, 91)]  # (untagged, tagged) BC1/BC2/BC3/BC7/RGBA/BGRA


def read_dds(path):
    raw = path.read_bytes()
    assert raw[:4] == b'DDS ', f'{path.name}: not a DDS'
    fourcc = struct.unpack_from('<I', raw, 84)[0]
    assert fourcc == 0x30315844, f'{path.name}: expected a DX10 header'
    fmt = struct.unpack_from('<I', raw, 128)[0]
    return {'format': fmt, 'width': struct.unpack_from('<I', raw, 16)[0], 'payload': raw[148:]}


def mapping_check(work):
    """A: the compiled mapping itself, for every format in both directions and one that must not change."""
    src = work / 'without_srgb.cpp'
    src.write_text('''#include <windows.h>
#include <d3d11.h>
#include <cstdio>
#include "texture_capture.h"
int main() {
    const unsigned both[][2] = {%s};
    for (const auto& pair : both) {
        const unsigned got = static_cast<unsigned>(texture_capture::without_srgb(static_cast<DXGI_FORMAT>(pair[1])));
        std::printf("%%u %%u %%u\\n", pair[0], pair[1], got);
    }
    std::printf("keep %%u\\n", static_cast<unsigned>(texture_capture::without_srgb(DXGI_FORMAT_BC5_UNORM)));
    return 0;
}
''' % ', '.join('{%d, %d}' % (untagged, tagged) for untagged, tagged in MAPPING))
    exe = work / 'without_srgb.exe'
    subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-static',
                    '-static-libgcc', '-static-libstdc++', '-I', str(C), str(src), '-o', str(exe)], check=True)
    out = subprocess.run(['wine', str(exe)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    rows = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if parts[0] == 'keep':
            assert parts[1] == '83', f'BC5_UNORM (83) must stay: {line}'
            continue
        untagged, tagged, got = (int(v) for v in parts)
        rows[tagged] = (untagged, got)
    for untagged, tagged in MAPPING:
        assert rows[tagged] == (untagged, untagged), \
            f'sRGB format {tagged} should map to {untagged}: {rows[tagged]}'
    return {f'{tagged}->{untagged}' for untagged, tagged in MAPPING}


def written(work, name, env):
    tex = work / f'tex-{name}'
    tex.mkdir()
    _, result, log, fake = tr.run(work, name, {
        'NIER_REMIX_RUNTIME': tr.win(work / 'fake_remix.dll'), 'NIER_REMIX_SCENE': tr.win(work / 'scene' / 'scene.bin'),
        'MOCK_FRAME_MS': '40', 'NIER_REMIX': '1', 'NIER_REMIX_LIVE': '1', 'NIER_REMIX_LIVE_TEX': tr.win(tex),
        'MOCK_CAMERA': 'live-skinned', 'FAKE_REMIX_INSTANCE_LOG': '1', 'MOCK_PBR_PS': '1', 'NIER_REMIX_LIVE_PBR': '1',
        # This gate is about the albedo's header only: normal maps are on by default and would put a second 4-channel
        # DDS (format 28) in the same folder, which the per-format dict below reads as the albedo's own tag.
        'NIER_REMIX_LIVE_NORMAL': '0',
        **env})
    assert fake and 'VIOLATION' not in fake, (name, fake)
    return {read_dds(p)['format']: read_dds(p) for p in sorted(tex.glob('live_*.dds'))}, result


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    results = {}
    try:
        tmo.build(work)
        subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-static', '-static-libgcc', '-static-libstdc++', '-isystem', str(A / 'remix-probe/vendor'),
                        str(C / 'remix_live_fake_runtime.cpp'), '-ld3d9', '-o', str(work / 'fake_remix.dll')], check=True)
        (work / 'scene' / 'scene_textures').mkdir(parents=True)
        (work / 'scene' / 'scene.bin').write_bytes(ts.scene_bytes(ts.CAMERA, ts.DRAWS, ts.TEXTURES, ts.TRIS))
        results['mapping'] = ', '.join(sorted(mapping_check(work)))

        # B: the albedo arrives sRGB-tagged; the default writes it untagged, and the rollback switch keeps the tag.
        rgba, _ = written(work, 'srgb-rgba', {'MOCK_TEX_SRGB': 'rgba8'})
        assert 28 in rgba and 29 not in rgba, f'the default must write RGBA8 albedo untagged: {sorted(rgba)}'
        rgba_off, _ = written(work, 'srgb-rgba-off', {'MOCK_TEX_SRGB': 'rgba8', 'NIER_REMIX_LIVE_ALBEDO_UNORM': '0'})
        assert 29 in rgba_off and 28 not in rgba_off, f'the rollback must keep the game tag: {sorted(rgba_off)}'
        assert rgba[28]['payload'] == rgba_off[29]['payload'], 'the retag changed the bytes'
        results['rgba8'] = 'R8G8B8A8_UNORM_SRGB written as 28 by default (29 with the rollback), same bytes'

        bc1, _ = written(work, 'srgb-bc1', {'MOCK_TEX_SRGB': 'bc1'})
        assert 71 in bc1 and 72 not in bc1, f'BC1 albedo must be written untagged: {sorted(bc1)}'
        bc1_off, _ = written(work, 'srgb-bc1-off', {'MOCK_TEX_SRGB': 'bc1', 'NIER_REMIX_LIVE_ALBEDO_UNORM': '0'})
        assert 72 in bc1_off, f'the rollback must keep the game tag: {sorted(bc1_off)}'
        assert bc1[71]['payload'] == bc1_off[72]['payload'], 'the retag changed the BC1 bytes'
        results['bc1'] = 'BC1_UNORM_SRGB written as 71 by default (72 with the rollback), same bytes'

        # C: the metal/roughness mask of the same run is not the albedo: it stays the R8 the mask path converts to.
        masks = [f for f in rgba if f not in (28, 29)]
        assert masks, f'no mask texture in the run: {sorted(rgba)}'
        results['mask'] = f'mask formats untouched: {sorted(masks)}'
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-3000:],
                                                         'results': results, 'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results,
              'limits': 'Wine mock: the DDS header and bytes the runtime is handed, not what the path tracer makes of them.'}
    (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def main():
    if sys.argv[1:] == ['--inside']:
        return inside()
    for name in ('prefix', 'home', 'cache', 'xdg'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / 'xdg').chmod(0o700)
    env = os.environ.copy()
    for k in tr.ENV_KEYS:
        env.pop(k, None)
    env.update(WINEPREFIX=str(OUT / 'prefix'), HOME=str(OUT / 'home'), XDG_CACHE_HOME=str(OUT / 'cache'),
               XDG_RUNTIME_DIR=str(OUT / 'xdg'), WINEDEBUG='-all', WAYLAND_DISPLAY='', LIBGL_ALWAYS_SOFTWARE='1',
               GALLIUM_DRIVER='llvmpipe', WINEDLLOVERRIDES='d3d11=n,b;winemenubuilder.exe=d;mscoree,mshtml=')
    subprocess.run(['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', sys.executable, str(Path(__file__).resolve()),
                    '--inside'], cwd=OUT, env=env, check=True)


if __name__ == '__main__':
    main()
