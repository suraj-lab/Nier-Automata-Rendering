#!/usr/bin/env python3
"""A0.2 replay caller gate: explicit private-prefix selection, mocked launch only (no Wine/GPU/signals)."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

C = Path(__file__).resolve().parent
A = C.parent


def check():
    spec = importlib.util.spec_from_file_location('private_replay_runner', A / 'replay/run_replay.py')
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    base = A / 'runtime/a0-replay-private-gate'
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as temporary:
        w = Path(temporary)
        out = w / 'replay'
        dll = w / 'dll'
        dll.mkdir()
        (dll / 'd3d11.dll').write_bytes(b'mocked DLL, never loaded')
        (dll / 'nier_render_fonts').mkdir()
        conf = w / 'rtx.conf'
        conf.write_text('rtx.test = false\n')
        for template in [out / 'proton-prefix', out / 'wine/prefix']:
            (template / 'pfx').mkdir(parents=True)
            (template / 'payload').write_bytes(b'template unchanged')
        def build(bin_dir, fake):
            bin_dir.mkdir(parents=True, exist_ok=True)
            for name in ['capture_replay.exe', 'd3d11_dlaa.dll', 'fake_remix.dll']:
                (bin_dir / name).write_bytes(b'fixture only')
        for mode in ['off', 'fake']:
            launches = []; cleanups = []
            class Child:
                def wait(self, timeout=None): return 0
            def launch(*args, **kwargs):
                launches.append(kwargs['env'].copy())
                return Child()
            def cleanup(token, prefix):
                cleanups.append((token, Path(prefix).resolve()))
                return []
            label = 'isolated-' + mode
            with contextlib.ExitStack() as stack:
                for attr, value in [('OUT', out), ('DLL', dll), ('build', build), ('cleanup', cleanup),
                                    ('summarise', lambda run: {'result': {'presented': '1'}})]:
                    stack.enter_context(patch.object(replay, attr, value))
                stack.enter_context(patch.object(replay.pack_capture, 'pack', lambda *args, **kwargs: {'scene_size': (32, 32)}))
                stack.enter_context(patch.object(replay.subprocess, 'Popen', launch))
                stack.enter_context(patch.dict(os.environ, {}, clear=True))
                stack.enter_context(patch.object(sys, 'argv', ['run_replay.py', label, 'unused-capture', '--mode', mode,
                                                              '--frames', '1', '--conf', str(conf), '--isolated-prefix']))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                code = replay.main()
            assert code == 0, (mode, code)
            assert len(launches) == len(cleanups) == 1
            env = launches[0]
            private = Path(env['STEAM_COMPAT_DATA_PATH']).resolve()
            assert private.is_relative_to((out / label).resolve()), 'replay launched a shared prefix'
            assert cleanups[0] == (env['NIER_RUN_TOKEN'], private), 'replay cleanup used another prefix'
            owner = json.loads((private / '.nier-run-owner.json').read_text())
            assert owner['token'] == env['NIER_RUN_TOKEN'] and owner['prefix'] == str(private)
            if mode == 'fake':
                assert Path(env['WINEPREFIX']).resolve() == private, 'fake Wine bootstrap and cleanup prefixes differ'
            summary = json.loads((out / label / 'summary.json').read_text())
            assert summary['prefix'] == str(private), 'private prefix omitted from replay receipt'
        for template in [out / 'proton-prefix', out / 'wine/prefix']:
            assert (template / 'payload').read_bytes() == b'template unchanged'
            assert not (template / '.nier-run-owner.json').exists(), 'shared template claimed as private'


if __name__ == '__main__':
    try:
        check()
        print(json.dumps({'passed': True}))
    except (Exception, SystemExit) as exc:
        print(json.dumps({'passed': False, 'error': str(exc)[:1500]}))
        sys.exit(1)
