#!/usr/bin/env python3
"""R2a/R2b frozen gate: a capture that can see PS slots 16-31 and can carry a cube texture, both default off.

R2a (slots): the F9 capture enumerated PS SRVs 0-15 only, so every material texture NieR binds past 15 (the sky's
AO mask t17, the fog LUT t12/t19 in the shader's naming) was invisible to the census and to the DDS files the bake
reads. `NIER_REMIX_LIVE_TEX_SLOTS=<n>` widens the range; the default stays 16, the render-target/UAV/dynamic filter
and the per-frame byte budget are unchanged, and a texture past the budget is still counted, not captured.

R2b (cubes): a cube SRV was read as if it were a 2D texture, so face 0's chain was written under a plain TEXTURE2D
header and the other five faces were dropped silently. `NIER_REMIX_LIVE_TEX_CUBE=1` reads all six faces and writes the
DDS as the DirectXTex loader reads it back (DirectXTexDDS.cpp, DDS_DIMENSION_TEXTURE2D case): `resourceDimension 3`
with `miscFlag` = `DDS_RESOURCE_MISC_TEXTURECUBE` (0x4) and `arraySize` 1 — `arraySize` counts cubes, and 4 is
TEXTURE3D, not a cube. Off, the file is the face-0 one of today bit for bit. Six faces are written only for a
TEXTURECUBE view: a Texture2D view of one face stays one face. A six-face read is charged to the byte budget whole.
The read-back side is pinned too: `terrain_bake::read_dds` takes face 0 of a cube and refuses another dimension, and
the packer refuses a cube DDS that does not carry all six faces while leaving 2D files untouched.

Everything here is the offline mock in Wine/llvmpipe: it pins the bytes the DDS carries, not what the path tracer or a
GPU makes of a cube. The per-frame cost of the wider slot range is NOT measured here (that needs a live run).
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
OUT = A / 'runtime/live-texture-wide'
sys.path.insert(0, str(C))
sys.path.insert(0, str(A / 'replay'))
import test_menu_overlay as tmo
import test_remix_live as tr
from test_pack_capture_validation import fixture, digest
import pack_capture as packer

EXTRA = ('MOCK_TEX_SLOT16', 'MOCK_TEX_CUBE', 'NIER_REMIX_LIVE_TEX_SLOTS', 'NIER_REMIX_LIVE_TEX_CUBE',
         'NIER_REMIX_LIVE_TEX_BUDGET')
# What menu_overlay_mock_game.cpp fills in, byte for byte.
WIDE = bytes((i * 13 + 7) & 0xff for i in range(8 * 8 * 4))
CUBE = {(f, m): bytes((i * 7 + f * 31 + m * 101 + 3) & 0xff for i in range((4 * 4 if m == 0 else 2 * 2) * 4))
        for f in range(6) for m in range(2)}
RGBA = bytes((i * 7 + 3) & 0xff for i in range(4 * 4 * 4))
BC1 = bytes((i * 5 + 1) & 0xff for i in range(2 * 2 * 8))
# The whole 148-byte 2D header the writer produced before this item for a 4x4 RGBA8 single-mip texture, byte for byte
# (test_menu_overlay.py only samples magic/DX10/format/payload, so caps, caps2 and the flags were unpinned).
PLAIN_HEADER = bytes.fromhex(
    '444453207c0000000710080004000000040000004000000000000000010000000000000000'
    '00000000000000000000000000000000000000000000000000000000000000000000000000'
    '00002000000004000000445831300000000000000000000000000000000000000000001000'
    '00000000000000000000000000000000001c00000003000000000000000100000000000000')


def read_dds(path):
    raw = path.read_bytes()
    assert raw[:4] == b'DDS ', f'{path.name}: not a DDS'
    flags, height, width, _pitch, _depth, mips = struct.unpack_from('<6I', raw, 8)
    assert raw[84:88] == b'DX10', f'{path.name}: expected a DX10 header'
    caps, caps2 = struct.unpack_from('<2I', raw, 108)
    fmt, dimension, misc, array_size, misc2 = struct.unpack_from('<5I', raw, 128)
    return {'flags': flags, 'header': raw[:148], 'caps': caps, 'caps2': caps2, 'width': width, 'height': height,
            'mips': mips, 'format': fmt, 'dimension': dimension, 'misc': misc, 'array_size': array_size,
            'misc2': misc2, 'payload': raw[148:]}


def captured(work, name, env):
    """One F9 capture run of the mock game: the two frames it captures during its 80 presents."""
    for k in EXTRA:
        os.environ.pop(k, None)
    os.environ.update(env)
    try:
        d, r, _log = tmo.scenario(work, name, b'[Rendering]\r\nPreset=Native\r\n', True, (0, 0))
    finally:
        for k in EXTRA:
            os.environ.pop(k, None)
    assert r['presented'] == '80' and r['stub_presents'] == '80', (name, r)
    frames = sorted((d / 'NIER_CAPTURE').glob('frame_*'), key=lambda f: int(f.name[6:]))
    assert len(frames) == 2, (name, frames)
    return d, frames


def frame_contents(frame):
    index = json.loads((frame / 'textures' / 'index.json').read_text())
    summary = json.loads((frame / 'frame.json').read_text())
    refs = [json.loads((d / 'capture.json').read_text())['ps_textures'] for d in sorted(frame.glob('draw_*'))]
    textures = {e['id']: read_dds(frame / 'textures' / f'tex_{e["id"]}.dds') for e in index}
    return index, summary, refs, textures


def slots(work, results):
    """R2a: the default range, the widened range, and the budget/filter that must survive it."""
    default_env = {'MOCK_TEX_SLOT16': '1'}
    _d, frames = captured(work, 'wide-default', default_env)
    for frame in frames:
        index, summary, refs, _ = frame_contents(frame)
        assert [e['id'] for e in index] == [1, 2], (frame, index)  # slots 16/17 unseen by the default range
        assert summary['textures'] == 2 and summary['textures_written'] == 2, summary
        for r in refs:
            assert r == [{'slot': 0, 'id': 1}, {'slot': 2, 'id': 2}], r
    results['default'] = 'slots 0-15 only: the static slot-16 texture and the slot-17 target are not captured'

    _d, frames = captured(work, 'wide-32', dict(default_env, **{'NIER_REMIX_LIVE_TEX_SLOTS': '32'}))
    for frame in frames:
        index, summary, refs, textures = frame_contents(frame)
        # slot 16 is a new static texture; 17 is a render target, 20/22 are the light-array buffers: none captured.
        assert [e['id'] for e in index] == [1, 2, 3], (frame, index)
        assert index[2] == {'id': 3, 'format': 28, 'width': 8, 'height': 8}, index[2]
        assert summary['textures'] == 3 and summary['textures_written'] == 3, summary
        for r in refs:
            assert r == [{'slot': 0, 'id': 1}, {'slot': 2, 'id': 2}, {'slot': 16, 'id': 3}], r
        assert textures[3]['payload'] == WIDE, 'the slot-16 texture did not carry its own bytes'
        assert textures[1]['payload'] == RGBA and textures[2]['payload'] == BC1, 'the 0-15 textures changed'
    results['slots32'] = 'PS slot 16 captured with its bytes; the slot-17 target and the 20/22 buffers still filtered'

    # The switch is clamped to 32: a larger number behaves exactly like 32, never like a 128-slot PSGetShaderResources.
    _d, frames = captured(work, 'wide-clamped', {'MOCK_TEX_SLOT16': '1', 'NIER_REMIX_LIVE_TEX_SLOTS': '200'})
    for frame in frames:
        index, _summary, refs, _textures = frame_contents(frame)
        assert [e['id'] for e in index] == [1, 2, 3], (frame, index)
        assert refs == [[{'slot': 0, 'id': 1}, {'slot': 2, 'id': 2}, {'slot': 16, 'id': 3}]] * len(refs), refs
    results['clamped'] = 'NIER_REMIX_LIVE_TEX_SLOTS=200 is clamped to 32 (three textures, no more)'

    _d, frames = captured(work, 'wide-budget', {'MOCK_TEX_SLOT16': '1', 'NIER_REMIX_LIVE_TEX_SLOTS': '32',
                                                'NIER_REMIX_LIVE_TEX_BUDGET': '64'})
    for frame in frames:
        index, summary, refs, textures = frame_contents(frame)
        # 64 bytes is exactly the 4x4 RGBA texture: the BC1 at slot 2 and the 8x8 at slot 16 are past the cap, so
        # they are counted as seen and written as id 0 -- not captured, and the frame does not exceed the budget.
        assert [e['id'] for e in index] == [1], (frame, index)
        assert summary['textures'] == 1 and summary['textures_written'] == 1, summary
        assert summary['texture_bytes'] == 64, summary
        for r in refs:
            assert r == [{'slot': 0, 'id': 1}], r
    results['budget'] = 'the per-frame byte budget still caps a wide-slot frame (64 B: only the first texture)'


def cube(work, results):
    """R2b: face 0 only by default, all six faces behind the switch, and the read-back side.

    The DDS encoding is the one DirectXTex requires (DirectXTexDDS.cpp, the DDS_DIMENSION_TEXTURE2D case): a cube is
    `resourceDimension 3` plus `miscFlag & DDS_RESOURCE_MISC_TEXTURECUBE` (0x4), and `arraySize` counts cubes, not
    faces, so one cube is 1. There is no TEXTURECUBE resource dimension: 4 is TEXTURE3D.
    """
    _d, frames = captured(work, 'cube-default', {'MOCK_TEX_CUBE': '1'})
    for frame in frames:
        index, summary, refs, textures = frame_contents(frame)
        ids = {e['id']: e for e in index}
        assert 3 in ids and ids[3] == {'id': 3, 'format': 28, 'width': 4, 'height': 4}, index
        for r in refs:
            assert r == [{'slot': 0, 'id': 1}, {'slot': 2, 'id': 2}, {'slot': 3, 'id': 3}], r
        assert summary['textures'] == 3, summary
        off = textures[3]
        assert (off['dimension'], off['misc'], off['array_size'], off['misc2']) == (3, 0, 1, 0), off
        assert off['payload'] == CUBE[(0, 0)] + CUBE[(0, 1)], 'default must read face 0 only, as today'
    results['cube_default'] = 'cube off: face 0 as a plain TEXTURE2D, 80 bytes'

    _d, frames = captured(work, 'cube-on', {'MOCK_TEX_CUBE': '1', 'NIER_REMIX_LIVE_TEX_CUBE': '1'})
    on_frames = frames
    for frame in frames:
        index, summary, refs, textures = frame_contents(frame)
        assert summary['textures'] == 3 and summary['textures_written'] == 3, summary
        for r in refs:
            assert r == [{'slot': 0, 'id': 1}, {'slot': 2, 'id': 2}, {'slot': 3, 'id': 3}], r
        on = textures[3]
        assert on['dimension'] == 3 and on['misc'] == 0x4, \
            f"a cube DDS is TEXTURE2D + DDS_RESOURCE_MISC_TEXTURECUBE, got dimension {on['dimension']} misc 0x{on['misc']:x}"
        assert on['array_size'] == 1 and on['misc2'] == 0, 'arraySize counts cubes (DirectXTex multiplies by 6)'
        assert on['caps'] & 0x8, f"a cube DDS is COMPLEX (caps 0x{on['caps']:x})"
        assert on['caps2'] & 0xFE00 == 0xFE00, f"DDSCAPS2 must name all six faces (0x{on['caps2']:x})"
        assert on['mips'] == 2 and on['width'] == 4 and on['height'] == 4, on
        want = b''.join(CUBE[(f, m)] for f in range(6) for m in range(2))  # slice-major, full chain per face
        assert len(on['payload']) == len(want) == 480, (len(on['payload']), len(want))
        assert on['payload'] == want, 'the six faces are missing, reordered or truncated'
        # the 2D textures of the same frame are untouched by the cube switch, header included
        assert textures[1]['header'] == PLAIN_HEADER, 'the 2D DDS header changed'
        assert textures[1]['payload'] == RGBA, 'the RGBA albedo changed'
    results['cube_on'] = 'cube on: TEXTURE2D + cube flag, 6 faces, all 480 bytes slice-major; 2D header byte-identical'

    # A 2D SRV of one face of the cube: the shader sampled one face, so six must not be written even with the switch on.
    _d, frames = captured(work, 'cube-face2d', {'MOCK_TEX_CUBE': 'face2d', 'NIER_REMIX_LIVE_TEX_CUBE': '1'})
    for frame in frames:
        _index, _summary, _refs, textures = frame_contents(frame)
        view = textures[3]
        assert (view['dimension'], view['misc'], view['array_size']) == (3, 0, 1), view
        assert view['payload'] == CUBE[(0, 0)] + CUBE[(0, 1)], 'a 2D view of a cube face became a cube file'
    results['cube_face_view'] = 'a Texture2D view of one cube face stays one face 0 file'

    # The budget covers the whole cube, not its first face: the frame's two 2D textures take 96 bytes of a 400-byte
    # budget, so a cube charged as one 80-byte face would still fit and a whole six-face read (480) does not.
    _d, frames = captured(work, 'cube-budget', {'MOCK_TEX_CUBE': '1', 'NIER_REMIX_LIVE_TEX_CUBE': '1',
                                                'NIER_REMIX_LIVE_TEX_BUDGET': '400'})
    for frame in frames:
        index, summary, refs, textures = frame_contents(frame)
        assert [e['id'] for e in index] == [1, 2], (frame, index)
        assert 3 not in textures, 'a cube that does not fit the budget was captured anyway'
        for r in refs:
            assert r == [{'slot': 0, 'id': 1}, {'slot': 2, 'id': 2}], r
    results['cube_budget'] = 'a six-face read is counted whole against the byte budget (400 B: no cube)'

    # The read-back side: terrain_bake::read_dds takes face 0 of a cube, refuses what it cannot read.
    dds = on_frames[0] / 'textures' / 'tex_3.dds'
    saved = work / 'cube-readback.dds'
    saved.write_bytes(dds.read_bytes())
    harness = work / 'readback.cpp'
    harness.write_text(r'''
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "terrain_bake.h"
#include "texture_capture.h"
static std::vector<unsigned char> load(const char* path) {
    std::vector<unsigned char> b;
    if (FILE* f = std::fopen(path, "rb")) { unsigned char buf[4096]; size_t n; while ((n = std::fread(buf, 1, sizeof buf, f))) b.insert(b.end(), buf, buf + n); std::fclose(f); }
    return b;
}
int main(int, char** argv) {
    auto file = load(argv[1]);
    if (file.size() < 148) return 9;
    terrain_bake::Image im;
    const bool read = terrain_bake::read_dds(file, im);
    if (!read) return 4;                        // refusing the writer's own cube must fail loudly, not read past a vector
    std::printf("cube %d %u %u\n", read ? 1 : 0, im.w, im.h);
    std::printf("face0 %u %u %u %u\n", (unsigned)(im.rgba[0] * 255.f + .5f), (unsigned)(im.rgba[1] * 255.f + .5f),
                (unsigned)(im.rgba[2] * 255.f + .5f), (unsigned)(im.rgba[3] * 255.f + .5f));
    for (unsigned dimension : {1u, 2u, 4u}) {   // TEXTURE1D, TEXTURE1DARRAY, TEXTURE3D: nothing this reader decodes
        auto patched = file;
        std::memcpy(patched.data() + 132, &dimension, 4);
        terrain_bake::Image other;
        std::printf("dim%d %d\n", dimension, terrain_bake::read_dds(patched, other) ? 1 : 0);
    }
    // A cube must never be converted as if its faces were one 2D mip chain: refused, bytes left as the game wrote them.
    texture_capture::Texture cube_t;
    cube_t.format = DXGI_FORMAT_R8G8B8A8_UNORM; cube_t.width = cube_t.height = 4; cube_t.faces = 6;
    cube_t.bytes.assign(6 * 4 * 4 * 4, 128);
    texture_capture::Texture plain = cube_t;
    std::printf("cube_channel %d\n", texture_capture::to_channel(cube_t, 0, false) ? 1 : 0);
    std::printf("cube_octa %d\n", texture_capture::to_octahedral(plain, false) ? 1 : 0);
    std::printf("cube_kept %d\n", cube_t.bytes.size() == 6 * 4 * 4 * 4 && cube_t.format == DXGI_FORMAT_R8G8B8A8_UNORM);
    return 0;
}
''')
    exe = work / 'readback.exe'
    gpp = ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-static',
           '-static-libgcc', '-static-libstdc++', '-I', str(C)]
    subprocess.run([*gpp, str(harness), '-o', str(exe)], check=True)
    out = subprocess.run(['wine', str(exe), tr.win(saved)], capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, (out.returncode, out.stderr[-800:])
    rows = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        rows[parts[0]] = parts[1:]
    assert rows['cube'] == ['1', '4', '4'], rows
    assert tuple(int(v) for v in rows['face0']) == tuple(CUBE[(0, 0)][:4]), (rows['face0'], CUBE[(0, 0)][:4])
    for dim in ('dim1', 'dim2', 'dim4'):
        assert rows[dim] == ['0'], f'{dim} must be refused, not decoded as a 2D tile: {rows[dim]}'
    assert rows['cube_channel'] == ['0'] and rows['cube_octa'] == ['0'], rows
    assert rows['cube_kept'] == ['1'], 'a refused cube must keep the game bytes'
    results['readback'] = 'read_dds: face 0 of the cube decodes to its first texel; TEXTURE1D/3D refused; ' \
                          'a cube is never converted as a 2D chain'

    # The packer: a cube must carry six whole faces; a real 2D file of the same run is untouched.
    plain_dds = sorted(frames[0].glob('textures/tex_1.dds'))[0]
    with tempfile.TemporaryDirectory(dir=OUT) as temporary:
        w = Path(temporary)
        frame = w / 'frame'
        fixture(frame, False)
        (frame / 'textures').mkdir()
        (frame / 'textures' / 'tex_1.dds').write_bytes(saved.read_bytes())
        meta = json.loads((frame / 'draw_0000' / 'capture.json').read_text())
        meta['ps_textures'] = [{'slot': 0, 'id': 1}]
        for d in sorted(frame.glob('draw_*')):
            (d / 'capture.json').write_text(json.dumps(meta))
        raw_digest = digest(frame)
        info = packer.pack(frame, w / 'out')
        assert info['textures'] == 1, info
        assert digest(frame) == raw_digest, 'the packer wrote into the raw capture'
        manifest = (w / 'out' / 'scene.manifest').read_text().splitlines()
        assert any(l.startswith('texture 1 ') for l in manifest), manifest
        results['pack_cube'] = 'packer: the six-face cube is accepted'

        def refused(label, data):
            (frame / 'textures' / 'tex_1.dds').write_bytes(data)
            try:
                packer.pack(frame, w / 'out-refused')
            except ValueError:
                pass
            else:
                raise AssertionError(label + ': silently packed')

        cube_header, cube_payload = saved.read_bytes()[:148], saved.read_bytes()[148:]
        refused('truncated cube', cube_header + cube_payload[:-16])
        refused('header-only cube', cube_header)
        refused('two cubes', cube_header[:140] + struct.pack('<I', 2) + cube_header[144:] + cube_payload * 2)
        (frame / 'textures' / 'tex_1.dds').write_bytes(plain_dds.read_bytes())   # a 2D file from the same run
        legacy_digest = digest(frame)
        assert packer.pack(frame, w / 'out-legacy')['textures'] == 1, 'a plain 2D DDS must still pack'
        assert (frame / 'textures' / 'tex_1.dds').read_bytes() == plain_dds.read_bytes(), 'the packer rewrote the DDS'
        assert digest(frame) == legacy_digest, 'the packer wrote into the raw capture'
        results['pack_refusals'] = 'packer: truncated/header-only/two-cube DDS refused; a real 2D DDS unchanged'


def inside():
    work = Path(tempfile.mkdtemp(prefix='run-', dir=OUT))
    results = {}
    try:
        tmo.build(work)
        slots(work, results)
        cube(work, results)
    except Exception as exc:
        (OUT / 'validation.json').write_text(json.dumps({'passed': False, 'error': str(exc)[-3000:],
                                                         'results': results, 'work': str(work)}, indent=2) + '\n')
        raise
    finally:
        subprocess.run(['wineserver', '-k'], env=os.environ, capture_output=True)
    report = {'passed': True, 'results': results, 'work': str(work),
              'limits': 'Wine/llvmpipe mock: the DDS bytes and the reader/packer decisions, not GPU cube sampling, '
                        'Remix loading a cube replacement, or the cost of a wider PSGetShaderResources call.'}
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
    OUT.mkdir(parents=True, exist_ok=True)
    main()
