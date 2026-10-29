#!/usr/bin/env python3
"""Convert a whole-frame D3D11 capture directory into a world-space NSCN scene binary (v3)."""
import hashlib
import json
import math
import os
import shutil
import struct
import sys
from collections import Counter
from pathlib import Path

import numpy as np

MAX_INDEX_COUNT = 1 << 24  # per draw; NieR's largest seen is 705K. Bounds memory on hostile captures.
MAX_INSTANCES = 4096
NAME_BYTES = 32  # fixed DDS file name field in the texture table
# DXGI *_UNORM_SRGB formats: the game's diffuse maps are stored sRGB, its masks/normals linear.
SRGB_FORMATS = {72, 75, 78, 90, 91}


class Reject(Exception):
    pass


ERR = (Reject, KeyError, OSError, ValueError, TypeError, IndexError, OverflowError)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_indices(d, c):
    size = {57: 2, 42: 4}.get(c.get('ib_format'))
    if c.get('has_index') != 1 or size is None or not 0 <= c['index_count'] <= MAX_INDEX_COUNT:
        raise Reject('index')
    if not -(2 ** 32) <= c['base_vertex'] < 2 ** 32:  # bounds the int64 product below
        raise Reject('base_vertex')
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


def normals(d, c, e, ids):  # NORMAL: 10 = float16 x4 (first 3), 2/6 = float32 x3+
    if e['format'] == 10:
        return element_bytes(d, c, e, ids, 6).copy().view('<f2').reshape(-1, 3).astype(np.float64)
    return element_bytes(d, c, e, ids, 12).copy().view('<f4').reshape(-1, 3).astype(np.float64)


def texcoords(d, c, e, ids):  # TEXCOORD: 34 = float16 x2, 16 = float32 x2
    if e['format'] == 34:
        return element_bytes(d, c, e, ids, 4).copy().view('<f2').reshape(-1, 2).astype(np.float64)
    return element_bytes(d, c, e, ids, 8).copy().view('<f4').reshape(-1, 2).astype(np.float64)


def mats(cb11, count):
    return np.frombuffer(cb11, dtype='<f4', count=count * 12).astype(np.float64).reshape(count, 3, 4)


def tex_index(frame):
    """textures/index.json -> {id: entry}; a missing or malformed index means no textures."""
    try:
        raw = json.loads((frame / 'textures' / 'index.json').read_text())
    except ERR:
        return {}
    if not isinstance(raw, list):
        return {}
    return {t['id']: t for t in raw if isinstance(t, dict) and type(t.get('id')) is int
            and 0 <= t['id'] < 2 ** 32  # the table field is uint32; anything else would fail to pack
            and type(t.get('format')) is int and type(t.get('width')) is int and type(t.get('height')) is int}


def albedo(c, index, frame):
    """Id of the draw's diffuse map: the largest-area sRGB texture bound to the pixel shader, lowest slot on
    a tie (strictly greater keeps the first of two equal entries). 0 when the draw has none or its DDS was
    not written."""
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
        if dds.is_file() and not mostly_black(dds):  # fall through to the next candidate, do not give up
            return tid
    return 0  # nothing usable: leave the surface on its constant albedo instead of painting it black


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


def sky_dds(level=255, size=8):
    """A small uniform-grey DDS for the dome light: a sky colour with no sky geometry.

    The runtime uploads asset textures as VK_IMAGE_TYPE_2D and samples them lat-long, so this must be a plain
    2D image, never a cubemap. A 1x1 texture crashes the runtime (integer divide by zero inside Present), and a
    full mip chain avoids the "suboptimal replacement texture" warning, so this writes 8x8 down to 1x1.
    The dome light multiplies its radiance by this texel.
    """
    mips = []
    n = size
    while n >= 1:
        mips.append(bytes((level, level, level, 255)) * (n * n))
        n //= 2
    h = bytearray(124)
    struct.pack_into('<7I', h, 0, 124, 0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | 0x20000, size, size, 4 * size, 0, len(mips))
    struct.pack_into('<2I', h, 72, 32, 0x4)      # DDS_PIXELFORMAT size, DDPF_FOURCC (required to recognise DX10)
    h[80:84] = b'DX10'                            # dwFourCC: DX10 header follows the 124-byte header
    struct.pack_into('<I', h, 104, 0x1000 | 0x8 | 0x400000)  # TEXTURE | COMPLEX | MIPMAP
    dx10 = struct.pack('<5I', 28, 3, 0, 1, 0)     # DXGI_FORMAT_R8G8B8A8_UNORM, TEXTURE2D, 1 array slice
    return b'DDS ' + bytes(h) + dx10 + b''.join(mips)


def first(layout, semantic, formats):
    """First element (layout order) with this semantic; None unless its format is one we decode."""
    for e in layout:
        if e['semantic'] == semantic:
            return e if e['format'] in formats else None
    return None


def score(c):
    """Duplicate draws (same geometry + transform in several passes): keep the one with the most attributes."""
    lay = c['layout']
    return (first(lay, 'NORMAL', (2, 6, 10)) is not None, first(lay, 'TEXCOORD', (16, 34)) is not None, len(lay))


def world_attrs(d, c, ids):
    """-> (list of (world positions, world normals or None) per instance, uv shared, skinned)."""
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


def sky_dds_hdr(width=128, height=64, zenith=(0.05, 0.09, 0.22), horizon=(0.72, 0.80, 0.96)):
    """Equirectangular RGBA16F sky for the dome light: a zenith->horizon gradient instead of one grey texel.

    Same DDS/DX10 framing as sky_dds (plain 2D, full mip chain, never a cubemap); only the DXGI format and the
    per-texel packing differ. Opt-in via REPROBE_SKY_HDR=1, because attaching any dome texture is the path that
    crashed the runtime with an integer divide by zero - this variant exists to test whether that is about the
    texture's size/format rather than the textured-dome path itself.
    """
    mips, w, h = [], width, height
    while True:
        t = np.linspace(0.0, 1.0, h)[:, None]  # 0 at the zenith row, 1 at the nadir row
        col = np.array(zenith, dtype=np.float64) * (1.0 - t) + np.array(horizon, dtype=np.float64) * t
        px = np.empty((h, w, 4), dtype='<f2')  # half floats: this format can carry radiance above 1.0
        px[..., :3] = col[:, None, :]
        px[..., 3] = 1.0
        mips.append(px.tobytes())
        if w == 1 and h == 1:
            break
        w, h = max(w >> 1, 1), max(h >> 1, 1)
    hd = bytearray(124)
    struct.pack_into('<7I', hd, 0, 124, 0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | 0x20000, height, width, 8 * width, 0, len(mips))
    struct.pack_into('<2I', hd, 72, 32, 0x4)     # DDS_PIXELFORMAT size, DDPF_FOURCC
    hd[80:84] = b'DX10'                            # dwFourCC: DX10 header follows the 124-byte header
    struct.pack_into('<I', hd, 104, 0x1000 | 0x8 | 0x400000)  # TEXTURE | COMPLEX | MIPMAP
    dx10 = struct.pack('<5I', 10, 3, 0, 1, 0)      # DXGI_FORMAT_R16G16B16A16_FLOAT, TEXTURE2D, 1 array slice
    return b'DDS ' + bytes(hd) + dx10 + b''.join(mips)


def build(frame, cutout_ids=frozenset()):
    index = tex_index(frame)
    # draw_<digits> fitting the uint32 table field; other folder names are ignored entirely.
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
        except ERR:
            stats['rejected'] += 1
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(d)
    table, tris, first_kept = [], [], None
    for key in order:
        # richest first (score descending), draw name breaks ties; a failed decode falls back to the next
        try:  # score() reaches into the layout: a malformed entry rejects these draws, not the whole frame
            cands = sorted(groups[key], key=lambda d: tuple(-int(x) for x in score(metas[d])) + (d.name,))
        except ERR:
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
            except ERR:
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
                fits = np.isfinite(v.astype(np.float32)).all(axis=(1, 2))  # the file stores float32
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
                tris.append(np.concatenate([v, vn, t], axis=2).reshape(-1, 24))
            # Bit 1 of the `skinned` field carries the cutout flag: bit 0 is the only bit the probe has ever
            # read (and today it reads neither), so the scene format stays v3 and every existing fixture and
            # capture converts byte-identically when no discard list is supplied.
            cutout = 2 if c.get('ps_hash') in cutout_ids else 0
            table.append((int(d.name[5:]), start, sum(len(x) for x in tris) - start, int(skinned) | cutout,
                          albedo(c, index, frame)))
            stats['kept'] += 1
            break
    if first_kept is None:
        raise Reject('no usable draws')
    allt = np.concatenate(tris) if tris else np.zeros((0, 24))
    return camera(first_kept), table, allt, main, stats


def load_discard(path):
    """Read a discard list and return the set of ps_hash ids whose pixel shader contains a discard.

    Accepts the verbatim stdout of analysis/checks/dxbc_disasm.cpp (`DISCARD ps_<id> 1`) or a plain
    `ps_<id> <0|1>` file, so the list can be produced offline and shipped next to the converter. Absence is
    not an error: a capture taken before shader capture existed simply gets no cutouts.
    """
    ids = set()
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == 'DISCARD':
            name, flag = parts[1], parts[2]
        elif len(parts) == 2:
            name, flag = parts
        else:
            continue
        if flag != '1' or not name.startswith('ps_'):
            continue
        digits = name[3:]
        if not digits.isdigit():  # rejects ps_-3, ps_0x10 and the like
            continue
        ids.add(int(digits))
    return frozenset(ids)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    discard_path = None
    if '--discard-file' in sys.argv:
        discard_path = sys.argv[sys.argv.index('--discard-file') + 1]
        args = [a for a in args if a != discard_path]
    if len(args) != 2:
        print('usage: scene_from_frame.py <frame_dir> <out_scene.bin> [--discard-file <list>]', file=sys.stderr)
        sys.exit(2)
    frame, out = Path(args[0]), Path(args[1])
    try:
        if not frame.is_dir():
            raise Reject('missing frame dir')
        cutout_ids = load_discard(discard_path) if discard_path else frozenset()
        cam, table, allt, main, stats = build(frame, cutout_ids)
    except Exception as e:
        print(f'error: {e}', file=sys.stderr)
        sys.exit(2)
    tex = sorted({row[4] for row in table if row[4]})
    blob = bytearray()
    blob += b'NSCN' + struct.pack('<4I', 3, len(table), len(allt), len(tex))
    blob += struct.pack('<14f', *[float(x) for x in cam])
    for row in table:
        blob += struct.pack('<5I', *row)
    for tid in tex:  # the probe resolves these names inside <out>_textures/
        name = f'tex_{tid}.dds'.encode()
        blob += struct.pack('<I', tid) + name.ljust(NAME_BYTES, b'\0')
    if allt.size:
        blob += np.ascontiguousarray(allt, dtype='<f4').tobytes()
    # Textures go into a fresh directory that then replaces the old one, so a re-run never merges stale files
    # and a failed copy never leaves a scene.bin pointing at textures that are not there.
    dest = out.parent / (out.stem + '_textures')
    tmp = out.parent / (out.stem + '_textures.tmp')
    try:
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        for tid in tex:
            (tmp / f'tex_{tid}.dds').write_bytes((frame / 'textures' / f'tex_{tid}.dds').read_bytes())
        if dest.is_dir():
            shutil.rmtree(dest)
        elif dest.exists():
            dest.unlink()
        tmp.rename(dest)
        out.write_bytes(bytes(blob))
        (out.parent / 'scene_sky.dds').write_bytes(
            sky_dds_hdr() if os.environ.get('REPROBE_SKY_HDR') == '1' else sky_dds())  # dome light points here
        # The capture's light arrays (point t20, spot t22), passed through unchanged: the probe converts them with
        # checks/light_convert.h, the same code the live path uses. NLIT v1: per array u32 stride, first, count, nbytes.
        lights_out = out.parent / 'scene_lights.bin'
        if (frame / 'lights.json').exists():
            lj = json.loads((frame / 'lights.json').read_text())
            blob_l = bytearray(b'NLIT' + struct.pack('<I', 1))
            for key, name in (('t20', 'lights_t20.bin'), ('t22', 'lights_t22.bin')):
                a = lj.get(key, {})
                data = (frame / name).read_bytes() if (frame / name).exists() else b''
                blob_l += struct.pack('<4I', a.get('stride', 0), a.get('first', 0), a.get('count', 0), len(data)) + data
            lights_out.write_bytes(bytes(blob_l))
        elif lights_out.exists():
            lights_out.unlink()  # never light a scene with another capture's lights
    except OSError as e:
        print(f'error: {e}', file=sys.stderr)
        sys.exit(2)
    summary = {'kept': stats['kept'], 'duplicates': stats['duplicates'], 'rejected': stats['rejected'],
               'other_viewport': stats['other_viewport'], 'triangles': len(allt),
               'main_viewport': list(main), 'textures': len(tex)}
    if cutout_ids:  # only present when a discard list was supplied, so default output stays unchanged
        summary['cutout_draws'] = sum(1 for row in table if row[3] & 2)
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
