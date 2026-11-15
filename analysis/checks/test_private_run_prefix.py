#!/usr/bin/env python3
"""A0.2 frozen gate: private copied prefix proves service ownership; legacy shared prefixes never do.
Synthetic saves, /proc records and mocked launcher only. No Wine, game, GPU, remote or real process signals.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

C = Path(__file__).resolve().parent
A = C.parent
sys.path.insert(0, str(C))
import game_run_safety as safety


def fixture_proc(root, pid, env):
    d = root / str(pid)
    d.mkdir()
    (d / 'environ').write_bytes(b'\0'.join(f'{k}={v}'.encode() for k, v in env.items()) + b'\0')


def check():
    prepare = getattr(safety, 'prepare_private_prefix', None)
    assert callable(prepare), 'A0 private-prefix preparation absent'
    base = A / 'runtime/a0-private-prefix-gate'
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as temporary:
        w = Path(temporary)
        real = w / 'real'
        real.mkdir()
        (real / 'SlotData_0.dat').write_bytes(b'current progress, never restore')
        template = w / 'template'
        user = template / 'pfx/drive_c/users/steamuser'
        docs = user / 'Documents'
        (docs / 'My Games/NieR_Automata').mkdir(parents=True)
        (docs / 'My Games/NieR_Automata/SlotData_0.dat').write_bytes(b'copied old progress')
        (user / 'My Documents').symlink_to(docs.resolve(), target_is_directory=True)
        (template / 'dosdevices').mkdir()
        (template / 'dosdevices/z:').symlink_to('/', target_is_directory=True)
        safety.validate_prefix(template, real)
        before = hashlib.sha256((real / 'SlotData_0.dat').read_bytes()).hexdigest()
        private = w / 'run/prefix'
        private.parent.mkdir()
        result = prepare(template, private, 'tok')
        assert Path(result).resolve() == private.resolve(), 'preparer returned a different prefix'
        safety.validate_prefix(private, real)
        assert (private / 'pfx/drive_c/users/steamuser/My Documents').resolve() == (private / 'pfx/drive_c/users/steamuser/Documents').resolve(), 'absolute internal save link was not rebased into private copy'
        assert (private / 'dosdevices/z:').readlink() == Path('/'), 'unrelated external device link was followed or rewritten'
        assert (docs / 'My Games/NieR_Automata/SlotData_0.dat').read_bytes() == b'copied old progress', 'template modified'
        assert hashlib.sha256((real / 'SlotData_0.dat').read_bytes()).hexdigest() == before, 'real save changed'
        marker = private / '.nier-run-owner.json'
        owner = json.loads(marker.read_text())
        st = private.stat()
        assert owner == {'token': 'tok', 'prefix': str(private.resolve()), 'device': st.st_dev, 'inode': st.st_ino}, owner
        try:
            prepare(template, private, 'overwrite')
        except (ValueError, FileExistsError):
            pass
        else:
            raise AssertionError('existing prefix overwritten')
        assert json.loads(marker.read_text()) == owner, 'existing ownership marker changed'
        try:
            prepare(template, template / 'nested', 'nested')
        except ValueError:
            pass
        else:
            raise AssertionError('recursive template copy accepted')
        try:
            prepare(template, w / 'empty-token', '')
        except ValueError:
            pass
        else:
            raise AssertionError('empty ownership token accepted')
        proc = w / 'proc'
        proc.mkdir()
        p = str(private.resolve()); shared = str(template.resolve())
        fixture_proc(proc, 101, {'NIER_RUN_TOKEN': 'tok', 'STEAM_COMPAT_DATA_PATH': p})
        fixture_proc(proc, 102, {'STEAM_COMPAT_DATA_PATH': p, 'WINEPREFIX': p + '/pfx/'})
        fixture_proc(proc, 103, {'WINEPREFIX': p + '/pfx'})
        fixture_proc(proc, 104, {'STEAM_COMPAT_DATA_PATH': shared, 'WINEPREFIX': shared + '/pfx'})
        fixture_proc(proc, 105, {'NIER_RUN_TOKEN': 'foreign', 'STEAM_COMPAT_DATA_PATH': p, 'WINEPREFIX': p + '/pfx'})
        fixture_proc(proc, 106, {'STEAM_COMPAT_DATA_PATH': p + '2', 'WINEPREFIX': p + '2/pfx'})
        fixture_proc(proc, 107, {'WINEPREFIX': p + '/unrelated/nested'})
        fixture_proc(proc, 108, {'STEAM_COMPAT_DATA_PATH': shared, 'WINEPREFIX': p + '/pfx'})
        fixture_proc(proc, 109, {'HOME': p})
        fixture_proc(proc, 110, {'STEAM_COMPAT_DATA_PATH': p})
        fixture_proc(proc, 111, {'WINEPREFIX': p})
        assert safety.owned_pids('tok', private, proc=proc) == [101, 102, 103, 110, 111], 'private service ownership incorrect'
        assert safety.owned_pids('wrong', private, proc=proc) == [], 'marker accepted another run token'
        assert safety.owned_pids('tok', template, proc=proc) == [], 'tokenless shared-prefix service claimed'
        marker.write_text('{broken')
        assert safety.owned_pids('tok', private, proc=proc) == [101], 'corrupt marker broadened ownership'
        marker.write_text(json.dumps(owner))
        cloned = w / 'cloned-prefix'
        shutil.copytree(private, cloned, symlinks=True)
        fixture_proc(proc, 112, {'WINEPREFIX': str(cloned / 'pfx')})
        assert safety.owned_pids('tok', cloned, proc=proc) == [], 'copied ownership receipt accepted for another directory'
        # Same path, replaced directory: device/inode witness must fail closed for tokenless services.
        private.rename(w / 'old-private')
        private.mkdir()
        (private / '.nier-run-owner.json').write_text(json.dumps(owner))
        assert safety.owned_pids('tok', private, proc=proc) == [101], 'replaced private directory claimed tokenless services'

        # Caller integration: --isolated-prefix must launch and clean against the SAME new prefix.
        spec = importlib.util.spec_from_file_location('private_prefix_game_runner', A / 'runtime/game-runs/game_run.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        launches = []; cleanups = []
        class Child:
            def poll(self): return 0
            def wait(self, timeout=None): return 0
        def launch(*args, **kwargs):
            launches.append(kwargs['env'].copy())
            return Child()
        def cleanup(token, prefix):
            cleanups.append((token, Path(prefix).resolve()))
            return []
        runs = w / 'runs'
        with contextlib.ExitStack() as stack:
            for attr, value in [('RUNS', runs), ('PREFIX', template), ('SAVE', real), ('GAME', w), ('cleanup', cleanup)]:
                stack.enter_context(patch.object(runner, attr, value))
            stack.enter_context(patch.object(runner.subprocess, 'Popen', launch))
            stack.enter_context(patch.object(runner, 'owned_pids', lambda *args, **kwargs: []))
            stack.enter_context(patch.object(runner.time, 'sleep', lambda *args: None))
            stack.enter_context(patch.dict(os.environ, {}, clear=True))
            stack.enter_context(patch.object(sys, 'argv', ['game_run.py', 'isolated', '--isolated-prefix', '--limit', '1']))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            code = runner.main()
        assert code == 1, 'mocked failed launch should remain a failed launch'
        assert len(launches) == len(cleanups) == 1, 'launcher/cleanup not called exactly once'
        env = launches[0]
        launched = Path(env['STEAM_COMPAT_DATA_PATH']).resolve()
        assert launched != template.resolve() and launched.is_relative_to((runs / 'isolated').resolve()), 'caller launched shared prefix'
        assert cleanups[0] == (env['NIER_RUN_TOKEN'], launched), 'cleanup used different ownership than launch'
        assert (launched / '.nier-run-owner.json').is_file(), 'caller launched an unowned service prefix'
        summary = json.loads((runs / 'isolated/summary.json').read_text())
        assert summary['save_ok'] and summary['exit'] == 'launch-failed', summary
        assert hashlib.sha256((real / 'SlotData_0.dat').read_bytes()).hexdigest() == before


if __name__ == '__main__':
    try:
        check()
        print(json.dumps({'passed': True}))
    except (Exception, SystemExit) as exc:
        print(json.dumps({'passed': False, 'error': str(exc)[:1500]}))
        sys.exit(1)
