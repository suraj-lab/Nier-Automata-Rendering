#!/usr/bin/env python3
"""Gate for the cutout flag: the converter's discard list and the bit the probe reads must agree.

The scene format stayed v3: the cutout flag rides in bit 1 of the `skinned` table field, because the probe
has never read bit 0 either. That decision only holds if both sides agree on the bit and if a missing or
stale discard list changes nothing -- which is what this gate pins.

Usage: test_scene_cutout.py <scene_from_frame.py>
Prints {"passed": true, "checks": [...]}.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

CUTOUT_BIT = 2  # bit 1 of the `skinned` field


def load_module(path):
    spec = importlib.util.spec_from_file_location('scene_from_frame', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    candidate = Path(sys.argv[1]).resolve()
    checks = []
    try:
        mod = load_module(candidate)

        # 1. The discard list is accepted in the shape dxbc_disasm prints, so its stdout can be used verbatim.
        parsed = mod.load_discard.__doc__ is not None  # docstring present: not a stub
        assert parsed, 'load_discard is missing its documented contract'
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / 'disasm.txt').write_text(
                'DISCARD ps_1234 1\nDISCARD ps_77 0\nOK examined=2 with_discard=1\n')
            ids = mod.load_discard(d / 'disasm.txt')
            assert ids == frozenset({1234}), f'dxbc_disasm format not parsed: {ids}'

            # 2. Plain two-column form works too, and a zero flag is not a cutout.
            (d / 'plain.txt').write_text('ps_5 1\nps_6 0\n')
            assert mod.load_discard(d / 'plain.txt') == frozenset({5}), 'plain form not parsed'

            # 3. Junk is ignored rather than crashing or producing bogus ids.
            (d / 'junk.txt').write_text('ps_x 1\nnonsense\nDISCARD ps_9 abc\nps_-3 1\n\n')
            assert mod.load_discard(d / 'junk.txt') == frozenset(), 'junk produced ids'
            checks.append('load_discard: dxbc_disasm form, plain form, and junk rejection')

            # 4. A stale list naming draws that are not in the capture changes nothing and does not fail.
            real = Path('/home/suraj/Projects/Nier-Automata-Rendering/analysis/runtime/remix-probe/captures/frame_9443695')
            if real.is_dir():
                (d / 'stale.txt').write_text('DISCARD ps_999999 1\n')
                out = d / 'scene.bin'
                r = subprocess.run([sys.executable, str(candidate), str(real), str(out),
                                    '--discard-file', str(d / 'stale.txt')],
                                   capture_output=True, text=True, timeout=1800)
                assert r.returncode == 0, f'stale discard list failed the converter: {r.stderr[-300:]}'
                summary = json.loads(r.stdout.strip().splitlines()[-1])
                assert summary.get('cutout_draws') == 0, f'stale list flagged draws: {summary}'
                assert out.exists() and out.stat().st_size > 1000, 'no scene written'
                # 5. And with no list at all the summary keeps its old shape, so existing callers and the
                #    byte-exact scene gate are unaffected.
                r2 = subprocess.run([sys.executable, str(candidate), str(real), str(d / 'scene2.bin')],
                                    capture_output=True, text=True, timeout=1800)
                assert r2.returncode == 0, r2.stderr[-300:]
                summary2 = json.loads(r2.stdout.strip().splitlines()[-1])
                assert 'cutout_draws' not in summary2, f'default summary gained a key: {summary2}'
                assert (d / 'scene2.bin').read_bytes() == out.read_bytes(), \
                    'a stale discard list changed the scene bytes'
                checks.append('a stale or absent discard list leaves the scene bytes identical')
            else:
                checks.append('real capture absent; stale-list case skipped')

        # 6. Both sides must agree on the bit. The probe tests `d.skinned & 2`; the converter writes 2.
        probe = candidate.parent / 'triangle.cpp'
        source = probe.read_text(errors='replace')
        assert 'd.skinned & 2u' in source, 'probe no longer tests bit 1 of skinned'
        assert CUTOUT_BIT == 2, 'gate constant drifted'
        assert 'cutout = 2 if' in candidate.read_text(errors='replace'), \
            'converter no longer writes 2 into the skinned field'
        checks.append('converter writes bit 1 and the probe reads bit 1')

        print(json.dumps({'passed': True, 'checks': checks}, indent=2))
    except AssertionError as e:
        print(json.dumps({'passed': False, 'error': str(e), 'checks_passed': checks}, indent=2))
        sys.exit(1)


if __name__ == '__main__':
    main()
