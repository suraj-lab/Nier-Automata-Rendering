#!/usr/bin/env python3
"""Read-only E1/W4 evidence census; keyword candidates are not accepted material classes."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

A = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(A / 'checks'))
import dump_shader_decls as parser


def main():
    roots = {'camp': Path('/mnt/second/SteamLibrary/steamapps/common/NieRAutomata/NIER_CAPTURE/frame_30632051'),
             'desert': A / 'runtime/laptop-play-20261114/frame_67279062',
             'pond': A / 'runtime/laptop-play-20261114/frame_67078468'}
    result = {}
    for area, root in roots.items():
        if not root.is_dir():
            result[area] = {'waiting': 'capture unavailable'}
            continue
        counts, shader_draws, declarations = Counter(), Counter(), {}
        for draw in sorted(root.glob('draw_*')):
            j = json.loads((draw / 'capture.json').read_text())
            state = j['state']
            counts['recorded_draws'] += 1
            counts[f'blend={state["blend_enable"]},src={state["src_blend"]},dst={state["dest_blend"]},op={state["blend_op"]},depthwrite={state["depth_write"]}'] += 1
            shader_draws[str(j['ps_hash'])] += 1
        metadata = json.loads((root / 'frame.json').read_text())
        assert counts['recorded_draws'] == metadata['written'], f'{area}: incomplete draw metadata'
        for shader in shader_draws:
            path = root.parent / 'shaders' / f'ps_{shader}.dxbc'
            if not path.exists():
                declarations[shader] = {'missing_bytecode': True}
                continue
            data = path.read_bytes()
            chunks = parser.chunks(data)
            if 'RDEF' not in chunks:
                declarations[shader] = {'missing_rdef': True}
                continue
            cbs, resources = parser.declarations(chunks['RDEF'][0])
            matches = {kind: [(cb, name, offset, size) for cb, _, variables in cbs for name, offset, size in variables if re.search(pattern, name, re.I)]
                       for kind, pattern in [('emission', r'emiss|emission|lumin|glow'), ('water_effect', r'water|refract|transluc|uvanim'),
                                             ('hair', r'aniso|secondaryspec'), ('sky', r'sky|cloud')]}
            declarations[shader] = {'sha256': hashlib.sha256(data).hexdigest(), 'draws': shader_draws[shader],
                                    'keyword_candidates': matches, 'structured_resources': [r for r in resources if r[1] in ['structured', 'byteaddress', 'tbuffer']]}
        result[area] = {'capture': str(root), 'capture_metadata': metadata, 'draw_state_census': dict(counts), 'shaders': declarations,
                        'limitations': 'Keyword matches only; no photometric emission/class identification. Legacy data omits small draws and blend-alpha/view-format/target-size evidence. Duplicate RDEF names must not be joined to binding slots by name alone.'}
        print(area, 'draws', counts['recorded_draws'], 'emission-keyword shaders', sum(bool(s.get('keyword_candidates', {}).get('emission')) for s in declarations.values()),
              'water/effect-keyword shaders', sum(bool(s.get('keyword_candidates', {}).get('water_effect')) for s in declarations.values()),
              'missing shaders', sum(bool(s.get('missing_bytecode')) for s in declarations.values()))
    out = A / 'runtime/a0-shader-audit/candidate-inventory.json'
    with out.open('x') as f:
        json.dump(result, f, indent=2)
        f.write('\n')


if __name__ == '__main__':
    main()
