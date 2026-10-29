#!/usr/bin/env python3
"""Run the live path's own decoder (live_vertex_decode.h) over EVERY draw of an F9 capture and find stretched geometry.

Usage: python3 analysis/checks/scan_live_decode.py <NIER_CAPTURE/frame_N> [out.json]
For each draw: decode exactly like live_capture.h does, then apply what the live path gives Remix:
  static  -> CB11 row matrix of instance 0 (64-byte stride, translation in element 3 of each row);
  skinned -> bind-pose positions blended with the CB11 palette (48-byte stride per bone), 4 weights.
Metrics in local and in world space: extent, median and max triangle edge, NaN/Inf count. A draw is 'stretched' when
its longest edge is > 25x its median edge and > 5% of the frame's typical extent. Read-only; prints a summary grouped by
(skinned, layout). The harness is the one in test_live_vertex_decode.py, so the decoder under test is the shipped one.
"""
import json
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

C = Path(__file__).resolve().parent
sys.path.insert(0, str(C))
import test_live_vertex_decode as tlvd  # noqa: E402


def harness():
    work = Path(tempfile.mkdtemp(prefix='scan-'))
    (work / 'harness.cpp').write_text(tlvd.HARNESS)
    subprocess.run(['g++', '-std=c++17', '-O2', '-I', str(C), str(work / 'harness.cpp'), '-o', str(work / 'harness')],
                   check=True)
    return work / 'harness'


def edges(pos, idx):
    t = idx.reshape(-1, 3)
    a, b, c = pos[t[:, 0]], pos[t[:, 1]], pos[t[:, 2]]
    return np.concatenate([np.linalg.norm(a - b, axis=1), np.linalg.norm(b - c, axis=1), np.linalg.norm(c - a, axis=1)])


def stats(pos, idx):
    finite = np.isfinite(pos).all(axis=1)
    if not finite.all():
        return {'nonfinite': int((~finite).sum())}
    e = edges(pos, idx)
    ext = float((pos.max(0) - pos.min(0)).max()) if len(pos) else 0.0
    return {'extent': ext, 'median_edge': float(np.median(e)), 'max_edge': float(e.max()), 'nonfinite': 0}


def scan(binary, folder):
    meta = json.loads((folder / 'capture.json').read_text())
    sem = {e['semantic'] for e in meta['layout']}
    skinned = {'BLENDINDICES', 'BLENDWEIGHT'} <= sem
    width = 2 if meta['ib_format'] == 57 else 4
    cb11 = (folder / 'cb_11.bin').read_bytes() if (folder / 'cb_11.bin').exists() else b''
    bones = len(cb11) // 48
    layout = ' '.join(f"{e['semantic']}:{e['format']}@{e['offset']}/s{e.get('slot', 0)}" for e in meta['layout'])
    strides = ','.join(str(v['stride']) for v in sorted(meta['vertex_buffers'], key=lambda x: x['slot']))
    row = {'draw': folder.name, 'skinned': skinned, 'layout': layout, 'strides': strides, 'index_count': meta['index_count'],
           'instanced': meta.get('instanced', 0), 'cb11_bytes': len(cb11)}
    args = [str(binary)]
    for v in sorted(meta['vertex_buffers'], key=lambda x: x['slot']):
        args += [f"{v['slot']}:{v['stride']}:{v['offset']}", 'x', str(folder / f"vb_{v['slot']}.bin")]
    spec = ';'.join(f"{e['semantic']}:{e['format']}:{e['offset']}:{e.get('slot', 0)}:0" for e in meta['layout'])
    args += ['--', str(folder / 'ib.bin'), str(meta['ib_offset'] + meta['start_index'] * width), str(meta['index_count']),
             str(width), str(meta['base_vertex']), str(bones), '1' if skinned else '0', spec]
    run = subprocess.run(args, capture_output=True, text=True)
    if 'ok=1' not in run.stdout:
        row['decode'] = 'rejected'
        return row
    lines = run.stdout.splitlines()
    idx = np.array(next(l for l in lines if l.startswith('i ')).split()[1:], dtype=np.int64)
    pos = np.array([l.split()[1:4] for l in lines if l.startswith('v ')], dtype=np.float64)
    row['decode'] = 'ok'
    row['local'] = stats(pos, idx)
    if len(cb11) < 48:
        row['world'] = {'note': 'no CB11'}
        return row
    if skinned:
        bw = np.array([l.split()[1:9] for l in lines if l.startswith('b ')], dtype=np.float64)
        pal = np.frombuffer(cb11[:bones * 48], dtype='<f4').reshape(bones, 3, 4).astype(np.float64)
        hom = np.c_[pos, np.ones(len(pos))]
        world = np.zeros_like(pos)
        bad = 0
        for k in range(4):
            bi = bw[:, k].astype(np.int64)
            w = bw[:, 4 + k]
            inside = bi < bones
            bad += int(((w > 0) & ~inside).sum())
            bi = np.where(inside, bi, 0)
            world += w[:, None] * np.einsum('nij,nj->ni', pal[bi], hom)
        row['bad_bone_refs'] = bad
    else:
        m = np.frombuffer(cb11[:48], dtype='<f4').reshape(3, 4).astype(np.float64)
        world = np.c_[pos, np.ones(len(pos))] @ m.T
    row['world'] = stats(world, idx)
    return row


def main():
    frame = Path(sys.argv[1])
    out = Path(sys.argv[2]) if sys.argv[2:] else Path(tempfile.gettempdir()) / f'scan_{frame.name}.json'
    binary = harness()
    folders = sorted(p for p in frame.glob('draw_*') if (p / 'capture.json').exists())
    with ThreadPoolExecutor(16) as pool:
        rows = list(pool.map(lambda f: scan(binary, f), folders))
    out.write_text(json.dumps(rows, indent=1))

    ok = [r for r in rows if r.get('decode') == 'ok' and 'extent' in r.get('world', {})]
    typical = float(np.median([r['world']['extent'] for r in ok])) if ok else 0.0

    def stretched(s):
        return 'max_edge' in s and s['max_edge'] > 25 * max(s['median_edge'], 1e-9) and s['max_edge'] > 0.05 * typical
    for r in ok:
        r['stretched_local'] = stretched(r['local'])
        r['stretched_world'] = stretched(r['world'])
    print(f'draws {len(rows)}; decoded {sum(r.get("decode") == "ok" for r in rows)}; rejected '
          f'{sum(r.get("decode") == "rejected" for r in rows)}; typical world extent {typical:.2f}')
    print(f'nonfinite world: {sum(r.get("world", {}).get("nonfinite", 0) > 0 for r in rows)} draws; '
          f'bad bone refs: {sum(r.get("bad_bone_refs", 0) > 0 for r in rows)} draws')
    groups = defaultdict(Counter)
    for r in ok:
        key = ('skinned' if r['skinned'] else 'static', r['strides'], r['layout'])
        g = groups[key]
        g['draws'] += 1
        g['stretched_local'] += r['stretched_local']
        g['stretched_world'] += r['stretched_world']
    print('\nkind     strides  draws  stretched(local)  stretched(world)  layout')
    for key, g in sorted(groups.items(), key=lambda kv: -kv[1]['stretched_world']):
        print(f'{key[0]:<8} {key[1]:<8} {g["draws"]:>5}  {g["stretched_local"]:>16}  {g["stretched_world"]:>16}  {key[2]}')
    print(f'\nrows written to {out}')


if __name__ == '__main__':
    main()
