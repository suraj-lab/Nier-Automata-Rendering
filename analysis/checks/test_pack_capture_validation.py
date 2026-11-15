#!/usr/bin/env python3
"""A1 frozen gate: explicit refusal of missing/truncated declared resources; valid legacy packing unchanged.
Does not accept the rejected content-dedup spike or change buffer identity. Synthetic linked/copy captures only.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile

C = Path(__file__).resolve().parent
A = C.parent
sys.path.insert(0, str(A / 'replay'))
import pack_capture as candidate


def fixture(root, linked):
    root.mkdir()
    state = dict(zip(('blend_enable', 'src_blend', 'dest_blend', 'blend_op', 'write_mask', 'depth_enable',
                      'depth_write', 'depth_func', 'cull_mode', 'fill_mode', 'dsv_format'),
                     (0, 2, 1, 1, 15, 1, 1, 4, 3, 3, 45)))
    meta = {'index_count': 3, 'start_index': 0, 'base_vertex': 0, 'instanced': 0, 'instance_count': 1,
            'start_instance': 0, 'has_index': 1, 'ib_format': 57, 'ib_offset': 0, 'vp_width': 10, 'vp_height': 10,
            'ps_hash': 123, 'layout_found': 1, 'state': state,
            'vertex_buffers': [{'slot': 0, 'stride': 4, 'offset': 0, 'bytes': 12}],
            'layout': [{'semantic': 'POSITION', 'format': 41, 'offset': 0, 'slot': 0}],
            'vs_cbs': [{'slot': 0, 'bytes': 16}], 'ps_cbs': [{'slot': 1, 'bytes': 16}], 'ps_textures': []}
    for i in range(2):
        d = root / f'draw_{i:04d}'
        d.mkdir()
        (d / 'capture.json').write_text(json.dumps(meta))
        for name, data in [('ib.bin', struct.pack('<3H', 0, 1, 2)), ('vb_0.bin', struct.pack('<3f', 1, 2, 3)),
                           ('cb_0.bin', b'V' * 16), ('ps_cb_1.bin', b'P' * 16)]:
            if linked and i:
                os.link(root / 'draw_0000' / name, d / name)
            else:
                (d / name).write_bytes(data)
    return meta


def digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def check():
    base = A / 'runtime/a1-validation-gate'
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as temporary:
        w = Path(temporary)
        linked = w / 'linked'; copied = w / 'copied'
        fixture(linked, True); original = fixture(copied, False)
        before = digest(copied)
        for root, buffers in [(linked, 2), (copied, 4)]:
            out = w / (root.name + '-out')
            info = candidate.pack(root, out)
            assert info == {'draws': 2, 'buffers': buffers, 'textures': 0, 'cb_bytes': 32, 'scene_size': (10, 10)}, info
            assert (out / 'scene.cbs').read_bytes() == b'V' * 16 + b'P' * 16
            manifest = (out / 'scene.manifest').read_text().splitlines()
            assert manifest[0] == 'replay 1' and sum(l.startswith('draw ') for l in manifest) == 2
        assert digest(copied) == before, 'packer modified raw fixture'
        out = w / 'refused'
        out.mkdir()
        (out / 'scene.manifest').write_bytes(b'existing manifest')
        (out / 'scene.cbs').write_bytes(b'existing constants')
        def refused(label):
            try:
                candidate.pack(copied, out)
            except (ValueError, FileNotFoundError):
                pass
            else:
                raise AssertionError(label + ': malformed resource silently packed')
            assert (out / 'scene.manifest').read_bytes() == b'existing manifest', label + ': replaced old manifest'
            assert (out / 'scene.cbs').read_bytes() == b'existing constants', label + ': replaced old constants'
        d = copied / 'draw_0000'
        for name in ['ib.bin', 'vb_0.bin', 'cb_0.bin', 'ps_cb_1.bin']:
            p = d / name; saved = p.read_bytes()
            p.unlink()
            refused('missing ' + name)
            p.write_bytes(saved[:-1])
            refused('truncated ' + name)
            p.write_bytes(saved)
        meta = d / 'capture.json'
        for key in ['index_count', 'start_index', 'ib_offset']:
            modified = copy.deepcopy(original); modified[key] = -1
            meta.write_text(json.dumps(modified)); refused('negative ' + key)
        for key, value in [('slot', -1), ('stride', 0), ('offset', -1), ('bytes', -1)]:
            modified = copy.deepcopy(original); modified['vertex_buffers'][0][key] = value
            meta.write_text(json.dumps(modified)); refused('invalid vertex ' + key)
        modified = copy.deepcopy(original); modified['vs_cbs'][0]['slot'] = -1
        meta.write_text(json.dumps(modified)); refused('invalid CB slot')
        modified = copy.deepcopy(original); modified['ps_textures'] = [{'slot': 0, 'id': 5}]
        meta.write_text(json.dumps(modified)); refused('missing declared texture')
        # id0 is the existing no-texture sentinel, not a missing required resource.
        modified['ps_textures'][0]['id'] = 0
        meta.write_text(json.dumps(modified)); candidate.pack(copied, w / 'no-texture')
        meta.write_text(json.dumps(original))
        assert digest(copied) == before, 'failed packing altered raw fixture'
        info = candidate.pack(copied, w / 'filtered', min_indices=4)
        assert info['draws'] == info['buffers'] == 0 and info['cb_bytes'] == 0


if __name__ == '__main__':
    try:
        check()
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)[:1500]}))
        sys.exit(1)
