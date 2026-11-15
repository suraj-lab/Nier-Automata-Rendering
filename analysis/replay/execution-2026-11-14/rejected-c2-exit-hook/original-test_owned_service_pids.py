#!/usr/bin/env python3
"""Frozen gate: run cleanup also owns token-less Wine service processes of the run's own prefix.

Evidence (execution-2026-11-14 C2): winedevice.exe is started by Wine's service manager, inherits the prefix but not
NIER_RUN_TOKEN, so token-only ownership never killed it; 26 orphans accumulated (ppid 1, no wineserver), ten spinning
at ~55% CPU each for 8 h. A process carrying a DIFFERENT run token stays someone else's even in the same prefix.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
sys.path.insert(0, str(C))
import game_run_safety as grs  # noqa: E402


def fake_proc(root, pid, env):
    d = root / str(pid)
    d.mkdir()
    (d / 'environ').write_bytes(b'\0'.join(f'{k}={v}'.encode() for k, v in env.items()) + b'\0')


def check():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        prefix = tmp / 'prefix'
        (prefix / 'pfx').mkdir(parents=True)
        other = tmp / 'prefix2'  # shares a string prefix with `prefix`: must not match
        (other / 'pfx').mkdir(parents=True)
        proc = tmp / 'proc'
        proc.mkdir()
        p = str(prefix.resolve())
        fake_proc(proc, 101, {'NIER_RUN_TOKEN': 'tok', 'STEAM_COMPAT_DATA_PATH': p})              # the game: owned
        fake_proc(proc, 102, {'STEAM_COMPAT_DATA_PATH': p, 'WINEPREFIX': p + '/pfx/'})           # winedevice: owned
        fake_proc(proc, 103, {'WINEPREFIX': p + '/pfx'})                                          # service, WINEPREFIX only
        fake_proc(proc, 104, {'NIER_RUN_TOKEN': 'other', 'STEAM_COMPAT_DATA_PATH': p})           # another run: not ours
        fake_proc(proc, 105, {'STEAM_COMPAT_DATA_PATH': str(other.resolve()), 'WINEPREFIX': str(other.resolve()) + '/pfx'})
        fake_proc(proc, 106, {'HOME': '/home/x'})                                                 # unrelated
        fake_proc(proc, 107, {'WINEPREFIX': p})                                                   # plain wine prefix = ours
        got = grs.owned_pids('tok', prefix, proc=proc)
        assert got == [101, 102, 103, 107], got
        try:
            grs.owned_pids('', prefix, proc=proc)
        except ValueError:
            pass
        else:
            raise AssertionError('empty token accepted')


if __name__ == '__main__':
    try:
        check()
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)[:600]}))
        sys.exit(1)
