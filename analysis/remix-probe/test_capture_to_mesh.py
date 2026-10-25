#!/usr/bin/env python3
"""Frozen gate for capture_to_mesh.py: an F9 capture directory -> C++ header for the Remix probe.

Usage: test_capture_to_mesh.py <candidate.py>
The candidate CLI is `python3 <candidate> <capture_dir> <out_header>`. The generated header is compiled with
g++ together with a checker that prints every array as JSON; values are compared exactly (float32) against
an independent reference decode written here. Prints {"passed": true, ...} on success.
"""
import json, math, shutil, struct, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAPS = HERE.parent / 'runtime' / 'remix-probe' / 'captures'
REAL = CAPS / '2b-head-786idx'
BODY = CAPS / '2b-body-13533idx'  # stream 1 stride 20 (uv @0, normal @8, uv copy @16)
CHECKER = r'''
#include <cstdio>
#include "mesh.h"
static_assert(sizeof(captured_positions) / sizeof(captured_positions[0]) == captured_vertex_count, "positions");
static_assert(sizeof(captured_normals) / sizeof(captured_normals[0]) == captured_vertex_count, "normals");
static_assert(sizeof(captured_texcoords) / sizeof(captured_texcoords[0]) == captured_vertex_count, "texcoords");
static_assert(sizeof(captured_indices) / sizeof(captured_indices[0]) == captured_index_count, "indices");
int main() {
    std::printf("{\"inferred\":%d,\"v\":[", captured_has_inferred_attributes ? 1 : 0);
    for (unsigned i = 0; i < captured_vertex_count; ++i)
        std::printf("%s[%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g]", i ? "," : "",
                    captured_positions[i][0], captured_positions[i][1], captured_positions[i][2],
                    captured_normals[i][0], captured_normals[i][1], captured_normals[i][2],
                    captured_texcoords[i][0], captured_texcoords[i][1]);
    std::printf("],\"i\":[");
    for (unsigned i = 0; i < captured_index_count; ++i) std::printf("%s%u", i ? "," : "", captured_indices[i]);
    std::printf("]}\n");
}
'''


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def half(b, o):
    return struct.unpack_from('<e', b, o)[0]


def reference(d):
    """Independent decode of the spec in the brief. Returns (inferred, vertices, indices)."""
    meta = json.loads((d / 'capture.json').read_text())
    isize = {57: 2, 42: 4}[meta['ib_format']]
    ib = (d / 'ib.bin').read_bytes()
    first = meta['ib_offset'] + meta['start_index'] * isize
    raw = [struct.unpack_from('<H' if isize == 2 else '<I', ib, first + k * isize)[0] for k in range(meta['index_count'])]
    ids = [r + meta['base_vertex'] for r in raw]
    vbs = {v['slot']: v for v in meta['vertex_buffers']}
    pos = next(e for e in meta['layout'] if e['semantic'] == 'POSITION')
    pslot = pos.get('slot', 0)
    vb0, s0 = (d / f'vb_{pslot}.bin').read_bytes(), vbs[pslot]
    s1 = vbs.get(1)
    inferred = s1 is not None and s1['stride'] in (16, 20) and (d / 'vb_1.bin').exists()
    vb1 = (d / 'vb_1.bin').read_bytes() if inferred else b''
    unique = sorted(set(ids))
    out = []
    for vid in unique:
        o = s0['offset'] + vid * s0['stride'] + pos['offset']
        if pos['format'] == 6 or pos['format'] == 2:
            p = struct.unpack_from('<3f', vb0, o)
        else:  # 10: R16G16B16A16_FLOAT
            p = (half(vb0, o), half(vb0, o + 2), half(vb0, o + 4))
        if inferred:
            o1 = s1['offset'] + vid * s1['stride']
            n = (half(vb1, o1 + 8), half(vb1, o1 + 10), half(vb1, o1 + 12))
            t = (half(vb1, o1), half(vb1, o1 + 2))
        else:
            n, t = (0.0, 0.0, -1.0), (0.0, 0.0)
        out.append([f32(x) for x in (*p, *n, *t)])
    rank = {vid: k for k, vid in enumerate(unique)}
    return inferred, out, [rank[v] for v in ids]


def run(candidate, d, work):
    out = work / 'mesh.h'
    if out.exists():
        out.unlink()
    p = subprocess.run([sys.executable, str(candidate), str(d), str(out)], capture_output=True, text=True, timeout=120)
    return p, out


def compiled(out, work):
    (work / 'check.cpp').write_text(CHECKER)
    exe = work / 'check'
    if not out.exists():
        raise AssertionError('exit 0 but no header was written')
    c = subprocess.run(['g++', '-std=c++17', '-O0', '-I', str(work), str(work / 'check.cpp'), '-o', str(exe)],
                       capture_output=True, text=True)
    if c.returncode:
        raise AssertionError('generated header does not compile with the checker: ' + c.stderr[-1500:])
    return json.loads(subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout)


def expect_ok(candidate, d, work, name):
    p, out = run(candidate, d, work)
    assert p.returncode == 0, f'{name}: exit {p.returncode}: {p.stderr}'
    got = compiled(out, work)
    inferred, verts, idx = reference(d)
    assert got['inferred'] == int(inferred), f'{name}: inferred flag {got["inferred"]}'
    assert got['i'] == idx, f'{name}: indices differ'
    assert len(got['v']) == len(verts), f'{name}: vertex count {len(got["v"])} != {len(verts)}'
    for k, (g, r) in enumerate(zip(got['v'], verts)):
        assert [f32(x) for x in g] == r, f'{name}: vertex {k} {g} != {r}'
    return len(verts), len(idx)


def expect_fail(candidate, d, work, name, code):
    p, out = run(candidate, d, work)
    assert p.returncode == code, f'{name}: exit {p.returncode} (want {code}): {p.stderr}'
    assert not out.exists(), f'{name}: header written on failure'


def synth(work, name, *, ib_format=57, start_index=0, base_vertex=0, ib_offset=0, slot1=False,
          pos_format=6, bad_normal=False, drop_position=False, indices=(0, 1, 2, 2, 1, 3), vertices=4,
          slot1_stride=16):
    """Build a capture dir. Slot 0 stride 28 (position at 0); optional slot 1 stride 16 (uv half2 @0, normal half4 @8)."""
    d = work / name
    d.mkdir()
    s0 = 28
    vb0 = bytearray(base_vertex * s0)  # rows before base_vertex are padding
    vb1 = bytearray(base_vertex * slot1_stride)
    for v in range(vertices):
        row = bytearray(s0)
        p = (v * 0.5, -v * 0.25, 1.0 + v)
        if pos_format == 10:
            struct.pack_into('<4e', row, 0, *p, 1.0)
        else:
            struct.pack_into('<3f', row, 0, *p)
        vb0 += row
        n = (0.0, 0.6, 0.8) if not (bad_normal and v == 1) else (0.0, 0.0, 0.5)
        vb1 += struct.pack('<2e2B2B4e', v / 4, 1 - v / 4, 255, 255, 255, 255, *n, 0.0) + bytes(slot1_stride - 16)
    isize = 2 if ib_format == 57 else 4
    ib = bytes(ib_offset) + bytes(start_index * isize) + b''.join(
        struct.pack('<H' if isize == 2 else '<I', i) for i in indices)
    layout = [] if drop_position else [{'semantic': 'POSITION', 'format': pos_format, 'offset': 0}]
    layout.append({'semantic': 'BLENDWEIGHT', 'format': 28, 'offset': 24})
    vbs = [{'slot': 0, 'stride': s0, 'offset': 0, 'bytes': len(vb0)}]
    (d / 'vb_0.bin').write_bytes(vb0)
    if slot1:
        vbs.append({'slot': 1, 'stride': slot1_stride, 'offset': 0, 'bytes': len(vb1)})
        (d / 'vb_1.bin').write_bytes(vb1)
    (d / 'ib.bin').write_bytes(ib)
    (d / 'capture.json').write_text(json.dumps({
        'index_count': len(indices), 'start_index': start_index, 'base_vertex': base_vertex, 'instanced': 0,
        'has_index': 1, 'ib_format': ib_format, 'ib_offset': ib_offset, 'vertex_buffers': vbs,
        'layout_found': 1, 'layout': layout}))
    return d


def main():
    candidate = Path(sys.argv[1]).resolve()
    work = Path(tempfile.mkdtemp(prefix='capture-to-mesh-'))
    checks = []
    try:
        n = expect_ok(candidate, REAL, work, 'real 2B head capture')
        assert n == (757, 786), n
        checks.append('real capture 757 vertices / 786 indices, inferred normal+uv, exact float32')
        n = expect_ok(candidate, BODY, work, 'real 2B body capture (stream 1 stride 20)')
        assert n == (12349, 13533), n
        expect_ok(candidate, synth(work, 's20', slot1=True, slot1_stride=20, base_vertex=1), work, 'stride 20')
        expect_ok(candidate, synth(work, 's24', slot1=True, slot1_stride=24), work, 'stride 24 -> defaults')
        checks.append('stream 1 stride 20 inferred (real body 12349/13533 + synthetic); other strides -> defaults')
        expect_ok(candidate, synth(work, 'r16', start_index=2, base_vertex=1, ib_offset=4), work, 'r16 offsets')
        checks.append('R16 indices with ib_offset/start_index/base_vertex, no slot 1 -> defaults')
        expect_ok(candidate, synth(work, 'r32', ib_format=42, slot1=True, indices=(3, 1, 1, 0, 3, 2)), work, 'r32')
        checks.append('R32 indices, slot 1 inferred attributes, compaction order')
        expect_fail(candidate, synth(work, 'badn', slot1=True, bad_normal=True), work, 'bad normal', 3)
        checks.append('non-unit inferred normal -> exit 3, no header')
        expect_fail(candidate, synth(work, 'nopos', drop_position=True), work, 'no POSITION', 2)
        checks.append('missing POSITION -> exit 2, no header')
        # Reviewer findings (2026-10-25): negative metadata offsets and non-integer fields must exit 2, not alias/crash.
        d = synth(work, 'negoff')
        m = json.loads((d / 'capture.json').read_text())
        m['index_count'], m['layout'][0]['offset'] = 3, -28  # vertex 1 + offset -28 would alias vertex 0
        (d / 'ib.bin').write_bytes(struct.pack('<3H', 1, 2, 3))
        (d / 'capture.json').write_text(json.dumps(m))
        expect_fail(candidate, d, work, 'negative POSITION offset', 2)
        d = synth(work, 'listfmt')
        m = json.loads((d / 'capture.json').read_text()); m['ib_format'] = []
        (d / 'capture.json').write_text(json.dumps(m))
        expect_fail(candidate, d, work, 'ib_format as list', 2)
        checks.append('negative metadata offset / non-integer ib_format -> exit 2, no header')
        print(json.dumps({'passed': True, 'checks': checks}, indent=2))
    except AssertionError as e:
        print(json.dumps({'passed': False, 'error': str(e), 'checks_passed': checks}, indent=2))
        sys.exit(1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
