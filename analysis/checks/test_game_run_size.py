#!/usr/bin/env python3
"""Desktop display size must reach gamescope exactly, and junk sizes must be refused, not guessed."""
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location('runner_size', ROOT / 'runtime/game-runs/game_run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == '__main__':
    try:
        runner = load()
        build = getattr(runner, 'launch_command', None)
        assert build, 'no command builder exposed'
        cmd = build('3440x1440')
        joined = ' '.join(cmd)
        for expected in ['--backend headless', '-W 3440', '-H 1440', '-w 3440', '-h 1440']:
            assert expected in joined, 'missing ' + expected
        assert cmd[-2:] == ['run', './NieRAutomata.exe'], 'proton/game tail changed: ' + joined
        for bad in ['3440', '0x1440', '3440x', 'axb', '3440x1440x1', '-1x10']:
            try:
                build(bad)
            except ValueError:
                continue
            raise AssertionError('bad size accepted: ' + bad)
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
