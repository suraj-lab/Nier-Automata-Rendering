#!/usr/bin/env python3
"""Convert a whole-frame D3D11 capture directory into a world-space NSCN scene binary."""
import hashlib
import json
import math
import struct
import sys
from collections import Counter
from pathlib import Path

import numpy as np

MAX_INDEX_COUNT = 1 << 24  # per draw; NieR's largest seen is 705K. Bounds memory on hostile captures.


class Reject(Exception):
    pass


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


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


def build(frame):
    # draw_<digits> fitting the uint32 table field; other folder names are ignored entirely.
    draws = sorted(p for p in frame.iterdir() if p.is_dir() and p.name.startswith('draw_') and p.name[5:].isdigit()
                   and int(p.name[5:]) < 2 ** 32)
    metas = {}
    for d in draws:
        try:
            c = json.loads((d / 'capture.json').read_text())
            if valid_meta(c):
                metas[d] = c
        except Exception:
            pass
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
            key = (sha(d / f'vb_{pslot}.bin'), sha(d / 'ib.bin'), c['start_index'], c['index_count'],
                   c['base_vertex'], sha(d / 'cb_11.bin') if (d / 'cb_11.bin').exists() else '',
                   vb['offset'], vb['stride'])
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
        keep &= (length > 0) & np.isfinite(v).all(axis=(1, 2)) & np.isfinite(length)  # NaN/inf world: drop
        v, nrm = v[keep], nrm[keep] / length[keep, None]
        table.append((int(d.name[5:]), sum(len(x) for x in tris), len(v), int(skinned)))
        tris.append(np.concatenate([v.reshape(-1, 9), nrm], axis=1))
        stats['kept'] += 1
    if first_kept is None:
        raise Reject('no usable draws')
    allt = np.concatenate(tris) if tris else np.zeros((0, 12))
    return camera(first_kept), table, allt, main, stats


def main():
    if len(sys.argv) != 3:
        print('usage: scene_from_frame.py <frame_dir> <out_scene.bin>', file=sys.stderr)
        sys.exit(2)
    frame, out = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        if not frame.is_dir():
            raise Reject('missing frame dir')
        cam, table, allt, main, stats = build(frame)
    except (Reject, KeyError, OSError, ValueError) as e:
        print(f'error: {e}', file=sys.stderr)
        sys.exit(2)
    blob = bytearray()
    blob += b'NSCN' + struct.pack('<3I', 1, len(table), len(allt))
    blob += struct.pack('<14f', *[float(x) for x in cam])
    for row in table:
        blob += struct.pack('<4I', *row)
    if allt.size:
        blob += np.ascontiguousarray(allt, dtype='<f4').tobytes()
    out.write_bytes(bytes(blob))
    print(json.dumps({'kept': stats['kept'], 'duplicates': stats['duplicates'], 'rejected': stats['rejected'],
                      'other_viewport': stats['other_viewport'], 'triangles': len(allt),
                      'main_viewport': list(main)}))


if __name__ == '__main__':
    main()
