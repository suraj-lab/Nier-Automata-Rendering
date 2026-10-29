#!/usr/bin/env python3
"""Offline gate: captured sun upload is explicit; stale sidecars cannot affect a baseline render."""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


def main():
    script = Path(__file__).resolve().parents[1] / 'remix-probe/run_remote.py'
    spec = importlib.util.spec_from_file_location('probe_remote', script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with tempfile.TemporaryDirectory(prefix='sun-upload-') as tmp:
        work = Path(tmp)
        (work / 'validation-scene.json').write_text(json.dumps({'passed': True, 'exe_sha256': 'test-only'}))
        scene = work / 'scene.bin'
        scene.write_bytes(b'test scene')
        stale = work / 'scene_sun.bin'
        stale.write_bytes(b'stale sun')
        chosen = work / 'verified-ps-cb2.bin'
        chosen.write_bytes(bytes(32))
        result = {'run_folder': 'C:\\test', 'captures': [], 'stdout': '', 'stderr': '', 'threads_at_timeout': [],
                  'timed_out': True, 'exit_code': -1, 'elapsed_seconds': 90, 'remaining': []}

        def run(extra):
            argv = [str(script), 'test-sun', '--scene', str(scene), '--no-unload', *extra]
            with patch.object(mod, 'OUT', work), patch.object(sys, 'argv', argv), \
                 patch.object(mod, 'ps', side_effect=[json.dumps('C:\\test'), json.dumps(result)]) as ps, \
                 patch.object(mod.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as proc, \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    mod.main()
                    code = 0
                except SystemExit as exc:
                    code = exc.code
                return code, [call.args[0] for call in proc.call_args_list], ps.call_count

        code, calls, _ = run([])
        assert code == 0 and not any('scene_sun.bin' in str(c) for c in calls), 'stale sun must not auto-upload'
        code, calls, _ = run(['--sun-cb', str(chosen)])
        assert code == 0 and any(str(chosen) in c and c[-1].endswith('/scene_sun.bin') for c in calls), 'explicit chosen file'
        code, calls, ssh = run(['--sun-cb', str(work / 'missing.bin')])
        assert code == 2 and not calls and not ssh, 'missing requested sun must fail before contacting laptop'
        print(json.dumps({'passed': True, 'cases': 3, 'laptop_contacted': False}))


if __name__ == '__main__':
    try:
        main()
    except AssertionError as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        raise SystemExit(1)
