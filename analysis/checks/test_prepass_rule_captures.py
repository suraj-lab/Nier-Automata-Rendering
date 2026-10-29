#!/usr/bin/env python3
"""Data gate: the pre-pass rule in live_capture.h holds on every real F9 capture we have.

Rule (live_capture.h, observe): a draw into the scene target whose input layout has none of TEXCOORD, NORMAL, TANGENT,
COLOR is NieR's depth pre-pass and is not submitted. That is only safe if every such draw has a full-layout twin
(same index/vertex bytes, offsets and counts) in the same frame, so dropping it never removes an object. This gate
checks exactly that on the captures in NIER_CAPTURE, and that the rule matches a meaningful share (the pre-pass exists).
Skips (passes with a note) when no capture is on this machine. Native Python only.
"""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

CAPTURES = Path('/mnt/second/SteamLibrary/steamapps/common/NieRAutomata/NIER_CAPTURE')
SURFACE = {'TEXCOORD', 'NORMAL', 'TANGENT', 'COLOR'}  # must match kSurfaceSemantics in live_capture.h


def digest(path):
    return hashlib.md5(path.read_bytes()).hexdigest() if path.exists() else None


def main():
    frames = sorted(p for p in CAPTURES.glob('frame_*') if p.is_dir()) if CAPTURES.exists() else []
    if not frames:
        print(json.dumps({'passed': True, 'note': f'no captures under {CAPTURES}; nothing to check'}))
        return
    report = {}
    for frame in frames:
        draws = []
        for folder in frame.glob('draw_*'):
            try:
                meta = json.loads((folder / 'capture.json').read_text())
            except (OSError, ValueError):
                continue
            draws.append((folder, meta))
        sizes = Counter((m['vp_width'], m['vp_height']) for _, m in draws)
        final = max(sizes, key=lambda s: s[0] * s[1])
        # The scene viewport: largest one with the final image's aspect that is smaller than it (the A1 rule).
        scene = max((s for s in sizes if s[0] < final[0] and abs(s[0] * final[1] - s[1] * final[0]) <= 0.01 * s[1] * final[0]),
                    key=lambda s: s[0] * s[1], default=None)
        if scene is None:
            continue

        def key(folder, m):
            return (digest(folder / 'ib.bin'), m['ib_offset'], m['start_index'], m['index_count'], m['base_vertex'],
                    digest(folder / 'vb_0.bin'))
        in_scene = [(f, m) for f, m in draws if (m['vp_width'], m['vp_height']) == scene]
        full = {key(f, m) for f, m in in_scene if {e['semantic'] for e in m['layout']} & SURFACE}
        prepass = [(f, m) for f, m in in_scene if not {e['semantic'] for e in m['layout']} & SURFACE]
        orphans = [f.name for f, m in prepass if key(f, m) not in full]
        report[frame.name] = {'scene_draws': len(in_scene), 'prepass': len(prepass), 'orphans': orphans[:5]}
        assert not orphans, f'{frame.name}: {len(orphans)} non-surface draws have no full twin, e.g. {orphans[:3]}'
        assert len(prepass) >= 0.2 * len(in_scene), f'{frame.name}: pre-pass share {len(prepass)}/{len(in_scene)} unexpectedly low'
    print(json.dumps({'passed': True, 'frames': report}, indent=1))


if __name__ == '__main__':
    try:
        main()
    except AssertionError as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
