#!/usr/bin/env python3
"""Frozen gate for scene_from_frame.py: an F9 whole-frame capture -> world-space scene.bin (v3) for the Remix probe.

Usage: test_scene_from_frame.py <candidate.py>
The candidate CLI is `python3 <candidate> <frame_dir> <out_scene.bin>`. Its output is parsed and compared
against `reference()` below (the executable spec) on synthetic frames and on a real NieR frame.
Set SCENE_TEXTURED_FRAME=<frame dir> to also check a real capture that has textures.
Prints {"passed": true, ...} on success.
"""
import hashlib, json, math, os, shutil, struct, subprocess, sys, tempfile
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REAL = HERE.parent / 'runtime' / 'remix-probe' / 'captures' / 'frame_7991289'
FULL = HERE.parent / 'runtime' / 'remix-probe' / 'captures' / 'frame_9443695'  # colour pass + instancing
MAGIC, VERSION = b'NSCN', 3
FLOATS = 24  # per triangle: 3 vertices x (position[3], normal[3], uv[2])
NAME_BYTES = 32  # fixed width of a texture file name in the texture table
# DXGI *_UNORM_SRGB: NieR stores diffuse maps sRGB and its masks/normals linear, so this is what selects albedo.
SRGB_FORMATS = {72, 75, 78, 90, 91}
MAX_INDEX_COUNT = 1 << 24  # per draw; NieR's largest seen is 705K. Bounds memory on hostile captures.
MAX_INSTANCES = 4096


# ---------------------------------------------------------------- reference (the spec)

class Reject(Exception):
    pass


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_indices(d, c):
    size = {57: 2, 42: 4}.get(c.get('ib_format'))
    if c.get('has_index') != 1 or size is None or not 0 <= c['index_count'] <= MAX_INDEX_COUNT:
        raise Reject('index')
    if not -(2 ** 32) <= c['base_vertex'] < 2 ** 32:
        raise Reject('base_vertex')
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


def tex_index(frame):
    """textures/index.json -> {id: entry}; a missing or malformed index means no textures."""
    try:
        raw = json.loads((frame / 'textures' / 'index.json').read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, list):
        return {}
    return {t['id']: t for t in raw if isinstance(t, dict) and type(t.get('id')) is int
            and 0 <= t['id'] < 2 ** 32
            and type(t.get('format')) is int and type(t.get('width')) is int and type(t.get('height')) is int}


def albedo(c, index, frame):
    """Id of the draw's diffuse map: the largest-area sRGB texture bound to the pixel shader, lowest slot on a
    tie. 0 when the draw has none or its DDS was not written."""
    ranked = []
    for p in c.get('ps_textures') or []:
        if not isinstance(p, dict) or type(p.get('slot')) is not int or p['slot'] < 0:
            continue
        t = index.get(p.get('id'))
        if t is None or t['format'] not in SRGB_FORMATS or t['width'] <= 0 or t['height'] <= 0:
            continue
        ranked.append(((t['width'] * t['height'], -p['slot']), t['id']))
    for _, tid in sorted(ranked, reverse=True):
        dds = frame / 'textures' / f'tex_{tid}.dds'
        if dds.is_file() and not mostly_black(dds):
            return tid
    return 0


def mostly_black(path):
    """True when an atlas is mostly black, i.e. a detail/mask map rather than a diffuse map.

    Reads only the block colour endpoints (BC1: bytes 0-3; BC2/BC3: bytes 8-11, after the alpha block), so it
    needs no decode. NieR's mask atlases are black with sparse motifs; a diffuse map is not.
    """
    b = Path(path).read_bytes()
    if len(b) < 148 or b[:4] != b'DDS ':
        return False
    stride = {71: 8, 72: 8, 75: 16, 77: 16, 78: 16}.get(struct.unpack_from('<I', b, 128)[0])
    if stride is None:
        return False
    n = (len(b) - 148) // stride
    if n <= 0:
        return False
    off = stride - 8  # BC1 keeps the colour endpoints at 0; BC2/BC3 store an 8-byte alpha block first
    blocks = np.frombuffer(b[148:148 + n * stride], dtype=np.uint8).reshape(n, stride)[:, off:off + 4]
    c = np.frombuffer(np.ascontiguousarray(blocks).tobytes(), dtype='<u2').reshape(n, 2).astype(np.uint32)
    rgb = np.stack([((c >> 11) & 31) / 31, ((c >> 5) & 63) / 63, (c & 31) / 31], axis=2)  # n,2,3
    dark = rgb.max(axis=2).max(axis=1) < 0.10  # both endpoints black -> the whole block is black
    # 0.9, not 0.5: on the real capture a legitimate cutout diffuse (a green banner, 0.54) overlaps a
    # detail mask (0.66), and this statistic cannot tell them apart. Only near-empty atlases are rejected
    # here; telling a mask from a diffuse needs the shader identity, which the capture does not record yet.
    # shortcut: a mask atlas that is 50-90% black is still used as albedo and paints its surface black.
    return float(dark.mean()) > 0.9

def first(layout, semantic, formats):
    """First element (layout order) with this semantic; None unless its format is one we decode."""
    for e in layout:
        if e['semantic'] == semantic:
            return e if e['format'] in formats else None
    return None


def normals(d, c, e, ids):  # NORMAL: 10 = float16 x4 (first 3), 2/6 = float32 x3+
    if e['format'] == 10:
        return element_bytes(d, c, e, ids, 6).copy().view('<f2').reshape(-1, 3).astype(np.float64)
    return element_bytes(d, c, e, ids, 12).copy().view('<f4').reshape(-1, 3).astype(np.float64)


def texcoords(d, c, e, ids):  # TEXCOORD: 34 = float16 x2, 16 = float32 x2
    if e['format'] == 34:
        return element_bytes(d, c, e, ids, 4).copy().view('<f2').reshape(-1, 2).astype(np.float64)
    return element_bytes(d, c, e, ids, 8).copy().view('<f4').reshape(-1, 2).astype(np.float64)


def score(c):
    """Duplicate draws (same geometry + transform in several passes): keep the one with the most attributes."""
    lay = c['layout']
    return (first(lay, 'NORMAL', (2, 6, 10)) is not None, first(lay, 'TEXCOORD', (16, 34)) is not None, len(lay))


def world_attrs(d, c, ids):
    """-> list of (world positions, world normals or None) per instance, uv (shared), skinned."""
    lay = {e['semantic']: e for e in c['layout']}
    if 'POSITION' not in lay:
        raise Reject('no position')
    p = positions(d, c, lay['POSITION'], ids)
    ne = first(c['layout'], 'NORMAL', (2, 6, 10))
    n = normals(d, c, ne, ids) if ne else None
    te = first(c['layout'], 'TEXCOORD', (16, 34))
    uv = texcoords(d, c, te, ids) if te else np.zeros((len(p), 2))
    cb11 = (d / 'cb_11.bin').read_bytes() if (d / 'cb_11.bin').exists() else b''
    ph = np.concatenate([p, np.ones((len(p), 1))], axis=1)
    bi, bw = lay.get('BLENDINDICES'), lay.get('BLENDWEIGHT')
    if bi and bw and bi['format'] == 30 and bw['format'] == 28:  # skinned: one copy, instancing ignored
        idx = element_bytes(d, c, bi, ids, 4).astype(np.int64)
        w = element_bytes(d, c, bw, ids, 4).astype(np.float64) / 255.0
        used = idx[w > 0]
        nb = len(cb11) // 48
        if used.size and used.max() >= nb:
            raise Reject('bone index')
        bones = mats(cb11, nb) if nb else np.zeros((1, 3, 4))
        out, nout = np.zeros((len(p), 3)), np.zeros((len(p), 3))
        for k in range(4):
            m = w[:, k] > 0
            out[m] += w[m, k, None] * np.einsum('nij,nj->ni', bones[idx[m, k]], ph[m])
            if n is not None:
                nout[m] += w[m, k, None] * np.einsum('nij,nj->ni', bones[idx[m, k], :, :3], n[m])
        return [(out, nout if n is not None else None)], uv, True
    count = c.get('instance_count', 1) if c.get('instanced') == 1 else 1
    if type(count) is not int or not 1 <= count <= MAX_INSTANCES:
        raise Reject('instance_count')
    if len(cb11) < 64 * (count - 1) + 48:  # one 3x4 world matrix per instance at a 64-byte stride
        raise Reject('cb11')
    out = []
    for i in range(count):
        M = np.frombuffer(cb11, dtype='<f4', count=12, offset=64 * i).astype(np.float64).reshape(3, 4)
        out.append((ph @ M.T, n @ M[:, :3].T if n is not None else None))
    return out, uv, False


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
    index = tex_index(frame)
    # Folder names must be draw_<digits> fitting uint32 (the table field); others are ignored entirely.
    draws = sorted(p for p in frame.iterdir() if p.is_dir() and p.name.startswith('draw_') and p.name[5:].isascii()
                   and p.name[5:].isdigit() and int(p.name[5:]) < 2 ** 32)
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
    ERRORS = (Reject, KeyError, OSError, ValueError, TypeError, IndexError, OverflowError)
    groups, order, stats = {}, [], Counter()
    for d in draws:  # group main-viewport draws by geometry + transform; groups keep first-appearance order
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
        except ERRORS:
            stats['rejected'] += 1
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(d)
    table, tris, first_kept = [], [], None
    for key in order:
        # richest first (score descending), draw order breaks ties; a failed decode falls back to the next
        try:
            cands = sorted(groups[key], key=lambda d: tuple(-int(x) for x in score(metas[d])) + (d.name,))
        except (Reject, KeyError, OSError, ValueError, TypeError, IndexError, OverflowError):
            stats['rejected'] += len(groups[key])
            continue
        for i, d in enumerate(cands):
            c = metas[d]
            try:
                ids = read_indices(d, c)
                ids = ids[:len(ids) // 3 * 3]
                if ids.size and ids.min() < 0:
                    raise Reject('negative id')
                uniq, inv = np.unique(ids, return_inverse=True)
                instances, uv, skinned = world_attrs(d, c, uniq)
            except ERRORS:
                stats['rejected'] += 1
                continue
            stats['duplicates'] += len(cands) - i - 1
            if first_kept is None:
                first_kept = d
            t3 = ids.reshape(-1, 3)
            distinct = (t3[:, 0] != t3[:, 1]) & (t3[:, 1] != t3[:, 2]) & (t3[:, 0] != t3[:, 2])
            start = sum(len(x) for x in tris)
            for wp, wn in instances:
                v = wp[inv].reshape(-1, 3, 3)
                face = np.cross(v[:, 2] - v[:, 0], v[:, 1] - v[:, 0])  # NieR/D3D front faces are clockwise
                length = np.linalg.norm(face, axis=1)
                fits = np.isfinite(v.astype(np.float32)).all(axis=(1, 2))
                keep = distinct & (length > 0) & np.isfinite(v).all(axis=(1, 2)) & np.isfinite(length) & fits
                face = face[keep] / length[keep, None]
                v = v[keep]
                if wn is not None:
                    vn = wn[inv].reshape(-1, 3, 3)[keep]
                    nl = np.linalg.norm(vn, axis=2, keepdims=True)
                    ok = np.isfinite(vn).all(axis=2, keepdims=True) & np.isfinite(nl) & (nl > 0)
                    vn = np.where(ok, vn / np.where(ok, nl, 1), face[:, None, :])
                else:
                    vn = np.broadcast_to(face[:, None, :], v.shape)
                t = uv[inv].reshape(-1, 3, 2)[keep]
                t = np.where(np.isfinite(t), t, 0.0)
                tris.append(np.concatenate([v, vn, t], axis=2).reshape(-1, FLOATS))
            table.append((int(d.name[5:]), start, sum(len(x) for x in tris) - start, int(skinned),
                          albedo(c, index, frame)))
            stats['kept'] += 1
            break
    if first_kept is None:
        raise Reject('no usable draws')
    allt = np.concatenate(tris) if tris else np.zeros((0, FLOATS))
    tex = sorted({row[4] for row in table if row[4]})
    assert all(len(f'tex_{t}.dds') <= NAME_BYTES for t in tex), 'texture name does not fit the table field'
    return {'camera': camera(first_kept), 'table': table, 'tris': allt, 'textures': tex,
            'main_viewport': list(main),
            'stats': {'kept': stats['kept'], 'duplicates': stats['duplicates'], 'rejected': stats['rejected'],
                      'other_viewport': stats['other_viewport'], 'triangles': len(allt), 'textures': len(tex)}}


# ---------------------------------------------------------------- parse candidate output

def parse(path):
    b = path.read_bytes()
    entry = 4 + NAME_BYTES
    try:
        assert b[:4] == MAGIC, 'bad magic'
        version, draws, ntri, ntex = struct.unpack_from('<4I', b, 4)
        assert version == VERSION, f'version {version}'
        cam = list(struct.unpack_from('<14f', b, 20))
        o = 20 + 56
        table = [struct.unpack_from('<5I', b, o + 20 * i) for i in range(draws)]
        o += 20 * draws
        tex = []
        for i in range(ntex):
            tid = struct.unpack_from('<I', b, o + entry * i)[0]
            raw = b[o + entry * i + 4:o + entry * i + entry]
            name = raw.rstrip(b'\0')
            assert raw[len(name):] == b'\0' * (len(raw) - len(name)), 'texture name not NUL padded'
            tex.append((tid, name.decode()))
        o += entry * ntex
        tris = np.frombuffer(b, dtype='<f4', count=ntri * FLOATS, offset=o).reshape(ntri, FLOATS).astype(np.float64)
        assert len(b) == o + ntri * FLOATS * 4, f'file size {len(b)} != {o + ntri * FLOATS * 4}'
    except (struct.error, UnicodeDecodeError, ValueError) as e:
        raise AssertionError(f'malformed scene.bin: {e}')  # a bad file must fail the gate, not the gate itself
    return cam, [tuple(t) for t in table], tris, tex


def run(candidate, frame, work):
    out = work / 'scene.bin'
    if out.exists():
        out.unlink()
    shutil.rmtree(work / (out.stem + '_textures'), ignore_errors=True)  # a stale set would mask a real run
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
    cam, table, tris, tex = parse(out)
    assert table == ref['table'], f'{name}: draw table {table[:5]} != {ref["table"][:5]}'
    assert [t[0] for t in tex] == ref['textures'], f'{name}: texture ids {[t[0] for t in tex]} != {ref["textures"]}'
    for tid, fname in tex:
        assert fname == f'tex_{tid}.dds', f'{name}: texture name {fname!r} for id {tid}'
    dest = work / (out.stem + '_textures')
    copied = sorted(q.name for q in dest.iterdir()) if dest.is_dir() else []
    want = sorted(f'tex_{t}.dds' for t in ref['textures'])
    assert copied == want, f'{name}: copied {copied} != expected {want}'
    for tid in ref['textures']:  # byte-identical to the capture's own DDS
        assert (dest / f'tex_{tid}.dds').read_bytes() == (frame / 'textures' / f'tex_{tid}.dds').read_bytes(), \
            f'{name}: tex {tid} differs from the captured DDS'
    assert np.allclose(cam, ref['camera'], rtol=1e-5, atol=1e-4), f'{name}: camera {cam} != {ref["camera"]}'
    assert tris.shape == ref['tris'].shape, f'{name}: triangles {tris.shape} != {ref["tris"].shape}'
    bad = ~np.isclose(tris, ref['tris'], rtol=1e-5, atol=1e-3)
    assert not bad.any(), f'{name}: {int(bad.sum())} triangle floats differ, first at {np.argwhere(bad)[0].tolist()}'
    return ref['stats'], cam, table, tris


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
         weights=(255, 0, 0, 0), normal=None, instances=None, ps_textures=None):
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
    vbs = [{'slot': 0, 'stride': 28, 'offset': 0, 'bytes': len(vb)}]
    if normal is not None:  # NieR colour-pass stream 1: uv half2 @0, normal half4 @8
        s1 = b''.join(struct.pack('<2e4x4e', i * 0.25, 1 - i * 0.25, *normal, 0) for i in range(4))
        (d / 'vb_1.bin').write_bytes(s1)
        vbs.append({'slot': 1, 'stride': 16, 'offset': 0, 'bytes': len(s1)})
        layout += [{'semantic': 'TEXCOORD', 'format': 34, 'offset': 0, 'slot': 1},
                   {'semantic': 'NORMAL', 'format': 10, 'offset': 8, 'slot': 1}]
    (d / 'ib.bin').write_bytes(struct.pack(f'<{len(indices)}H', *indices))
    (d / 'cb_0.bin').write_bytes(camera_cb0())
    if bones is not None:
        (d / 'cb_11.bin').write_bytes(b''.join(struct.pack('<12f', *m) for m in bones))
    elif instances is not None:  # one 64-byte (3x4 + 0,0,0,1) matrix per instance
        (d / 'cb_11.bin').write_bytes(b''.join(struct.pack('<12f', *m) + struct.pack('<4f', 0, 0, 0, 1) for m in instances))
    elif cb11 is not None:
        (d / 'cb_11.bin').write_bytes(struct.pack('<12f', *cb11) + struct.pack('<4f', 0, 0, 0, 1))
    (d / 'capture.json').write_text(json.dumps({
        'index_count': len(indices), 'start_index': 0, 'base_vertex': 0, 'has_index': 1,
        'instanced': int(instances is not None), 'instance_count': len(instances) if instances else 0,
        'ib_format': 57, 'ib_offset': 0, 'vp_width': vp[0], 'vp_height': vp[1], 'vertex_buffers': vbs,
        'layout_found': 1, 'layout': layout, 'vs_cbs': [], 'ps_textures': ps_textures or []}))
    return d


def texture(frame, tid, *, fmt=72, w=64, h=64, payload=None, write_dds=True):
    """Add tex_<tid>.dds to the capture's texture dir + its index.json entry (format 72 = BC1_UNORM_SRGB)."""
    tdir = frame / 'textures'
    tdir.mkdir(exist_ok=True)
    index_file = tdir / 'index.json'
    index = json.loads(index_file.read_text()) if index_file.exists() else []
    index = [t for t in index if t['id'] != tid] + [{'id': tid, 'format': fmt, 'width': w, 'height': h}]
    index_file.write_text(json.dumps(index))
    if write_dds:  # 148-byte DDS + DX10 header, then opaque payload bytes (never decoded by the converter)
        body = payload if payload is not None else bytes(((tid * 37) + i) & 0xff for i in range(64))
        (tdir / f'tex_{tid}.dds').write_bytes(b'DDS ' + bytes(80) + b'DX10' + bytes(60) + body)
    return {'slot': 0, 'id': tid}


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
        s, _, syn_table, syn_tris = expect_ok(candidate, synthetic(work), work, 'synthetic frame')
        # Fallback normal is the clockwise face normal: quad (0,0,0),(1,0,0),(1,1,0) at x+10 -> (0,0,-1).
        assert np.allclose(syn_tris[0, 3:6], (0, 0, -1)) and np.allclose(syn_tris[0, 6:8], (0, 0)), syn_tris[0]
        assert s == {'kept': 3, 'duplicates': 1, 'rejected': 3, 'other_viewport': 1, 'triangles': 6, 'textures': 0}, s
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
        s = expect_ok(candidate, m, work, 'malformed frame')[0]
        assert s == {'kept': 2, 'duplicates': 0, 'rejected': 4, 'other_viewport': 0, 'triangles': 2, 'textures': 0}, s
        z = work / 'frame_badcam'
        z.mkdir()
        d = draw(z, 0, cb11=mat34(0, (0, 0, 0)))
        cb = bytearray((d / 'cb_0.bin').read_bytes()); cb[84:88] = struct.pack('<f', 0.0); (d / 'cb_0.bin').write_bytes(cb)
        expect_fail(candidate, z, work, 'zero projection term')
        checks.append('malformed types / size bound / uint32 draw number / NaN world / bad camera handled')
        # v2: richest duplicate wins, normals rotated by the world matrix, instancing.
        v = work / 'frame_v2'
        v.mkdir()
        draw(v, 0, cb11=mat34(90, (0, 0, 0)))                                  # depth pass: position only
        draw(v, 1, cb11=mat34(90, (0, 0, 0)), normal=(0, 0, -1))              # colour pass, same geometry
        draw(v, 2, instances=[mat34(0, (0, 0, 0)), mat34(0, (5, 0, 0)), mat34(0, (0, 7, 0))])  # 3 instances
        s, cam, table, tris = expect_ok(candidate, v, work, 'v2 frame')
        assert s == {'kept': 2, 'duplicates': 1, 'rejected': 0, 'other_viewport': 0, 'triangles': 2 + 6, 'textures': 0}, s
        assert table[0][0] == 1, f'richest duplicate not chosen: {table}'
        assert np.allclose(tris[0, 3:6], (-1, 0, 0), atol=1e-6), f'normal not rotated by world: {tris[0, 3:6]}'
        assert np.allclose(tris[0, 6:8], (0, 1)), f'uv of vertex 0: {tris[0, 6:8]}'
        # draw 1 -> rows 0-1; draw 2 has 2 triangles per instance -> instance 1 at row 4, instance 2 at row 6
        assert np.allclose(tris[4, 0:3], (5, 0, 0)) and np.allclose(tris[6, 0:3], (0, 7, 0)), tris[[4, 6], 0:3]
        checks.append('v2: colour-pass duplicate chosen, world-rotated normal, uv, 3 instances')
        # v3: albedo = largest-area sRGB PS texture, lowest slot on a tie; linear-only and missing-DDS draws get 0.
        t = work / 'frame_tex'
        t.mkdir()
        draw(t, 0, cb11=mat34(0, (0, 0, 0)))                                    # no ps_textures -> 0
        big = texture(t, 40, w=512, h=512)                                      # sRGB 512^2 at slot 0
        small = texture(t, 41, w=64, h=64)
        draw(t, 1, cb11=mat34(0, (1, 0, 0)), ps_textures=[{**small, 'slot': 0}, {**big, 'slot': 3}])
        draw(t, 2, cb11=mat34(0, (2, 0, 0)), ps_textures=[{**big, 'slot': 0}, {**small, 'slot': 9}])  # same id: one entry
        tie_a, tie_b = texture(t, 42, w=128, h=128), texture(t, 43, w=128, h=128)
        draw(t, 3, cb11=mat34(0, (3, 0, 0)), ps_textures=[{**tie_b, 'slot': 2}, {**tie_a, 'slot': 5}])
        lin = texture(t, 44, fmt=71, w=2048, h=2048)                            # linear BC1: not albedo
        draw(t, 4, cb11=mat34(0, (4, 0, 0)), ps_textures=[{**lin, 'slot': 0}, {**small, 'slot': 1}])
        draw(t, 5, cb11=mat34(0, (5, 0, 0)), ps_textures=[{**texture(t, 45, fmt=71, w=1024, h=1024), 'slot': 0}])
        draw(t, 6, cb11=mat34(0, (6, 0, 0)), ps_textures=[{**texture(t, 46, w=256, h=256, write_dds=False), 'slot': 0}])
        draw(t, 7, cb11=mat34(0, (7, 0, 0)), ps_textures=['junk', {'slot': '0', 'id': 41}, {'slot': 0, 'id': 999},
                                                         {'slot': 1, 'id': 'x'}])  # malformed entries ignored
        s, _, table, _ = expect_ok(candidate, t, work, 'texture-bearing frame')
        assert s['textures'] == 3, s
        got = {row[0]: row[4] for row in table}
        assert got == {0: 0, 1: 40, 2: 40, 3: 43, 4: 41, 5: 0, 6: 0, 7: 0}, f'albedo picks {got}'
        checks.append('v3: albedo = largest sRGB texture, slot tie-break, linear-only/missing-DDS/malformed -> 0')
        # Skinning is the one transform with no independent check: hand-computed, not from the reference.
        # draw 4 of the synthetic frame is skinned, weights 128/255 to bone 0 (translate z+3) and 127/255 to
        # bone 1 (rotate 45 deg, translate x+2); vertex 0 is the origin, so its world position is that blend.
        skin_row = next(r[1] for r in syn_table if r[0] == 4)  # first triangle of draw_0004
        assert np.allclose(syn_tris[skin_row, 0:3], (254 / 255, 0.0, 384 / 255), atol=1e-6), \
            f'skinned vertex 0: {syn_tris[skin_row, 0:3]}'
        checks.append('skinned vertex 0 matches a hand-computed bone blend')
        # A texture id outside uint32 must not reach struct.pack: the draw keeps no albedo instead.
        big = work / 'frame_bigtex'
        big.mkdir()
        draw(big, 0, cb11=mat34(0, (0, 0, 0)), ps_textures=[{'slot': 0, 'id': 2 ** 32}])
        (big / 'textures').mkdir()
        (big / 'textures/index.json').write_text(json.dumps([{'id': 2 ** 32, 'format': 72, 'width': 8, 'height': 8}]))
        (big / 'textures' / f'tex_{2 ** 32}.dds').write_bytes(b'DDS ' + bytes(60))
        s = expect_ok(candidate, big, work, 'texture id past uint32')[0]
        assert s['textures'] == 0, s
        checks.append('texture id past uint32 -> no albedo, no traceback')
        # Re-running into the same output path must replace the texture set, never append to it.
        first, second = work / 'frame_stale_a', work / 'frame_stale_b'
        first.mkdir()
        draw(first, 0, cb11=mat34(0, (0, 0, 0)),
             ps_textures=[{**texture(first, 60, w=32, h=32), 'slot': 0}, {**texture(first, 61, w=32, h=32), 'slot': 1}])
        expect_ok(candidate, first, work, 'stale frame a')
        second.mkdir()
        draw(second, 0, cb11=mat34(0, (0, 0, 0)), ps_textures=[{**texture(second, 62, w=32, h=32), 'slot': 0}])
        p2 = subprocess.run([sys.executable, str(candidate), str(second), str(work / 'scene.bin')],
                            capture_output=True, text=True, timeout=900)
        assert p2.returncode == 0, f'stale frame b: exit {p2.returncode}: {p2.stderr[-300:]}'
        left = sorted(q.name for q in (work / 'scene_textures').iterdir())
        assert left == ['tex_62.dds'], f'stale textures survived a re-run: {left}'
        checks.append('re-run replaces the texture dir instead of merging into it')
        # A detail/mask atlas is mostly black and must not become an albedo, or the surface renders black.
        # Its negative twin (a bright atlas of the same shape and format) must still be used.
        mk = work / 'frame_mask'
        mk.mkdir()
        tdir = mk / 'textures'
        tdir.mkdir()
        def dds(fmt, payload):  # 4 magic + 124 header (DX10 fourcc at 84) + 20 DX10 header = payload at 148
            return b'DDS ' + bytes(80) + b'DX10' + bytes(40) + struct.pack('<I', fmt) + bytes(16) + payload
        (tdir / 'index.json').write_text(json.dumps([
            {'id': 70, 'format': 72, 'width': 32, 'height': 32},   # black BC1 atlas -> mask
            {'id': 71, 'format': 72, 'width': 32, 'height': 32}]))  # white BC1 atlas -> diffuse
        blocks = 64  # 32x32 in 4x4 blocks
        (tdir / 'tex_70.dds').write_bytes(dds(72, struct.pack('<II', 0, 0) * blocks))
        (tdir / 'tex_71.dds').write_bytes(dds(72, struct.pack('<II', 0xFFFF, 0xFFFF) * blocks))
        draw(mk, 0, cb11=mat34(0, (0, 0, 0)), ps_textures=[{'slot': 0, 'id': 70}])
        draw(mk, 1, cb11=mat34(0, (1, 0, 0)), ps_textures=[{'slot': 0, 'id': 71}])
        s, _, mask_table, _ = expect_ok(candidate, mk, work, 'mask frame')
        picked = {row[0]: row[4] for row in mask_table}
        assert picked == {0: 0, 1: 71}, f'mask atlas not rejected / bright atlas lost: {picked}'
        assert s['textures'] == 1, s
        checks.append('mostly-black mask atlas rejected, bright atlas kept')
        # A near-empty atlas must not consume the whole draw: the next candidate is a usable diffuse.
        fb = work / 'frame_fallback'
        fb.mkdir()
        (fb / 'textures').mkdir()
        (fb / 'textures' / 'index.json').write_text(json.dumps([
            {'id': 72, 'format': 72, 'width': 32, 'height': 32},    # larger, black -> skip
            {'id': 73, 'format': 72, 'width': 16, 'height': 16}]))  # smaller, bright -> chosen
        (fb / 'textures' / 'tex_72.dds').write_bytes(
            b'DDS ' + bytes(80) + b'DX10' + bytes(40) + struct.pack('<I', 72) + bytes(16) + struct.pack('<II', 0, 0) * 64)
        (fb / 'textures' / 'tex_73.dds').write_bytes(
            b'DDS ' + bytes(80) + b'DX10' + bytes(40) + struct.pack('<I', 72) + bytes(16) + struct.pack('<II', 0xFFFF, 0xFFFF) * 16)
        draw(fb, 0, cb11=mat34(0, (0, 0, 0)), ps_textures=[{'slot': 0, 'id': 72}, {'slot': 1, 'id': 73}])
        _, _, fb_table, _ = expect_ok(candidate, fb, work, 'fallback frame')
        assert fb_table[0][4] == 73, f'albedo did not fall through to a usable candidate: {fb_table}'
        checks.append('near-empty atlas falls through to the next candidate')
        # The dome light is dead without a colour texture, so every scene ships a 1x1 lat-long DDS beside it.
        sky = work / 'scene_sky.dds'
        assert sky.read_bytes()[:4] == b'DDS ', 'missing scene_sky.dds'
        raw = sky.read_bytes()
        assert raw[:4] == b'DDS ' and raw[84:88] == b'DX10', 'sky dds missing DDS/DX10 header'
        size, mips = struct.unpack_from('<I', raw, 16)[0], struct.unpack_from('<I', raw, 28)[0]
        assert size == 8 and mips == 4, f'sky dds is {size}x{size} with {mips} mips, want 8x8 with 4'
        assert struct.unpack_from('<I', raw, 128)[0] == 28, 'sky dds is not R8G8B8A8_UNORM'
        assert struct.unpack_from('<I', raw, 140)[0] == 1, 'sky dds must be one array slice (2D, never a cubemap)'
        assert len(raw) == 148 + sum(4 * (size * size >> (2 * i)) for i in range(mips)), 'sky dds payload size'
        assert set(raw[148:]) == {0xFF}, 'sky mips are not opaque white'
        checks.append('scene_sky.dds is an 8x8 mip-chained RGBA8 lat-long DDS')
        # An unusable output path is a clean exit 2, not a traceback.
        p3 = subprocess.run([sys.executable, str(candidate), str(second), str(work / 'missing-dir' / 'scene.bin')],
                            capture_output=True, text=True, timeout=900)
        assert p3.returncode == 2 and 'Traceback' not in p3.stderr, (p3.returncode, p3.stderr[-400:])
        checks.append('unusable output path -> exit 2 without a traceback')
        s = expect_ok(candidate, REAL, work, 'real NieR frame_7991289')[0]
        assert s['kept'] >= 60 and s['triangles'] > 100000 and s['textures'] == 0, s
        checks.append(f'real frame (depth pass only, no textures): {s}')
        if FULL.exists():
            s, _, table, tris = expect_ok(candidate, FULL, work, 'real NieR frame_9443695 (full frame)')
            v = tris.reshape(-1, 3, 8)  # per vertex: position[3], normal[3], uv[2]
            face = np.cross(v[:, 2, :3] - v[:, 0, :3], v[:, 1, :3] - v[:, 0, :3])
            agree = np.mean(np.sum(face * v[:, 0, 3:6], axis=1) > 0)
            assert agree > 0.85, f'only {agree:.2f} of vertex normals agree with outward faces'
            checks.append(f'real full frame: {s}; normals agree with outward faces {agree:.3f}')
        textured = os.environ.get('SCENE_TEXTURED_FRAME')
        if textured:  # opt-in: a real F9 capture that has textures (too big to keep in the repo)
            s, _, table, _ = expect_ok(candidate, Path(textured), work, 'real textured frame')
            assert s['textures'] > 0 and all(row[4] for row in table), f'textured frame lost albedos: {s}'
            checks.append(f'real textured frame: {s}')
        print(json.dumps({'passed': True, 'checks': checks}, indent=2))
    except AssertionError as e:
        print(json.dumps({'passed': False, 'error': str(e), 'checks_passed': checks}, indent=2))
        sys.exit(1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
