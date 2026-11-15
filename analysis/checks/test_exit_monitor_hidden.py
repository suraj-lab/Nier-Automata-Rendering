#!/usr/bin/env python3
"""Hidden C2.1 gate (reviewer dc003508): launch-failure/malformed reports must not crash run_replay before
summary.json, and child argv must round-trip through exit_monitor's quoting (Windows argv rules)."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from unittest.mock import patch

C = Path(__file__).resolve().parent
A = C.parent
sys.path.insert(0, str(C))
from game_run_safety import cleanup, prepare_private_prefix
import test_exit_monitor as frozen

ECHO = r'''
#include <cstdio>
int main(int argc, char** argv) {
    FILE* f = std::fopen("argv.txt", "wb");
    for (int i = 1; i < argc; ++i) std::fprintf(f, "%s\n", argv[i]);
    std::fclose(f);
    return 0;
}
'''


def mocked(report_text, launcher_code):
    spec = importlib.util.spec_from_file_location('exit_monitor_hidden', A / 'replay/run_replay.py')
    replay = importlib.util.module_from_spec(spec); spec.loader.exec_module(replay)
    base = A / 'runtime/exit-monitor-gate'; base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as temporary:
        w = Path(temporary); out = w / 'replay'; dll = w / 'dll'
        (dll / 'nier_render_fonts').mkdir(parents=True); (dll / 'd3d11.dll').write_bytes(b'mocked')
        conf = w / 'rtx.conf'; conf.write_text('rtx.test = false\n')
        def build(bin_dir, fake):
            bin_dir.mkdir(parents=True, exist_ok=True)
            for name in ['capture_replay.exe', 'd3d11_dlaa.dll', 'fake_remix.dll', 'exit_monitor.exe']:
                (bin_dir / name).write_bytes(b'fixture')
        class Child:
            returncode = launcher_code
            def poll(self): return self.returncode
            def wait(self, timeout=None): return self.returncode
        def launch(cmd, cwd=None, env=None, **kwargs):
            (Path(cwd) / 'target-exit.txt').write_text(report_text)
            return Child()
        with contextlib.ExitStack() as stack:
            for attr, value in [('OUT', out), ('DLL', dll), ('build', build), ('cleanup', lambda token, prefix: []),
                                ('summarise', lambda run: {'result': {'presented': '1'}})]:
                stack.enter_context(patch.object(replay, attr, value))
            stack.enter_context(patch.object(replay.pack_capture, 'pack', lambda *a, **k: {'scene_size': (32, 32)}))
            stack.enter_context(patch.object(replay.subprocess, 'Popen', launch))
            stack.enter_context(patch.dict(os.environ, {}, clear=True))
            stack.enter_context(patch.object(sys, 'argv', ['run_replay.py', 'x', 'unused', '--mode', 'off', '--frames', '1',
                                                          '--conf', str(conf), '--isolated-prefix', '--exit-monitor',
                                                          '--exit-grace', '1', '--timeout', '20']))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            try:
                code = replay.main()
            except Exception as exc:
                raise AssertionError(f'run_replay crashed on report {report_text!r}: {exc!r}')
        summary = out / 'x' / 'summary.json'
        assert summary.exists(), 'summary.json lost'
        return code, json.loads(summary.read_text())


def argv_roundtrip():
    frozen.OUT.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix='hidden-', dir=frozen.OUT))
    template = frozen.OUT / 'template'; template.mkdir(exist_ok=True)
    token = uuid.uuid4().hex
    prefix = prepare_private_prefix(template, session / 'prefix', token)
    work = session / 'work'; work.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('NIER_', 'MOCK_', 'FAKE_', 'WINE'))}
    env.update(WINEPREFIX=str(prefix), NIER_RUN_TOKEN=token, STEAM_COMPAT_DATA_PATH=str(prefix), WINEDEBUG='-all',
               HOME=str(session), DISPLAY='', WAYLAND_DISPLAY='', WINEDLLOVERRIDES='winemenubuilder.exe=d;mscoree,mshtml=')
    try:
        (work / 'echo.cpp').write_text(ECHO)
        for s, exe in [(C / 'exit_monitor.cpp', 'exit_monitor.exe'), (work / 'echo.cpp', 'echo.exe')]:
            r = subprocess.run([*frozen.GPP, str(s), '-o', str(work / exe)], capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[-1200:]
        args = ['plain', 'with space', 'x\\"y', 'D:\\out\\', 'a\\\\b', '', 'q"q']
        r = subprocess.run(['wine', 'exit_monitor.exe', 'r.txt', 'echo.exe', *args], cwd=work, env=env, capture_output=True, timeout=60)
        assert r.returncode == 0, r.returncode
        got = (work / 'argv.txt').read_bytes().decode().split('\n')[:-1]
        assert got == args, ('argv not preserved', got, args)
    finally:
        subprocess.run(['wineserver', '-k'], env=env, capture_output=True)
        cleanup(token, prefix)


def check():
    code, s = mocked('error=launch\ndone=1\n', 127)
    assert code == 1 and s['target_exit'] is None and s['errors'], ('launch failure', s)
    code, s = mocked('pid=7\ngarbage line\nexit_code=zero\nelapsed_ms=1\ndone=1\n', 0)
    assert code == 1 and s['target_exit'] is None and s['errors'], ('malformed report', s)
    argv_roundtrip()


if __name__ == '__main__':
    try:
        check(); print(json.dumps({'passed': True}))
    except (Exception, SystemExit) as exc:
        print(json.dumps({'passed': False, 'error': repr(exc)[:1800]})); sys.exit(1)
