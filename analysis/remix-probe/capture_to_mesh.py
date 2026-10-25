#!/usr/bin/env python3
"""Convert an F9 capture directory into a C++ header of mesh arrays for the Remix probe.

Usage: capture_to_mesh.py <capture_dir> <out_header>
Exit codes: 0 ok, 2 malformed input, 3 non-unit inferred normal. On failure the output header is not written.
"""
import json
import math
import os
import struct
import sys
from pathlib import Path


def fail(code, msg):
    sys.stderr.write('capture_to_mesh: ' + msg + '\n')
    sys.exit(code)


def fmt(v):
    v = float(v)
    if not math.isfinite(v):
        fail(2, 'non-finite vertex value')
    return '%.9e' % v


def fmt3(t):
    return (fmt(t[0]), fmt(t[1]), fmt(t[2]))


def main():
    if len(sys.argv) != 3:
        fail(2, 'usage: capture_to_mesh.py <capture_dir> <out_header>')
    d = Path(sys.argv[1])
    out = Path(sys.argv[2])

    try:
        meta = json.loads((d / 'capture.json').read_text())
    except Exception as e:
        fail(2, 'bad capture.json: %s' % e)
    try:
        index_count = int(meta['index_count'])
        start_index = int(meta['start_index'])
        base_vertex = int(meta['base_vertex'])
        ib_offset = int(meta['ib_offset'])
        ib_format = meta['ib_format']
        layout = meta['layout']
        vbs = {v['slot']: v for v in meta['vertex_buffers']}
    except Exception as e:
        fail(2, 'bad capture.json keys: %s' % e)

    isize = {57: 2, 42: 4}.get(ib_format)
    if isize is None:
        fail(2, 'unsupported ib_format %r' % (ib_format,))
    if index_count < 0:
        fail(2, 'negative index_count')

    try:
        ib = (d / 'ib.bin').read_bytes()
    except Exception as e:
        fail(2, 'missing ib.bin: %s' % e)
    ids = []
    for k in range(index_count):
        off = ib_offset + (start_index + k) * isize
        if off < 0 or off + isize > len(ib):
            fail(2, 'index %d read out of ib.bin' % k)
        raw = struct.unpack_from('<H' if isize == 2 else '<I', ib, off)[0]
        vid = raw + base_vertex
        if vid < 0:
            fail(2, 'vertex id %d is negative' % vid)
        ids.append(vid)

    try:
        pos = next(e for e in layout if e['semantic'] == 'POSITION')
    except (KeyError, TypeError, StopIteration):
        fail(2, 'no POSITION element in layout')
    pslot = pos.get('slot', 0)
    if pslot not in vbs:
        fail(2, 'position slot %r not in vertex_buffers' % (pslot,))
    try:
        vb0 = (d / ('vb_%d.bin' % pslot)).read_bytes()
    except Exception as e:
        fail(2, 'missing vb_%d.bin: %s' % (pslot, e))
    s0 = vbs[pslot]
    pfmt = pos['format']
    if pfmt not in (6, 2, 10):
        fail(2, 'unsupported POSITION format %r' % (pfmt,))

    s1 = vbs.get(1)
    # Metadata offsets/strides must be non-negative ints: a negative value could alias another vertex.
    for name, value in (('vb offset', s0['offset']), ('vb stride', s0['stride']), ('POSITION offset', pos['offset'])) + (
            (('slot 1 offset', s1['offset']),) if s1 is not None else ()):
        if type(value) is not int or value < 0:
            fail(2, '%s %r is not a non-negative integer' % (name, value))
    # NieR stream 1: uv half2 @0, normal half4 @8 (stride 20 appends a uv copy @16); checked by the unit-normal test.
    inferred = s1 is not None and s1['stride'] in (16, 20) and (d / 'vb_1.bin').exists()
    if inferred:
        try:
            vb1 = (d / 'vb_1.bin').read_bytes()
        except Exception as e:
            fail(2, 'missing vb_1.bin: %s' % e)
    else:
        vb1 = b''

    unique = sorted(set(ids))
    verts = []
    for vid in unique:
        o = s0['offset'] + vid * s0['stride'] + pos['offset']
        if pfmt in (6, 2):
            if o < 0 or o + 12 > len(vb0):
                fail(2, 'position read out of range for vertex %d' % vid)
            p = struct.unpack_from('<3f', vb0, o)
        else:  # 10: R16G16B16A16_FLOAT, use first 3 halfs
            if o < 0 or o + 6 > len(vb0):
                fail(2, 'position read out of range for vertex %d' % vid)
            p = (struct.unpack_from('<e', vb0, o)[0],
                 struct.unpack_from('<e', vb0, o + 2)[0],
                 struct.unpack_from('<e', vb0, o + 4)[0])
        if inferred:
            o1 = s1['offset'] + vid * s1['stride']
            if o1 < 0 or o1 + 16 > len(vb1):
                fail(2, 'inferred attribute read out of range for vertex %d' % vid)
            n = (struct.unpack_from('<e', vb1, o1 + 8)[0],
                 struct.unpack_from('<e', vb1, o1 + 10)[0],
                 struct.unpack_from('<e', vb1, o1 + 12)[0])
            t = (struct.unpack_from('<e', vb1, o1)[0],
                 struct.unpack_from('<e', vb1, o1 + 2)[0])
        else:
            n, t = (0.0, 0.0, -1.0), (0.0, 0.0)
        length = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        if not (0.99 <= length <= 1.01):
            fail(3, 'vertex %d inferred normal length %.6f not in [0.99, 1.01]' % (vid, length))
        verts.append((p, n, t))

    rank = {vid: k for k, vid in enumerate(unique)}
    indices = [rank[v] for v in ids]

    lines = [
        '#pragma once',
        'constexpr unsigned captured_vertex_count = %d;' % len(unique),
        'constexpr unsigned captured_index_count = %d;' % len(indices),
        'constexpr bool captured_has_inferred_attributes = %s;' % ('true' if inferred else 'false'),
        'constexpr float captured_positions[][3] = {%s};' % ','.join('{%s,%s,%s}' % fmt3(p) for p, n, t in verts),
        'constexpr float captured_normals[][3] = {%s};' % ','.join('{%s,%s,%s}' % fmt3(n) for p, n, t in verts),
        'constexpr float captured_texcoords[][2] = {%s};' % ','.join('{%s,%s}' % (fmt(t[0]), fmt(t[1])) for p, n, t in verts),
        'constexpr unsigned captured_indices[] = {%s};' % ','.join(str(i) for i in indices),
    ]
    # Write a sibling temp file and rename, so a failed write never leaves a partial header at `out`.
    tmp = out.with_name(out.name + '.tmp')
    try:
        tmp.write_text('\n'.join(lines) + '\n')
        os.replace(tmp, out)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        fail(2, 'cannot write %s: %s' % (out, e))


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # any other malformed-input surprise (wrong JSON types etc.) is exit 2, not 1
        fail(2, 'malformed capture: %r' % (e,))
