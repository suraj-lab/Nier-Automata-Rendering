#!/usr/bin/env python3
"""W5 step 1 evidence: hair candidates by corrected bytecode declarations plus draw state.

Read-only. Does not implement anisotropy: runtime support and tangent basis must be verified in a live
build first (plan W5.2), so this reports candidates and keeps the feature off.
"""
import hashlib
import json
from pathlib import Path
import re
import sys

A = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(A / 'checks'))
import dump_shader_decls as parser

ROOTS = {'camp': Path('/mnt/second/SteamLibrary/steamapps/common/NieRAutomata/NIER_CAPTURE/frame_30632051'),
         'desert': A / 'runtime/laptop-play-20261114/frame_67279062',
         'pond': A / 'runtime/laptop-play-20261114/frame_67078468'}


def shader_vars(path):
    data = path.read_bytes()
    cbuffers, resources = parser.declarations(parser.chunks(data)['RDEF'][0])
    return data, cbuffers, resources


def main():
    report = {}
    for area, root in ROOTS.items():
        if not root.is_dir():
            report[area] = {'waiting': 'capture unavailable'}
            continue
        by_shader = {}
        for draw in sorted(root.glob('draw_*')):
            j = json.loads((draw / 'capture.json').read_text())
            by_shader.setdefault(str(j['ps_hash']), []).append((draw, j))
        candidates, unavailable = {}, []
        for shader, draws in by_shader.items():
            path = root.parent / 'shaders' / f'ps_{shader}.dxbc'
            if not path.exists():
                unavailable.append({'shader': shader, 'why': 'bytecode absent'})
                continue
            data, cbuffers, resources = shader_vars(path)
            # Name->register joins are ambiguous (duplicate RDEF names); use declaration text only.
            names = {v for _, _, vs in cbuffers for v, _, _ in vs}
            if not any(re.search(r'aniso', v, re.I) for v in names):
                continue
            aniso = sorted(n for n in names if re.search(r'aniso', n, re.I))
            states = []
            for draw, j in draws:
                s = j['state']
                states.append({'draw': draw.name, 'index_count': j['index_count'],
                               'blend': [s['blend_enable'], s['src_blend'], s['dest_blend'], s['blend_op']],
                               'depth_write': s['depth_write'], 'viewport': [j['vp_width'], j['vp_height']],
                               'ps_textures': j['ps_textures']})
            tex_inputs = sorted({r[0] for r in resources if r[1] in ('texture', 'sampler')})
            candidates[shader] = {
                'shader_file': path.name, 'shader_sha256': hashlib.sha256(data).hexdigest(),
                'draws': len(draws), 'anisotropy_declarations': aniso,
                'secondary_spec': sorted(n for n in names if re.search(r'secondar', n, re.I)),
                'texture_inputs': tex_inputs, 'draw_state': states,
                'tangent_declared': any(r[0].lower().startswith('g_texture') and 'normal' in r[0].lower() for r in resources),
            }
        total = sum(c['draws'] for c in candidates.values())
        report[area] = {'capture': str(root), 'hair_candidate_shaders': candidates, 'candidate_draws': total,
                        'missing_bytecode': unavailable,
                        'limitations': ['Keyword declaration match only: scalp, lashes and alpha cards are not yet separated.',
                                        'Tangent basis and runtime anisotropy behavior are unverified; no anisotropy value was sent.',
                                        'State metadata cannot show whether a draw is hidden by a later pass (hide-draw check pending).']}
        print(area, 'candidates', len(candidates), 'draws', total, 'missing bytecode', len(unavailable))
    out = A / 'runtime/a0-shader-audit/hair-candidates.json'
    with out.open('x') as f:
        json.dump(report, f, indent=2)
        f.write('\n')


if __name__ == '__main__':
    main()
