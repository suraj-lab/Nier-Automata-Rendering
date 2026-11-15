#!/usr/bin/env python3
"""W5 step 1 evidence: which captured shaders declare the hair family's anisotropy members, in which constant buffer at
which offset, what state and lobe value their draws carry, and what their albedo's alpha coverage looks like. Read-only;
writes nothing. The gate (checks/test_live_hair.py) re-reads the declaration, offset, state and lobe facts itself; the
alpha coverage below is the one measurement it does not recompute, so this script is the command that produces it.
"""
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(A / 'checks'))
import dump_shader_decls as P

ROOTS = {
    'camp': Path('/mnt/second/SteamLibrary/steamapps/common/NieRAutomata/NIER_CAPTURE'),
    'desert': A / 'runtime/laptop-play-20261114',
    'pond': A / 'runtime/laptop-play-20261114',
}
FRAMES = {'camp': ['frame_30632051'], 'desert': ['frame_67279062'], 'pond': ['frame_67078468']}
OFFSETS = {'g_AnisoParam1': 96, 'g_AnisoParam2': 112}


def decls(path):
    return P.declarations(P.chunks(path.read_bytes())['RDEF'][0])


def dds_alpha(path):
    """(width, height, fraction of texels whose encoded alpha is zero) for one captured albedo.

    BC1 encodes transparency as block index 3 in a three-colour block; BC2 (DXGI 75/76) carries 4-bit explicit alpha in
    the first 8 bytes of every 16-byte block. Those are the two formats the captures' t0 slots use.
    """
    data = Path(path).read_bytes()
    assert data[:4] == b'DDS ', path
    h = struct.unpack_from('<31I', data, 4)
    height, width = h[2], h[3]
    fmt = struct.unpack_from('<I', data, 128)[0]
    assert data[84:88] == b'DX10', f'{path}: not a DX10-header DDS'
    bw, bh = (width + 3) // 4, (height + 3) // 4
    body = data[148:]
    clear = 0
    for block in range(bw * bh):
        if fmt in (75, 76):                      # BC2_UNORM(_SRGB)
            nibbles = struct.unpack_from('<8B', body, block * 16)
            for byte in nibbles:
                clear += (byte & 0xF == 0) + (byte >> 4 == 0)
        elif fmt in (72, 73):                    # BC1_UNORM(_SRGB)
            c0, c1, bits = struct.unpack_from('<HHI', body, block * 8)
            if c0 > c1:
                continue                         # three-colour block: every index is opaque
            clear += sum(1 for k in range(16) if (bits >> (2 * k)) & 3 == 3)
        else:
            raise AssertionError(f'{path}: unexpected DXGI format {fmt}')
    return width, height, clear / float(width * height)


def main():
    for area, root in ROOTS.items():
        shader_dir = root / 'shaders'
        if not shader_dir.is_dir():
            print('==', area, 'unavailable', root)
            continue
        blobs = sorted(shader_dir.glob('ps_*.dxbc'))
        declarers = {}
        for blob in blobs:
            try:
                cbs, _res = decls(blob)
            except Exception as e:   # noqa: BLE001 - a capture with a broken blob is reported, not skipped
                print('PARSE-FAIL', blob.name, e)
                continue
            hits = [(cname, csize, vname, off, vsize) for cname, csize, vs in cbs
                    for vname, off, vsize in vs if 'aniso' in vname.lower()]
            if hits:
                declarers[blob.stem] = hits
        print('==', area, 'blobs', len(blobs), 'declarers', len(declarers))
        for frame in FRAMES[area]:
            draws = defaultdict(list)
            for p in sorted((root / frame).glob('draw_*')):
                j = json.loads((p / 'capture.json').read_text())
                draws['ps_%d' % j['ps_hash']].append((p, j))
            for k, v in sorted(draws.items(), key=lambda kv: -max(int(j['index_count']) for _, j in kv[1])):
                if k not in declarers:
                    continue
                s = v[0][1]['state']
                cbs, _res = decls(shader_dir / (k + '.dxbc'))
                names = {n for (_c, _s, vs) in cbs for (n, _o, _z) in vs}
                lobe = [struct.unpack_from('<f', (d / 'ps_cb_1.bin').read_bytes(), OFFSETS['g_AnisoParam2'])[0]
                        for d, _j in v if (d / 'ps_cb_1.bin').exists()]
                print('  %s n=%-3d maxidx=%-6d blend=%s dw=%s two_lobe=%s lobe=%s' % (
                    k, len(v), max(int(j['index_count']) for _, j in v),
                    [s.get('blend_enable'), s.get('src_blend'), s.get('dest_blend')], s.get('depth_write'),
                    'g_SecondarySpecParam' in names, sorted(set(lobe))))
                tex = v[0][1].get('ps_textures') or []
                t0 = next((t['id'] for t in tex if t['slot'] == 0), None)
                albedo = shader_dir.parent / frame / 'textures' / ('tex_%d.dds' % t0) if t0 else None
                if albedo is not None and albedo.exists():
                    w, h, clear = dds_alpha(albedo)
                    print('      t0 = tex_%d.dds %dx%d: %.3f of texels fully transparent' % (t0, w, h, clear))
                else:
                    print('      t0 = %s: no DDS in this capture (alpha coverage not measurable here)' % t0)


if __name__ == '__main__':
    main()
