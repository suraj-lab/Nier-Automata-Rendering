#!/usr/bin/env python3
"""Frozen gate for replay/pair_metrics.py (W2 region comparison).

Proves: hand-computed per-region statistics, exclusion masks, strict pair validation, and agreement with the
existing frame_tools whole-frame numbers. Run: python3 checks/test_pair_metrics.py [candidate.py]
"""
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
A = HERE.parent


def load(path):
    spec = importlib.util.spec_from_file_location('pair_metrics_candidate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, array):
    Image.fromarray(np.asarray(array, dtype=np.uint8), 'RGB').save(path)


def check(candidate):
    import tempfile
    with tempfile.TemporaryDirectory(dir=HERE.parent / 'runtime') as tmp:
        tmp = Path(tmp)
        # 4x4 image: left half black, right half white; one red corner pixel for saturation.
        img = np.zeros((4, 4, 3), dtype=np.uint8)
        img[:, 2:] = 255
        img[0, 0] = (255, 0, 0)
        a, b = tmp / 'a.png', tmp / 'b.png'
        write(a, img)
        write(b, img)
        spec = {'regions': {'left': [0.0, 0.0, 0.5, 1.0], 'right': [0.5, 0.0, 1.0, 1.0]}}
        out = candidate.compare(a, b, spec)
        left, right = out['regions']['left'], out['regions']['right']
        # Hand computed: left column pair = 2 columns x 4 rows = 8 px, one of them red.
        assert abs(left['original']['median'] - 0.0) < 1e-9, left['original']
        assert abs(right['original']['median'] - 1.0) < 1e-9, right['original']
        assert left['original']['crush_pct'] == 87.5, left['original']  # 7 of 8 px are black; the red one is not
        assert right['original']['clip_pct'] == 100.0, right['original']
        # saturation of pure white/black is 0; the single red pixel is inside the left region only
        assert abs(right['original']['saturation']) < 1e-9
        assert left['original']['saturation'] > 0.0
        assert out['identical'] is True and abs(out['frame_delta']) < 1e-9

        # Exclusion removes the red pixel from the left region without touching the right one.
        spec_ex = {'regions': spec['regions'], 'exclude': [[0.0, 0.0, 0.25, 0.25]]}
        out2 = candidate.compare(a, b, spec_ex)
        assert out2['regions']['left']['original']['saturation'] == 0.0, out2['regions']['left']['original']
        assert out2['excluded_pixels'] == 1, out2['excluded_pixels']
        assert abs(out2['regions']['right']['original']['median'] - 1.0) < 1e-9

        # Non-dyadic fractions on an awkward width: floor, round and ceil must give different answers here,
        # so the gate pins one convention instead of accepting whatever the candidate happens to do.
        odd = np.zeros((3, 7, 3), dtype=np.uint8)
        write(tmp / 'odd.png', odd)
        spec_odd = {'regions': {'mid': [0.5, 0.0, 1.0, 1.0], 'rows': [0.0, 0.5, 1.0, 1.0]}}
        out_odd = candidate.compare(tmp / 'odd.png', tmp / 'odd.png', spec_odd)
        # round(0.5*7)=4 and round(0.5*3)=2 (floor would give 3 and 1; ceil would give 4 and 2).
        assert out_odd['regions']['mid']['pixels'] == 3 * 3, out_odd['regions']['mid']['pixels']
        assert out_odd['regions']['rows']['pixels'] == 7 * 1, out_odd['regions']['rows']['pixels']

        # A pair of different sizes must be rejected, not resampled.
        write(tmp / 'small.png', np.zeros((2, 2, 3), dtype=np.uint8))
        try:
            candidate.compare(tmp / 'small.png', a, spec)
        except ValueError:
            pass
        else:
            raise AssertionError('mismatched frame sizes accepted')

        # Banker's rounding rounds DOWN at .5 here, so this separates round (4 -> 2 cols) from ceil (5 -> 1 col).
        even = np.zeros((2, 6, 3), dtype=np.uint8)
        write(tmp / 'even.png', even)
        out_even = candidate.compare(tmp / 'even.png', tmp / 'even.png', {'regions': {'edge': [0.75, 0.0, 1.0, 1.0]}})
        assert out_even['regions']['edge']['pixels'] == 2 * 2, out_even['regions']['edge']['pixels']

        # A non-identical pair pins identical=False and the 0..255 grey-level scale, and the exclusion must mask it.
        base = np.zeros((2, 2, 3), dtype=np.uint8)
        changed = base.copy()
        changed[0, 0] = 20  # exactly 20 grey levels on one pixel of four
        write(tmp / 'd0.png', base)
        write(tmp / 'd1.png', changed)
        out_diff = candidate.compare(tmp / 'd0.png', tmp / 'd1.png', {'regions': {'all': [0.0, 0.0, 1.0, 1.0]}})
        assert out_diff['identical'] is False
        assert abs(out_diff['frame_delta'] - 20 / 4) < 1e-6, out_diff['frame_delta']
        masked = candidate.compare(tmp / 'd0.png', tmp / 'd1.png',
                                  {'regions': {'all': [0.0, 0.0, 1.0, 1.0]}, 'exclude': [[0.0, 0.0, 0.5, 0.5]]})
        assert abs(masked['frame_delta']) < 1e-9, 'exclusion not applied to frame_delta: %r' % (masked['frame_delta'],)
        assert masked['regions']['all']['original']['median'] == 0.0

        # `exclude` that is present but not a sequence is a malformed spec, not "no exclusions".
        for bad_exclude in (0, '', False, None, 1.5, {}):
            try:
                candidate.compare(tmp / 'd0.png', tmp / 'd1.png', {'regions': {'all': [0, 0, 1, 1]}, 'exclude': bad_exclude})
            except ValueError:
                continue
            raise AssertionError('falsy/non-sequence exclude accepted: %r' % (bad_exclude,))

        # Malformed regions: inverted, out of range, unknown key.
        for bad in ({'regions': {'x': [0.5, 0.0, 0.2, 1.0]}},
                    {'regions': {'x': [0.0, 0.0, 1.5, 1.0]}},
                    {'regions': {'x': [0.0, 0.0]}},
                    {'regions': {}},
                    {'regions': {'all': [0, 0, 1, 1]}, 'exclude': [[0.9, 0.9, 0.1, 1.0]]}):
            try:
                candidate.compare(a, b, bad)
            except ValueError:
                continue
            raise AssertionError('malformed spec accepted: %r' % (bad,))

        # Independent cross-check against frame_tools on the real camp pair.
        sys.path.insert(0, str(A / 'replay'))
        import frame_tools
        remix = A / 'runtime/game-runs/t1-remix-clean/shots/shot-2.png'
        original = A / 'runtime/game-runs/t1-original-shortleft/shots/shot-2.png'
        checked = None
        if remix.exists() and original.exists():
            got = candidate.compare(original, remix, {'regions': {'all': [0.0, 0.0, 1.0, 1.0]}})
            reference = frame_tools.stats(original)
            for key in ['median', 'p95', 'clip_pct', 'crush_pct', 'saturation']:
                assert abs(got['regions']['all']['original'][key] - reference[key]) < 1e-9, \
                    f'{key}: {got["regions"]["all"]["original"][key]} vs frame_tools {reference[key]}'
            checked = {'median': reference['median'], 'crush_pct': reference['crush_pct']}
        return checked


if __name__ == '__main__':
    try:
        path = Path(sys.argv[1]) if len(sys.argv) > 1 else A / 'replay/pair_metrics.py'
        real = check(load(path))
        print(json.dumps({'passed': True, 'real_pair_check': real}))
    except (Exception, SystemExit) as exc:
        error = f'candidate exited early: {exc.code}' if isinstance(exc, SystemExit) else str(exc)
        print(json.dumps({'passed': False, 'error': error}))
        sys.exit(1)
