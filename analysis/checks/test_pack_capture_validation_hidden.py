#!/usr/bin/env python3
"""A1 hidden input-boundary cases: refuse malformed scalar metadata and never pack into the raw capture."""
import copy
import json
from pathlib import Path
import sys
import tempfile

C = Path(__file__).resolve().parent
A = C.parent
sys.path.insert(0, str(C))
from test_pack_capture_validation import fixture, digest
import pack_capture as candidate


def check():
    base = A / 'runtime/a1-validation-hidden'
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as temporary:
        w = Path(temporary)
        source = w / 'raw'
        original = fixture(source, False)
        before = digest(source)
        out = w / 'out'
        def refused(label, frame=source, destination=out, name='scene'):
            try:
                candidate.pack(frame, destination, name=name)
            except (ValueError, FileNotFoundError):
                return
            raise AssertionError(label + ' silently accepted')
        refused('missing capture root', frame=w / 'absent')
        ordinary = w / 'ordinary-file'
        ordinary.write_text('not a capture directory')
        refused('file instead of capture root', frame=ordinary)
        refused('output inside raw capture', destination=source / 'derived')
        assert digest(source) == before and not (source / 'derived').exists(), 'packer wrote inside raw capture'
        for name in ['../escape', 'nested/name', 'back\\slash', '', 'line\nbreak', 'with space']:
            refused('unsafe output name', name=name)
        meta = source / 'draw_0000/capture.json'
        cases = [
            ('fractional index count', lambda j: j.update(index_count=3.5)),
            ('fractional start index', lambda j: j.update(start_index=0.5)),
            ('string stride', lambda j: j['vertex_buffers'][0].update(stride='4')),
            ('vertex slot beyond API limit', lambda j: j['vertex_buffers'][0].update(slot=32)),
            ('vertex offset beyond buffer', lambda j: j['vertex_buffers'][0].update(offset=13)),
            ('CB slot beyond API limit', lambda j: j['vs_cbs'][0].update(slot=14)),
            ('fractional texture id', lambda j: j['ps_textures'].append({'slot': 0, 'id': 1.5})),
        ]
        for label, change in cases:
            j = copy.deepcopy(original); change(j); meta.write_text(json.dumps(j))
            refused(label)
        meta.write_text(json.dumps(original))
        # Review b760c1d3: excluded draws do not require payloads that will never be replayed.
        ib = source / 'draw_0000/ib.bin'
        ib_bytes = ib.read_bytes(); ib.unlink()
        info = candidate.pack(source, w / 'excluded-by-count', min_indices=4)
        assert info['draws'] == 0, 'size-filtered draw still requires missing payload'
        j = copy.deepcopy(original); j['layout_found'] = 0
        meta.write_text(json.dumps(j))
        info = candidate.pack(source, w / 'excluded-by-layout')
        assert info['draws'] == 1, 'layout-filtered draw still requires missing payload'
        j['index_count'] = -1
        meta.write_text(json.dumps(j))
        refused('negative selection metadata, even when layout excluded')
        ib.write_bytes(ib_bytes); meta.write_text(json.dumps(original))

        # A stray tex_0 file cannot turn the unbound texture sentinel into a material resource.
        tex = source / 'textures'
        tex.mkdir()
        (tex / 'tex_0.dds').write_bytes(b'fixture only')
        j = copy.deepcopy(original); j['ps_textures'] = [{'slot': 0, 'id': 0}]
        meta.write_text(json.dumps(j))
        candidate.pack(source, out)
        assert not any(line.startswith('texture 0 ') or line == 'tex 0 0' for line in (out / 'scene.manifest').read_text().splitlines()), 'texture id0 sentinel was bound'


if __name__ == '__main__':
    try:
        check()
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)[:1500]}))
        sys.exit(1)
