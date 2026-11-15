#!/usr/bin/env python3
"""A0 review regressions: reporting failures, replay launch failure, legacy fail-closed."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from test_game_run_safety import HERE, ROOT, load


def check():
    runner = load(ROOT / 'runtime/game-runs/game_run.py', 'runner_hidden')
    base = ROOT / 'runtime/a0-safety-hidden'
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        w = Path(tmp)
        real = w / 'saves'; real.mkdir(); (real / 'SlotData_0.dat').write_bytes(b'progress')
        prefix = w / 'prefix'
        (prefix / 'pfx/drive_c/users/steamuser/Documents').mkdir(parents=True)
        for label in ['../escape', r'..\escape', 'drive:escape']:
            with patch.object(runner, 'RUNS', w / 'labels'), patch.object(runner, 'SAVE', real), patch.object(runner, 'PREFIX', prefix), patch.object(runner.subprocess, 'Popen', side_effect=OSError('synthetic only')), patch.object(sys, 'argv', ['game_run.py', label, '--limit', '0']):
                try:
                    runner.main()
                except SystemExit as exc:
                    assert exc.code == 2
                except ValueError:
                    pass  # shared sanitizer refuses before any filesystem/process work
                else:
                    raise AssertionError('unsafe cross-platform run label accepted')
        for failure in ['cleanup', 'verify_save']:
            with patch.object(runner, 'RUNS', w / 'runs'), patch.object(runner, 'SAVE', real), patch.object(runner, 'PREFIX', prefix), patch.object(runner.subprocess, 'Popen', side_effect=OSError('no launch')), patch.object(runner, failure, side_effect=OSError('synthetic reporting error')), patch.object(sys, 'argv', ['game_run.py', failure, '--limit', '0']):
                assert runner.main() != 0
            summary = json.loads((w / 'runs' / failure / 'summary.json').read_text())
            assert summary['errors'], 'reporting failure absent from summary'
            assert (real / 'SlotData_0.dat').read_bytes() == b'progress'
        replay = load(ROOT / 'replay/run_replay.py', 'replay_hidden')
        out, dll = w / 'replay', w / 'dll'
        (out / 'bin').mkdir(parents=True); (dll / 'nier_render_fonts').mkdir(parents=True)
        for p in [out / 'bin/capture_replay.exe', out / 'bin/d3d11_dlaa.dll', dll / 'd3d11.dll']:
            p.write_bytes(b'fixture')
        def failed_replay(*args, **kwargs):
            (out / 'failed/shot-bad.raw').write_bytes(b'bad')
            raise OSError('synthetic replay launch failure')
        with patch.object(replay, 'OUT', out), patch.object(replay, 'DLL', dll), patch.object(replay, 'build'), patch.object(replay.pack_capture, 'pack', return_value={'scene_size': (10, 10)}), patch.object(replay.subprocess, 'Popen', side_effect=failed_replay), patch.object(sys, 'argv', ['run_replay.py', 'failed', 'unused-frame', '--mode', 'fake']):
            assert replay.main() != 0
        summary = json.loads((out / 'failed/summary.json').read_text())
        assert summary['exit'] == 'launch-failed' and len(summary['errors']) == 2
        assert (out / 'failed/shot-bad.raw').read_bytes() == b'bad', 'malformed raw evidence lost'
        # Legacy ignored launcher must not ignore guard failure and reach a real command.
        legacy = ROOT / 'runtime/game-runs/g2-drive.sh'
        if legacy.exists():
            text = legacy.read_text()
            assert 'legacy launcher disabled' in text or 'guard.sh" before || exit' in text, 'legacy launcher fails open on guard error'


if __name__ == '__main__':
    try:
        check()
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
