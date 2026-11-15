#!/usr/bin/env python3
"""Turn an F9 capture frame (NIER_CAPTURE/frame_N) into a flat manifest for capture_replay.exe.

  pack_capture.py <frame_dir> <out_dir> [--name scene]   writes <out_dir>/<name>.manifest and <name>.cbs

The capture is read, never written. Vertex/index buffers that the capture hard-linked (one game buffer shared by
many draws) become ONE replay buffer, so the proxy sees the same buffer identity the game gave it. Constant-buffer
bytes are packed into one blob, identical contents once.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def win(path):
    return 'Z:' + str(Path(path).resolve())


def pack(frame, out, name='scene', min_indices=0, dedup_content=False):
    frame, out = Path(frame).resolve(), Path(out)
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
    content = {}

    def buffer_id(path):
        st = path.stat()
        key = (st.st_dev, st.st_ino)
        if dedup_content:
            data = path.read_bytes()
            digest = (len(data), hashlib.sha256(data).digest())
            matches = content.setdefault(digest, [])
            for previous, buffer in matches:
                if previous.read_bytes() == data:  # Resolve even a strong-digest collision by bytes.
                    return buffer
            key = (digest, len(matches))
            matches.append((path, len(buffers)))
        if key not in buffers:
            buffers[key] = len(buffers)
            lines.append(f'buffer {buffers[key]} {st.st_size} {win(path)}')
        return buffers[key]

    def require(path, expected=None):
        size = path.stat().st_size
        if not size or (expected is not None and size != expected):
            raise ValueError(f'missing/truncated capture resource: {path} ({size}, expected {expected})')

    def cb(path):
        data = path.read_bytes()
        if data not in blob_at:
            blob_at[data] = len(blob)
            blob.extend(data)
        return blob_at[data], len(data)

    draws = 0
    scene_size = (0, 0)
    for d in sorted(frame.glob('draw_*')):
        j = json.loads((d / 'capture.json').read_text())
        if j['index_count'] < min_indices or not j.get('layout_found'):
            continue
        if dedup_content:
            for vb in j['vertex_buffers']:
                require(d / f'vb_{vb["slot"]}.bin', vb.get('bytes'))
            if j['has_index']:
                path = d / 'ib.bin'
                index_size = {42: 4, 57: 2}.get(j['ib_format'])
                if index_size is None:
                    raise ValueError(f'unsupported capture index format: {j["ib_format"]}')
                require(path)
                if path.stat().st_size < j['ib_offset'] + (j['start_index'] + j['index_count']) * index_size:
                    raise ValueError(f'truncated capture index buffer: {path}')
            for key, prefix in [('vs_cbs', 'cb_'), ('ps_cbs', 'ps_cb_')]:
                for cb_info in j[key]:
                    require(d / f'{prefix}{cb_info["slot"]}.bin', cb_info.get('bytes'))
            for t in j['ps_textures']:
                require(frame / 'textures' / f'tex_{t["id"]}.dds')
        for t in j['ps_textures']:
            if t['id'] not in textures and (frame / 'textures' / f'tex_{t["id"]}.dds').exists():
                textures[t['id']] = True
                lines.append(f'texture {t["id"]} {win(frame / "textures" / f"tex_{t["id"]}.dds")}')
        ib = buffer_id(d / 'ib.bin') if j['has_index'] and (d / 'ib.bin').exists() else -1
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
            if path.exists():
                lines.append(f'vb {vb["slot"]} {vb["stride"]} {vb["offset"]} {buffer_id(path)}')
        for e in j['layout']:
            lines.append(f'el {e["semantic"]} {e["format"]} {e["offset"]} {e["slot"]}')
        for kind, key, prefix in (('vcb', 'vs_cbs', 'cb_'), ('pcb', 'ps_cbs', 'ps_cb_')):
            for c in j[key]:
                path = d / f'{prefix}{c["slot"]}.bin'
                if path.exists():
                    lines.append(f'{kind} {c["slot"]} %d %d' % cb(path))
        for t in j['ps_textures']:
            if t['id'] in textures:
                lines.append(f'tex {t["slot"]} {t["id"]}')
        lines.append('end')
        draws += 1
    lines.insert(1, f'size {scene_size[0]} {scene_size[1]}')
    (out / (name + '.cbs')).write_bytes(blob)
    (out / (name + '.manifest')).write_text('\n'.join(lines) + '\n')
    return {'draws': draws, 'buffers': len(buffers), 'textures': len(textures), 'cb_bytes': len(blob),
            'scene_size': scene_size}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('frame')
    ap.add_argument('out')
    ap.add_argument('--name', default='scene')
    ap.add_argument('--min-indices', type=int, default=0)
    ap.add_argument('--dedup-content', action='store_true', help='deduplicate copied buffers by SHA-256 and bytes; validate required resources')
    a = ap.parse_args()
    print(json.dumps(pack(a.frame, a.out, a.name, a.min_indices, a.dedup_content)))
    sys.exit(0)
