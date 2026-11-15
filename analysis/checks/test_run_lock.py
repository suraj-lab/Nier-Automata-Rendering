#!/usr/bin/env python3
"""Frozen gate: one game/replay run at a time (a second concurrent run corrupts both).

Proves: exclusive acquisition, refusal instead of clobbering, stale-lock recovery that needs an explicit flag,
idempotent release, refusal surviving the launcher's own arg parsing, and a real second process being refused
while the first holds the lock. Synthetic locks only: no game, no GPU.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check():
    safety = load(ROOT / 'checks/game_run_safety.py', 'safety_lock')
    acquire = getattr(safety, 'acquire_run_lock', None)
    release = getattr(safety, 'release_run_lock', None)
    assert acquire and release, 'no run lock API'
    base = ROOT / 'runtime/a0-lock-gate'
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        lock = Path(tmp) / 'run.lock'
        handle = acquire(lock, 'first')
        assert lock.exists(), 'lock file not created'
        record = json.loads(lock.read_text())
        assert record['label'] == 'first' and record['pid'] == os.getpid(), record
        # Same process asking twice is still a conflict: a second launcher must not proceed.
        try:
            acquire(lock, 'second')
        except RuntimeError:
            pass
        else:
            raise AssertionError('concurrent acquisition accepted')
        release(handle)
        assert not lock.exists(), 'release left the lock behind'
        release(handle)  # idempotent, must not raise or delete another owner's file

        # A live foreign owner blocks; a dead owner is only recoverable with the explicit flag.
        lock.write_text(json.dumps({'pid': os.getpid(), 'label': 'foreign', 'started': 'now'}))
        try:
            acquire(lock, 'third')
        except RuntimeError:
            pass
        else:
            raise AssertionError('lock held by a live owner was stolen')
        lock.write_text(json.dumps({'pid': 2 ** 22 + 7, 'label': 'dead', 'started': 'now'}))
        try:
            acquire(lock, 'fourth')
        except RuntimeError:
            pass
        else:
            raise AssertionError('stale lock recovered without an explicit flag')
        recovered = acquire(lock, 'fourth', recover_stale=True)
        assert json.loads(lock.read_text())['label'] == 'fourth'
        release(recovered)

        # Corrupt lock content is a refusal, not a crash and not a steal.
        lock.write_text('not json')
        try:
            acquire(lock, 'fifth')
        except RuntimeError:
            pass
        else:
            raise AssertionError('corrupt lock treated as free')
        lock.unlink()

        # Independent process: a live foreign owner blocks, even with recover_stale, and the launcher must refuse.
        holder = subprocess.Popen([sys.executable, '-c',
                                   'import json,sys,time,pathlib;'
                                   f'p=pathlib.Path({str(lock)!r});'
                                   'p.write_text(json.dumps({"pid": __import__("os").getpid(), "label": "holder", "started": "now"}));'
                                   'print("held", flush=True); time.sleep(30)'],
                                  stdout=subprocess.PIPE, text=True)
        try:
            assert holder.stdout.readline().strip() == 'held'
            for recover in (False, True):  # a live owner is never stolen, even when stale recovery is allowed
                try:
                    acquire(lock, 'intruder', recover_stale=recover)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError(f'live foreign owner bypassed (recover_stale={recover})')
            assert json.loads(lock.read_text())['label'] == 'holder', 'live owner lock was replaced'
            runner = load(ROOT / 'runtime/game-runs/game_run.py', 'runner_lock')
            calls = []
            runner.subprocess = types.SimpleNamespace(Popen=lambda *a, **k: calls.append(a))  # module-local shim: never patch the real module
            release_holder = lambda: holder.terminate()
            try:
                runner.acquire_run_lock(lock, 'intruder')
            except RuntimeError:
                pass
            else:
                raise AssertionError('second process acquired a held lock')
            assert not calls, 'launcher started a process while the lock was held'
            # The launcher's own refusal must be a clean message, not a traceback.
            cli = subprocess.run([sys.executable, str(ROOT / 'runtime/game-runs/game_run.py'), 'refusal-test', '--limit', '0'],
                                 capture_output=True, text=True, cwd=ROOT, env={**os.environ, 'NIER_RUN_LOCK': str(lock)})
            combined = cli.stdout + cli.stderr
            assert cli.returncode != 0, 'launcher exit code 0 while a lock is held'
            assert 'Traceback' not in combined, 'refusal printed a traceback: ' + combined.strip().splitlines()[-1]
            assert 'lock' in combined.lower(), 'refusal did not mention the lock'
        finally:
            holder.terminate()
            holder.wait(timeout=10)


if __name__ == '__main__':
    try:
        check()
        print(json.dumps({'passed': True}))
    except (Exception, SystemExit) as exc:
        error = f'candidate exited early: {exc.code}' if isinstance(exc, SystemExit) else str(exc)
        print(json.dumps({'passed': False, 'error': error}))
        sys.exit(1)
