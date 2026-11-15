#!/usr/bin/env python3
"""One-off: which captured shaders declare the water family's constants, and how are their draws blended?"""
import json, sys, glob
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, '/home/suraj/Projects/Nier-Automata-Rendering/analysis/checks')
import dump_shader_decls as D

ROOT = Path('/home/suraj/Projects/Nier-Automata-Rendering/analysis/runtime/laptop-play-20261114')
names = {}
for f in sorted((ROOT / 'shaders').glob('ps_*.dxbc')):
    data = f.read_bytes()
    try:
        cb, res = D.declarations(D.chunks(data)['RDEF'][0])
    except Exception as e:
        names[f.stem] = ('ERR:%s' % e, [], [])
        continue
    vars_ = [(v, o) for (_n, _s, vs) in cb for (v, o, _sz) in vs]
    names[f.stem] = ('ok', vars_, [(r[0], r[2]) for r in res if r[1] in ('texture', 'structured')])

KW = ('Water', 'Translucent', 'Refract', 'Wet', 'Aniso', 'Opacity', 'Cube', 'Eye', 'Hair', 'Glass', 'Foliage', 'Grass')

for frame in ['frame_67078468', 'frame_67279062']:
    per = defaultdict(lambda: {'n': 0, 'idx': 0, 'maxidx': 0, 'states': set(), 'vp': set()})
    for p in glob.glob(str(ROOT / frame / 'draw_*' / 'capture.json')):
        d = json.load(open(p))
        st = d['state']
        k = 'ps_%s' % d['ps_hash']
        e = per[k]
        e['n'] += 1
        e['idx'] += int(d['index_count'])
        e['maxidx'] = max(e['maxidx'], int(d['index_count']))
        e['states'].add((st.get('blend_enable'), st.get('src_blend'), st.get('dest_blend'), st.get('blend_op'),
                         st.get('depth_write'), st.get('dss_hash')))
        e['vp'].add((d['vp_width'], d['vp_height']))
    print('==', frame, len(per), 'shaders')
    rows = []
    for k, e in per.items():
        info = names.get(k)
        if not info or info[0] != 'ok':
            continue
        vars_ = [v for v, o in info[1]]
        hit = sorted({v for v in vars_ if any(w in v for w in KW)})
        if hit:
            rows.append((e['maxidx'], k, e['n'], e['idx'], hit, sorted(e['states'])[0], sorted(e['vp'])))
    for r in sorted(rows, reverse=True):
        print('%s n=%-3d idx=%-7d max=%-6d state=%s vp=%s\n   %s' % (r[1], r[2], r[3], r[0], r[5], r[6], ', '.join(r[4])))
