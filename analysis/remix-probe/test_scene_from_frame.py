#!/usr/bin/env python3
"""Frozen gate for scene_from_frame.py: an F9 whole-frame capture -> world-space scene.bin for the Remix probe.

Usage: test_scene_from_frame.py <candidate.py>
The candidate CLI is `python3 <candidate> <frame_dir> <out_scene.bin>`. Its output is parsed and compared
against `reference()` below (the executable spec) on synthetic frames and on a real NieR frame.
Prints {"passed": true, ...} on success.
"""
import hashlib, json, math, shutil, struct, subprocess, sys, tempfile
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REAL = HERE.parent / 'runtime' / 'remix-probe' / 'captures' / 'frame_7991289'
MAGIC, VERSION = b'NSCN', 1
MAX_INDEX_COUNT = 1 << 24  # per draw; NieR's largest seen is 705K. Bounds memory on hostile captures.


# ---------------------------------------------------------------- reference (the spec)

class Reject(Exception):
    pass


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_indices(d, c):
    size = {57: 2, 42: 4}.get(c.get('ib_format'))
    if c.get('has_index') != 1 or size is None or not 0 <= c['index_count'] <= MAX_INDEX_COUNT:
        raise Reject('index')
    ib = (d / 'ib.bin').read_bytes()
    first, n = c['ib_offset'] + c['start_index'] * size, c['index_count']
    if first < 0 or first + n * size > len(ib):
        raise Reject('ib range')
    raw = np.frombuffer(ib, dtype='<u2' if size == 2 else '<u4', count=n, offset=first).astype(np.int64)
    return raw + c['base_vertex']


def element_bytes(d, c, e, ids, width):
    """(len(ids), width) uint8 rows of element `e` for vertex ids."""
    vbs = {v['slot']: v for v in c['vertex_buffers']}
    slot = e.get('slot', 0)
    if slot not in vbs:
        raise Reject('slot')
    vb = np.frombuffer((d / f'vb_{slot}.bin').read_bytes(), dtype=np.uint8)
    o = vbs[slot]['offset'] + ids * vbs[slot]['stride'] + e['offset']
    if ids.size and (o.min() < 0 or o.max() + width > vb.size):
        raise Reject('vb range')
    return vb[o[:, None] + np.arange(width)[None, :]]


def positions(d, c, e, ids):
    fmt = e['format']
    if fmt in (2, 6):
        return element_bytes(d, c, e, ids, 12).copy().view('<f4').reshape(-1, 3).astype(np.float64)
    if fmt == 10:
        return element_bytes(d, c, e, ids, 6).copy().view('<f2').reshape(-1, 3).astype(np.float64)
    raise Reject('position format')


def mats(cb11, count):
    return np.frombuffer(cb11, dtype='<f4', count=count * 12).astype(np.float64).reshape(count, 3, 4)


def world_positions(d, c, ids):
    lay = {e['semantic']: e for e in c['layout']}
    if 'POSITION' not in lay:
        raise Reject('no position')
    p = positions(d, c, lay['POSITION'], ids)
    cb11 = (d / 'cb_11.bin').read_bytes() if (d / 'cb_11.bin').exists() else b''
    ph = np.concatenate([p, np.ones((len(p), 1))], axis=1)
    bi, bw = lay.get('BLENDINDICES'), lay.get('BLENDWEIGHT')
    if bi and bw and bi['format'] == 30 and bw['format'] == 28:
        idx = element_bytes(d, c, bi, ids, 4).astype(np.int64)
        w = element_bytes(d, c, bw, ids, 4).astype(np.float64) / 255.0
        used = idx[w > 0]
        nb = len(cb11) // 48
        if used.size and used.max() >= nb:
            raise Reject('bone index')
        bones = mats(cb11, nb) if nb else np.zeros((1, 3, 4))
        out = np.zeros((len(p), 3))
        for k in range(4):
            m = w[:, k] > 0
            out[m] += w[m, k, None] * np.einsum('nij,nj->ni', bones[idx[m, k]], ph[m])
        return out, True
    if len(cb11) < 48:
        raise Reject('cb11')
    return ph @ mats(cb11, 1)[0].T, False


def camera(d):
    f = np.frombuffer((d / 'cb_0.bin').read_bytes(), dtype='<f4', count=32).astype(np.float64)
    if not np.isfinite(f).all() or f[21] <= 0 or f[16] <= 0:
        raise Reject('invalid camera')
    R, t = f[0:12].reshape(3, 4)[:, :3], f[0:12].reshape(3, 4)[:, 3]
    pos = -R.T @ t
    fov = math.degrees(2 * math.atan(1 / f[21]))
    return [*pos, *(-R[2]), *R[1], *R[0], fov, f[21] / f[16]]


def valid_meta(c):
    """Top-level shape checks; anything deeper that is malformed rejects the draw during decoding."""
    ints = ('vp_width', 'vp_height', 'index_count', 'start_index', 'base_vertex', 'ib_offset')
    return (isinstance(c, dict) and all(type(c.get(k)) is int for k in ints) and isinstance(c.get('layout'), list)
            and all(isinstance(e, dict) for e in c['layout']) and isinstance(c.get('vertex_buffers'), list)
            and all(isinstance(v, dict) and all(type(v.get(k)) is int and v[k] >= 0 for k in ('slot', 'stride', 'offset'))
                    for v in c['vertex_buffers'])
            and all(type(e.get('offset')) is int and e['offset'] >= 0 and type(e.get('slot', 0)) is int for e in c['layout']))


def reference(frame):
    # Folder names must be draw_<digits> fitting uint32 (the table field); others are ignored entirely.
    draws = sorted(p for p in frame.iterdir() if p.is_dir() and p.name.startswith('draw_') and p.name[5:].isdigit()
                   and int(p.name[5:]) < 2 ** 32)
    metas = {}
    for d in draws:
        try:
            c = json.loads((d / 'capture.json').read_text())
        except Exception:
            continue
        if valid_meta(c):
            metas[d] = c
    vps = Counter((m['vp_width'], m['vp_height']) for m in metas.values())
    if not vps:
        raise Reject('no draws')
    main = max(vps, key=lambda k: (vps[k], k[0] * k[1]))
    seen, table, tris = set(), [], []
    stats = Counter()
    first_kept = None
    for d in draws:
        c = metas.get(d)
        if c is None:
            stats['rejected'] += 1
            continue
        if (c['vp_width'], c['vp_height']) != main:
            stats['other_viewport'] += 1
            continue
        try:
            lay = {e['semantic']: e for e in c['layout']}
            if 'POSITION' not in lay:
                raise Reject('no position')
            pslot = lay['POSITION'].get('slot', 0)
            vb = {v['slot']: v for v in c['vertex_buffers']}[pslot]
            key = (sha(d / f'vb_{pslot}.bin'), sha(d / 'ib.bin'), c['start_index'], c['index_count'], c['base_vertex'],
                   sha(d / 'cb_11.bin') if (d / 'cb_11.bin').exists() else '', vb['offset'], vb['stride'])
            if key in seen:
                stats['duplicates'] += 1
                continue
            ids = read_indices(d, c)
            n = len(ids) // 3 * 3
            ids = ids[:n]
            if ids.size and ids.min() < 0:
                raise Reject('negative id')
            uniq, inv = np.unique(ids, return_inverse=True)
            w, skinned = world_positions(d, c, uniq)
        except (Reject, KeyError, OSError, ValueError, TypeError, IndexError, OverflowError):
            stats['rejected'] += 1
            continue
        seen.add(key)
        if first_kept is None:
            first_kept = d
        v = w[inv].reshape(-1, 3, 3)
        t3 = ids.reshape(-1, 3)
        keep = (t3[:, 0] != t3[:, 1]) & (t3[:, 1] != t3[:, 2]) & (t3[:, 0] != t3[:, 2])
        nrm = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        length = np.linalg.norm(nrm, axis=1)
        keep &= (length > 0) & np.isfinite(v).all(axis=(1, 2)) & np.isfinite(length)
        v, nrm = v[keep], nrm[keep] / length[keep, None]
        table.append((int(d.name[5:]), sum(len(x) for x in tris), len(v), int(skinned)))
        tris.append(np.concatenate([v.reshape(-1, 9), nrm], axis=1))
        stats['kept'] += 1
    if first_kept is None:
        raise Reject('no usable draws')
    allt = np.concatenate(tris) if tris else np.zeros((0, 12))
    return {'camera': camera(first_kept), 'table': table, 'tris': allt, 'main_viewport': list(main),
            'stats': {'kept': stats['kept'], 'duplicates': stats['duplicates'], 'rejected': stats['rejected'],
                      'other_viewport': stats['other_viewport'], 'triangles': len(allt)}}


# ---------------------------------------------------------------- parse candidate output

def parse(path):
    b = path.read_bytes()
    assert b[:4] == MAGIC, 'bad magic'
    version, draws, ntri = struct.unpack_from('<3I', b, 4)
    assert version == VERSION, f'version {version}'
    cam = list(struct.unpack_from('<14f', b, 16))
    o = 16 + 56
    table = [struct.unpack_from('<4I', b, o + 16 * i) for i in range(draws)]
    o += 16 * draws
    tris = np.frombuffer(b, dtype='<f4', count=ntri * 12, offset=o).reshape(ntri, 12).astype(np.float64)
    assert len(b) == o + ntri * 48, f'file size {len(b)} != {o + ntri * 48}'
    return cam, [tuple(t) for t in table], tris


def run(candidate, frame, work):
    out = work / 'scene.bin'
    if out.exists():
        out.unlink()
    p = subprocess.run([sys.executable, str(candidate), str(frame), str(out)], capture_output=True, text=True, timeout=900)
    return p, out


def expect_ok(candidate, frame, work, name):
    p, out = run(candidate, frame, work)
    assert p.returncode == 0, f'{name}: exit {p.returncode}: {p.stderr[-800:]}'
    assert out.exists(), f'{name}: exit 0 but no output'
    ref = reference(frame)
    try:
        summary = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        raise AssertionError(f'{name}: last stdout line is not the JSON summary: {p.stdout[-300:]!r}')
    assert summary == {**ref['stats'], 'main_viewport': ref['main_viewport']}, f'{name}: summary {summary} != {ref["stats"]}'
    cam, table, tris = parse(out)
    assert table == ref['table'], f'{name}: draw table {table[:5]} != {ref["table"][:5]}'
    assert np.allclose(cam, ref['camera'], rtol=1e-5, atol=1e-4), f'{name}: camera {cam} != {ref["camera"]}'
    assert tris.shape == ref['tris'].shape, f'{name}: triangles {tris.shape} != {ref["tris"].shape}'
    bad = ~np.isclose(tris, ref['tris'], rtol=1e-5, atol=1e-3)
    assert not bad.any(), f'{name}: {int(bad.sum())} triangle floats differ, first at {np.argwhere(bad)[0].tolist()}'
    return ref['stats']


def expect_fail(candidate, frame, work, name):
    p, out = run(candidate, frame, work)
    assert p.returncode == 2, f'{name}: exit {p.returncode} (want 2): {p.stderr[-300:]}'
    assert not out.exists(), f'{name}: output written on failure'


# ---------------------------------------------------------------- synthetic frames

def mat34(rot_deg_y, t):
    a = math.radians(rot_deg_y)
    c, s = math.cos(a), math.sin(a)
    return [c, 0, s, t[0], 0, 1, 0, t[1], -s, 0, c, t[2]]


def camera_cb0():
    view = mat34(30, (-5, 2, -40))
    proj = [1.2, 0, 0, 0, 0, 2.0, 0, 0, 0, 0, -1, -0.1, 0, 0, -1, 0]
    return struct.pack('<64f', *view, 0, 0, 0, 1, *proj, *([0.0] * 32))


def draw(frame, n, *, vp=(640, 360), skinned=False, cb11=None, bones=None, indices=(0, 1, 2, 0, 2, 3, 1, 1, 2),
         weights=(255, 0, 0, 0)):
    d = frame / f'draw_{n:04d}'
    d.mkdir()
    quad = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    vb = bytearray()
    for i, p in enumerate(quad):
        vb += struct.pack('<3f', *p) + bytes(8)
        vb += bytes((i % 2, (i + 1) % 2, 0, 0)) + bytes(weights)  # BLENDINDICES @20, BLENDWEIGHT @24
    layout = [{'semantic': 'POSITION', 'format': 6, 'offset': 0, 'slot': 0}]
    if skinned:
        layout += [{'semantic': 'BLENDINDICES', 'format': 30, 'offset': 20, 'slot': 0},
                   {'semantic': 'BLENDWEIGHT', 'format': 28, 'offset': 24, 'slot': 0}]
    (d / 'vb_0.bin').write_bytes(vb)
    (d / 'ib.bin').write_bytes(struct.pack(f'<{len(indices)}H', *indices))
    (d / 'cb_0.bin').write_bytes(camera_cb0())
    if bones is not None:
        (d / 'cb_11.bin').write_bytes(b''.join(struct.pack('<12f', *m) for m in bones))
    elif cb11 is not None:
        (d / 'cb_11.bin').write_bytes(struct.pack('<12f', *cb11) + struct.pack('<4f', 0, 0, 0, 1))
    (d / 'capture.json').write_text(json.dumps({
        'index_count': len(indices), 'start_index': 0, 'base_vertex': 0, 'instanced': 0, 'has_index': 1,
        'ib_format': 57, 'ib_offset': 0, 'vp_width': vp[0], 'vp_height': vp[1],
        'vertex_buffers': [{'slot': 0, 'stride': 28, 'offset': 0, 'bytes': len(vb)}],
        'layout_found': 1, 'layout': layout, 'vs_cbs': []}))
    return d


def synthetic(work):
    f = work / 'frame_synth'
    f.mkdir()
    draw(f, 0, cb11=mat34(0, (10, 0, 0)))                                     # static; one repeated-index tri dropped
    draw(f, 1, cb11=mat34(90, (0, 5, 0)))                                     # static, rotated
    shutil.copytree(f / 'draw_0000', f / 'draw_0002')                         # duplicate of draw 0
    draw(f, 3, vp=(1024, 1024), cb11=mat34(0, (0, 0, 0)))                     # shadow-map viewport: filtered
    draw(f, 4, skinned=True, bones=[mat34(0, (0, 0, 3)), mat34(45, (2, 0, 0))], weights=(128, 127, 0, 0))
    draw(f, 5, skinned=True, bones=[mat34(0, (0, 0, 0))])                     # bone index 1 out of range: rejected
    draw(f, 6)                                                                # no cb_11: rejected
    (f / 'draw_0007').mkdir()                                                 # no capture.json: rejected
    return f


def main():
    candidate = Path(sys.argv[1]).resolve()
    work = Path(tempfile.mkdtemp(prefix='scene-from-frame-'))
    checks = []
    try:
        s = expect_ok(candidate, synthetic(work), work, 'synthetic frame')
        assert s == {'kept': 3, 'duplicates': 1, 'rejected': 3, 'other_viewport': 1, 'triangles': 6}, s
        checks.append('synthetic: static + rotated + skinned kept, duplicate/shadow/bad-bone/no-cb11/no-json handled')
        empty = work / 'frame_empty'
        empty.mkdir()
        draw(empty, 0)  # only draw has no cb_11 -> no usable draws
        expect_fail(candidate, empty, work, 'no usable draws')
        expect_fail(candidate, work / 'missing', work, 'missing frame dir')
        checks.append('no usable draws / missing frame -> exit 2, no output')
        # Reviewer findings (2026-10-25): hostile/hand-edited captures must reject draws or exit 2, never crash.
        m = work / 'frame_malformed'
        m.mkdir()
        draw(m, 0, cb11=mat34(0, (0, 0, 0)))                                   # the one good draw
        bad = [draw(m, i, cb11=mat34(0, (i, 0, 0))) for i in range(1, 5)]
        for d, edit in zip(bad, [lambda c: c.update(vp_width=[]),             # wrong viewport type
                                 lambda c: c['layout'].append('POSITION'),    # non-dict layout entry
                                 lambda c: c['vertex_buffers'][0].update(stride='28'),  # string stride
                                 lambda c: c.update(index_count=MAX_INDEX_COUNT + 3)]):  # over the size bound
            c = json.loads((d / 'capture.json').read_text()); edit(c); (d / 'capture.json').write_text(json.dumps(c))
        shutil.copytree(m / 'draw_0000', m / 'draw_4294967296')               # draw number past uint32: ignored
        nan = draw(m, 5, cb11=mat34(0, (0, 0, 9)))
        (nan / 'cb_11.bin').write_bytes(struct.pack('<12f', *([float('nan')] * 12)) + bytes(16))  # NaN world: tris dropped
        s = expect_ok(candidate, m, work, 'malformed frame')
        assert s == {'kept': 2, 'duplicates': 0, 'rejected': 4, 'other_viewport': 0, 'triangles': 2}, s
        z = work / 'frame_badcam'
        z.mkdir()
        d = draw(z, 0, cb11=mat34(0, (0, 0, 0)))
        cb = bytearray((d / 'cb_0.bin').read_bytes()); cb[84:88] = struct.pack('<f', 0.0); (d / 'cb_0.bin').write_bytes(cb)
        expect_fail(candidate, z, work, 'zero projection term')
        checks.append('malformed types / size bound / uint32 draw number / NaN world / bad camera handled')
        s = expect_ok(candidate, REAL, work, 'real NieR frame_7991289')
        assert s['kept'] >= 60 and s['triangles'] > 100000, s
        checks.append(f'real frame: {s}')
        print(json.dumps({'passed': True, 'checks': checks}, indent=2))
    except AssertionError as e:
        print(json.dumps({'passed': False, 'error': str(e), 'checks_passed': checks}, indent=2))
        sys.exit(1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
