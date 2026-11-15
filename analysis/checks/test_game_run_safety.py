#!/usr/bin/env python3
"""A0 offline safety gate: synthetic saves/processes only; never launch the game."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check():
    runner = load(ROOT / 'runtime/game-runs/game_run.py', 'game_runner')
    base = ROOT / 'runtime/a0-safety-gate'
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        work = Path(tmp)
        real, backup = work / 'real', work / 'old-backup'
        real.mkdir(); backup.mkdir()
        (real / 'SlotData_0.dat').write_bytes(b'newer progress')
        (backup / 'SlotData_0.dat').write_bytes(b'old progress')
        # Regression witness against the old public helper, using synthetic paths.
        if hasattr(runner, 'restore'):
            with patch.object(runner, 'SAVE', real), patch.object(runner, 'BACKUP', backup):
                runner.restore('synthetic mismatch')
            assert (real / 'SlotData_0.dat').read_bytes() == b'newer progress', 'save guard overwrote newer progress with historical backup'
        safety = load(HERE / 'game_run_safety.py', 'safety_candidate')
        prefix = work / 'prefix'
        user = prefix / 'pfx/drive_c/users/steamuser'
        (user / 'Documents/My Games/NieR_Automata').mkdir(parents=True)
        safety.validate_prefix(prefix, real)
        (user / 'My Documents').symlink_to(user / 'Documents', target_is_directory=True)
        safety.validate_prefix(prefix, real)
        escaped = work / 'escaped'
        escaped.mkdir()
        (user / 'Documents/My Games/NieR_Automata').rmdir()
        (user / 'Documents/My Games/NieR_Automata').symlink_to(escaped, target_is_directory=True)
        try:
            safety.validate_prefix(prefix, real)
        except ValueError:
            pass
        else:
            raise AssertionError('escaping copied save path accepted')
        (user / 'Documents/My Games/NieR_Automata').unlink()
        (user / 'Documents/My Games/NieR_Automata').mkdir()
        before = safety.snapshot(real, work / 'before')
        (real / 'SlotData_0.dat').write_bytes(b'newest progress')
        after, ok = safety.verify_save(real, before, work / 'after')
        assert not ok and before != after
        assert (real / 'SlotData_0.dat').read_bytes() == b'newest progress'
        assert (work / 'before/SlotData_0.dat').read_bytes() == b'newer progress'
        assert (work / 'after/SlotData_0.dat').read_bytes() == b'newest progress'
        _, ok = safety.verify_save(real, after, work / 'unchanged')
        assert ok
        (real / 'extra.dat').write_bytes(b'new slot')
        _, ok = safety.verify_save(real, after, work / 'added')
        assert not ok, 'added save file missed'
        proc = work / 'proc'; proc.mkdir()
        for pid, data in [(101, b'NIER_RUN_TOKEN=abc\0STEAM_COMPAT_DATA_PATH=' + os.fsencode(prefix) + b'\0'),
                          (102, b'NIER_RUN_TOKEN=abc-extra\0STEAM_COMPAT_DATA_PATH=' + os.fsencode(prefix) + b'\0'),
                          (103, b'NIER_RUN_TOKEN=abc\0STEAM_COMPAT_DATA_PATH=/different\0')]:
            (proc / str(pid)).mkdir()
            (proc / str(pid) / 'environ').write_bytes(data)
        assert safety.owned_pids('abc', prefix, proc) == [101], 'substring or foreign-prefix process selected'
        token = 'a0-safety-gate-token'
        env = {**os.environ, 'NIER_RUN_TOKEN': token, 'STEAM_COMPAT_DATA_PATH': str(prefix)}
        owned = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], env=env)
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        try:
            safety.cleanup(token, prefix)
            owned.wait(timeout=5)
            assert unrelated.poll() is None, 'cleanup killed unrelated process'
        finally:
            for child in [owned, unrelated]:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=5)
        runs = work / 'runs'
        with patch.object(runner, 'RUNS', runs), patch.object(runner, 'SAVE', real), patch.object(runner, 'PREFIX', prefix), patch.object(runner.subprocess, 'Popen', side_effect=OSError('synthetic launch failure')), patch.object(sys, 'argv', ['game_run.py', 'failed-launch', '--limit', '0']):
            assert runner.main() != 0
        report = json.loads((runs / 'failed-launch/summary.json').read_text())
        assert report['save_ok'] and report['exit'] == 'launch-failed'
        assert (real / 'SlotData_0.dat').read_bytes() == b'newest progress'
        # The shell guard must delegate the same validated report-only implementation.
        state = work / 'shell-state'
        env = {**os.environ, 'NIER_GUARD_SAVE': str(real), 'NIER_GUARD_PREFIX': str(prefix), 'NIER_GUARD_STATE': str(state)}
        guard = ROOT / 'runtime/game-runs/guard.sh'
        first = subprocess.run(['bash', str(guard), 'before'], env=env, capture_output=True, text=True)
        assert first.returncode == 0, first.stderr
        (real / 'SlotData_0.dat').write_bytes(b'latest shell progress')
        second = subprocess.run(['bash', str(guard), 'after'], env=env, capture_output=True, text=True)
        assert second.returncode != 0, 'shell mismatch not signaled'
        assert (real / 'SlotData_0.dat').read_bytes() == b'latest shell progress'
        assert (state / 'before/SlotData_0.dat').read_bytes() == b'newest progress'
        assert (state / 'after/SlotData_0.dat').read_bytes() == b'latest shell progress'


if __name__ == '__main__':
    try:
        check()
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
