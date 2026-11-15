#!/usr/bin/env python3
"""Frozen A1 gate: equivalent link/copy captures, collision and missing-resource checks."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'replay'))
import pack_capture as candidate


def capture(root, linked):
    root.mkdir()
    meta = {'index_count': 3, 'start_index': 0, 'base_vertex': 0, 'instanced': 0, 'instance_count': 1,
            'start_instance': 0, 'has_index': 1, 'ib_format': 57, 'ib_offset': 0, 'vp_width': 10, 'vp_height': 10,
            'ps_hash': 123, 'layout_found': 1, 'state': dict(zip(['blend_enable', 'src_blend', 'dest_blend',
            'blend_op', 'write_mask', 'depth_enable', 'depth_write', 'depth_func', 'cull_mode', 'fill_mode',
            'dsv_format'], [0, 2, 1, 1, 15, 1, 1, 4, 3, 3, 45])),
            'vertex_buffers': [{'slot': 0, 'stride': 4, 'offset': 0, 'bytes': 12}],
            'layout': [{'semantic': 'POSITION', 'format': 41, 'offset': 0, 'slot': 0}],
            'vs_cbs': [{'slot': 0, 'bytes': 16}], 'ps_cbs': [], 'ps_textures': []}
    for i in range(3):
        draw = root / f'draw_{i:04d}'
        draw.mkdir()
        (draw / 'capture.json').write_text(json.dumps(meta))
        for name, data in [('ib.bin', b'\0\0\1\0\2\0'), ('vb_0.bin', b'A' * 12), ('cb_0.bin', b'C' * 16)]:
            first = root / 'draw_0000' / name
            if i == 1 and linked:
                os.link(first, draw / name)
            else:
                (draw / name).write_bytes(b'B' * 12 if i == 2 and name == 'vb_0.bin' else data)
    return root


def normalized(path):
    lines = path.read_text().splitlines()
    return [' '.join(line.split()[:3]) if line.startswith('buffer ') else line
            for line in lines if not line.startswith(('shaders ', 'cbblob '))]


def check():
    base = HERE.parent / 'runtime/a1-pack-gate'
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        w = Path(tmp)
        linked, copied = capture(w / 'linked', True), capture(w / 'copied', False)
        results = []
        for frame, name in [(linked, 'a'), (copied, 'b')]:
            info = candidate.pack(frame, w / name, dedup_content=True)
            assert info['buffers'] == 3, f'{name}: identical copied buffers not deduplicated or different content merged: {info}'
            results.append(info)
        assert results[0] == results[1]
        assert normalized(w / 'a/scene.manifest') == normalized(w / 'b/scene.manifest')
        assert (w / 'a/scene.cbs').read_bytes() == (w / 'b/scene.cbs').read_bytes() == b'C' * 16
        # Compatibility default keeps inode-based identity, including duplicate copies.
        assert candidate.pack(copied, w / 'old')['buffers'] == 6
        # Hash collisions must be resolved by comparing bytes, not merging unrelated buffers.
        class Collision:
            def digest(self): return b'collision'
            def hexdigest(self): return 'collision'
        with patch.object(candidate.hashlib, 'sha256', lambda *args, **kwargs: Collision()):
            assert candidate.pack(copied, w / 'collision', dedup_content=True)['buffers'] == 3
        for filename in ['vb_0.bin', 'ib.bin', 'cb_0.bin']:
            path = copied / 'draw_0000' / filename
            saved = path.read_bytes()
            for data in [None, saved[:-1]]:
                if data is None:
                    path.unlink()
                else:
                    path.write_bytes(data)
                try:
                    candidate.pack(copied, w / 'bad', dedup_content=True)
                except (ValueError, FileNotFoundError):
                    pass
                else:
                    raise AssertionError(f'missing/truncated {filename} silently accepted')
                path.write_bytes(saved)


if __name__ == '__main__':
    try:
        check()
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
