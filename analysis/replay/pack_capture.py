#!/usr/bin/env python3
"""Turn an F9 capture frame (NIER_CAPTURE/frame_N) into a flat manifest for capture_replay.exe.

  pack_capture.py <frame_dir> <out_dir> [--name scene]   writes <out_dir>/<name>.manifest and <name>.cbs

The capture is read, never written. Vertex/index buffers that the capture hard-linked (one game buffer shared by
many draws) become ONE replay buffer, so the proxy sees the same buffer identity the game gave it. Constant-buffer
bytes are packed into one blob, identical contents once.
"""
import argparse
import json
import os
import struct
import sys
from pathlib import Path
# Bytes per block (BC) or pixel, and the side of that block, for every DXGI format texture_capture.h gives a size.
FORMATS = {71: (8, 4), 72: (8, 4), 80: (8, 4), 81: (8, 4), 70: (8, 4), 79: (8, 4),          # BC1, BC4 + typeless
           74: (16, 4), 75: (16, 4), 77: (16, 4), 78: (16, 4), 83: (16, 4), 84: (16, 4),
           95: (16, 4), 96: (16, 4), 98: (16, 4), 99: (16, 4), 73: (16, 4), 76: (16, 4), 82: (16, 4), 94: (16, 4),
           97: (16, 4),                                                                # BC2/3/5/6H/7 + typeless
           28: (4, 1), 29: (4, 1), 27: (4, 1), 87: (4, 1), 88: (4, 1), 91: (4, 1), 90: (4, 1), 24: (4, 1),
           26: (4, 1), 34: (4, 1), 35: (4, 1), 41: (4, 1),                             # RGBA/BGRA/R10/...
           10: (8, 1), 11: (8, 1), 16: (8, 1), 49: (2, 1), 54: (2, 1), 56: (2, 1), 61: (1, 1), 65: (1, 1)}
CUBE = 0x4  # DDS_RESOURCE_MISC_TEXTURECUBE, miscFlag. DirectXTex: a cube is TEXTURE2D + this flag, and arraySize
            # counts cubes (it multiplies by 6 for faces), so one cube is arraySize 1. There is no TEXTURECUBE
            # resource dimension: 4 is TEXTURE3D.
def cube_sized(path):
    """R2b: a cube DDS (`texture_capture::write_dds` with faces > 1) must hold all six faces' whole mip chain, or the
    packer would chain a truncated replacement texture to replay. Legacy 2D files are not size-checked: that is the
    layout this packer has always accepted. Only the 148-byte header is read unless the file is a cube."""
    with path.open('rb') as f:
        header = f.read(148)
    if len(header) < 148 or header[:4] != b'DDS ' or header[84:88] != b'DX10':
        return
    fmt, dimension, misc, cubes = struct.unpack_from('<4I', header, 128)
    if dimension != 3 or not misc & CUBE:  # not a cube
        return
    height, width = struct.unpack_from('<I', header, 12)[0], struct.unpack_from('<I', header, 16)[0]
    levels = max(1, struct.unpack_from('<I', header, 28)[0])
    if cubes != 1:
        raise ValueError(f'{path.name}: cube DDS declares {cubes} cubes, this packer carries one')
    block, side = FORMATS.get(fmt, (0, 0))
    if not block:
        raise ValueError(f'{path.name}: cube DDS format {fmt} has no known block size')
    level = sum(((max(1, width >> m) + side - 1) // side) * ((max(1, height >> m) + side - 1) // side) * block
                for m in range(levels))
    size = path.stat().st_size
    if size != 148 + 6 * cubes * level:
        raise ValueError(f'{path.name}: cube DDS is {size} bytes, {6 * cubes} {levels}-level faces need '
                         f'{148 + 6 * cubes * level}')


def win(path):
    return 'Z:' + str(Path(path).resolve())


def pack(frame, out, name='scene', min_indices=0):
    frame, out = Path(frame).resolve(), Path(out)
    if not frame.is_dir():
        raise FileNotFoundError(f'capture directory unavailable: {frame}')
    if not isinstance(name, str) or not name or name in ('.', '..') or Path(name).name != name or any(c in '\\:' or c.isspace() or ord(c) < 32 for c in name):
        raise ValueError('unsafe packed scene name')
    if out.resolve().is_relative_to(frame):
        raise ValueError('packed output must be outside the immutable raw capture')
    def integer(value, label, minimum=0, maximum=0xffffffff):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f'invalid {label}')
    draws = []
    checked = set()   # texture ids whose DDS structure was already verified (R2b: once per file, not once per draw)
    for d in sorted(frame.glob('draw_*')):
        j = json.loads((d / 'capture.json').read_text())
        integer(j['index_count'], 'index_count')
        if j['index_count'] < min_indices or not j.get('layout_found'):
            continue
        for key in ('start_index', 'ib_offset'):
            integer(j[key], key)
        integer(j['base_vertex'], 'base_vertex', -0x80000000, 0x7fffffff)
        if j['has_index']:
            if j['ib_format'] not in (57, 42):
                raise ValueError(f'{d}: invalid index format')
            ib_path = d / 'ib.bin'
            if not ib_path.is_file():
                raise FileNotFoundError(ib_path)
            width = 2 if j['ib_format'] == 57 else 4
            if j['ib_offset'] + (j['start_index'] + j['index_count']) * width > ib_path.stat().st_size:
                raise ValueError(f'{d}: index range exceeds IB')
        for vb in j['vertex_buffers']:
            integer(vb['slot'], 'vertex slot', maximum=31)
            integer(vb['stride'], 'vertex stride', minimum=1)
            integer(vb['offset'], 'vertex offset')
            integer(vb['bytes'], 'vertex bytes', minimum=1)
            if vb['offset'] > vb['bytes']:
                raise ValueError(f'{d}: vertex offset exceeds buffer')
            path = d / f'vb_{vb["slot"]}.bin'
            if not path.is_file():
                raise FileNotFoundError(path)
            if path.stat().st_size != vb['bytes']:
                raise ValueError(f'{d}: vertex buffer length mismatch')
        for key, prefix in (('vs_cbs', 'cb_'), ('ps_cbs', 'ps_cb_')):
            for c in j[key]:
                integer(c['slot'], 'constant buffer slot', maximum=13)
                integer(c['bytes'], 'constant buffer bytes', minimum=1)
                path = d / f'{prefix}{c["slot"]}.bin'
                if not path.is_file():
                    raise FileNotFoundError(path)
                if path.stat().st_size != c['bytes']:
                    raise ValueError(f'{d}: constant buffer length mismatch')
        for t in j['ps_textures']:
            integer(t['id'], 'texture id')
            integer(t['slot'], 'texture slot', maximum=127)
            path = frame / 'textures' / f'tex_{t["id"]}.dds'
            if t['id'] > 0 and not path.is_file():
                raise FileNotFoundError(path)
            if t['id'] > 0 and t['id'] not in checked:
                cube_sized(path)
                checked.add(t['id'])
        draws.append((d, j))
    out.mkdir(parents=True, exist_ok=True)
    shaders = frame.parent / 'shaders'
    lines = ['replay 1', f'shaders {win(shaders)}', f'cbblob {win(out / (name + ".cbs"))}']
    lights = json.loads((frame / 'lights.json').read_text()) if (frame / 'lights.json').exists() else {}
    for key, slot in (('t20', 20), ('t22', 22)):
        info = lights.get(key) or {}
        path = frame / f'lights_{key}.bin'
        if info.get('present') and info.get('stride') and path.exists() and path.stat().st_size:
            lines.append(f'lights {slot} {info["stride"]} {path.stat().st_size // info["stride"]} {win(path)}')
    buffers, textures, blob, blob_at = {}, {}, bytearray(), {}

    def buffer_id(path):
        st = path.stat()
        key = (st.st_dev, st.st_ino)
        if key not in buffers:
            buffers[key] = len(buffers)
            lines.append(f'buffer {buffers[key]} {st.st_size} {win(path)}')
        return buffers[key]

    def cb(path):
        data = path.read_bytes()
        if data not in blob_at:
            blob_at[data] = len(blob)
            blob.extend(data)
        return blob_at[data], len(data)

    draw_count = 0
    scene_size = (0, 0)
    for d, j in draws:
        for t in j['ps_textures']:
            if t['id'] > 0 and t['id'] not in textures and (frame / 'textures' / f'tex_{t["id"]}.dds').exists():
                textures[t['id']] = True
                lines.append(f'texture {t["id"]} {win(frame / "textures" / f"tex_{t["id"]}.dds")}')
        ib = buffer_id(d / 'ib.bin') if j['has_index'] else -1
        s = j['state']
        if s['dsv_format'] == 45 and j['vp_width'] * j['vp_height'] > scene_size[0] * scene_size[1]:
            scene_size = (j['vp_width'], j['vp_height'])
        lines.append('draw ' + ' '.join(str(v) for v in (
            j['index_count'], j['start_index'], j['base_vertex'], j['instanced'], j['instance_count'],
            j['start_instance'], j['has_index'], j['ib_format'], j['ib_offset'], ib, j['vp_width'], j['vp_height'],
            j['ps_hash'])))
        lines.append('state ' + ' '.join(str(s[k]) for k in (
            'blend_enable', 'src_blend', 'dest_blend', 'blend_op', 'write_mask', 'depth_enable', 'depth_write',
            'depth_func', 'cull_mode', 'fill_mode', 'dsv_format')))
        for vb in j['vertex_buffers']:
            path = d / f'vb_{vb["slot"]}.bin'
            lines.append(f'vb {vb["slot"]} {vb["stride"]} {vb["offset"]} {buffer_id(path)}')
        for e in j['layout']:
            lines.append(f'el {e["semantic"]} {e["format"]} {e["offset"]} {e["slot"]}')
        for kind, key, prefix in (('vcb', 'vs_cbs', 'cb_'), ('pcb', 'ps_cbs', 'ps_cb_')):
            for c in j[key]:
                path = d / f'{prefix}{c["slot"]}.bin'
                lines.append(f'{kind} {c["slot"]} %d %d' % cb(path))
        for t in j['ps_textures']:
            if t['id'] in textures:
                lines.append(f'tex {t["slot"]} {t["id"]}')
        lines.append('end')
        draw_count += 1
    lines.insert(1, f'size {scene_size[0]} {scene_size[1]}')
    (out / (name + '.cbs')).write_bytes(blob)
    (out / (name + '.manifest')).write_text('\n'.join(lines) + '\n')
    return {'draws': draw_count, 'buffers': len(buffers), 'textures': len(textures), 'cb_bytes': len(blob),
            'scene_size': scene_size}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('frame')
    ap.add_argument('out')
    ap.add_argument('--name', default='scene')
    ap.add_argument('--min-indices', type=int, default=0)
    a = ap.parse_args()
    print(json.dumps(pack(a.frame, a.out, a.name, a.min_indices)))
    sys.exit(0)
