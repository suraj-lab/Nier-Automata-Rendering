#!/usr/bin/env python3
"""Cross-platform run label sanitizer: no separator or drive escape, no silent coercion of distinct labels."""
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check():
    for relative in ['runtime/game-runs/game_run.py', 'replay/run_replay.py']:
        module = load(ROOT / relative, 'sanitizer_' + Path(relative).stem)
        clean = getattr(module, 'safe_label', None)
        assert clean, relative + ': no validation entry point'
        for bad in ['../escape', r'..\\escape', 'drive:escape', 'a/b', '', '.', '..', '/abs', 'a\\b', 'a:b', 'a\x00b']:
            try:
                clean(bad)
            except (ValueError, SystemExit):
                pass
            else:
                raise AssertionError(f'{relative}: unsafe label accepted: {bad!r}')
        for good in ['failed-launch', 'g2-drive-2026-11-13', 'a_b.c-1']:
            assert clean(good) == good, f'{relative}: safe label changed: {good!r}'
    return True


if __name__ == '__main__':
    try:
        check()
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
