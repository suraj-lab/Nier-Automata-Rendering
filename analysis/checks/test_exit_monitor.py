#!/usr/bin/env python3
"""Frozen C2.1 gate: Windows-side child exit-status monitor and opt-in replay integration.

Part A (Wine, private owned prefix, no display/GPU): checks/exit_monitor.cpp ->
  exit_monitor.exe <report> <child.exe> [args...]
  starts the child, waits for THAT process only (not detached grandchildren), mirrors its exit code and writes
  <report> exclusively as key=value lines: pid=, exit_code=, elapsed_ms=, then done=1 last. Launch failure ->
  error=launch, done=1, nonzero monitor exit. An existing report is never overwritten.
Part B (mocked launch, no Wine): run_replay.py --exit-monitor [--exit-grace S] wraps capture_replay.exe, reads the
  report while the launcher lingers, records summary['target_exit'], and stops waiting S seconds after the target
  exited. Without the flag the command line and summary semantics are unchanged.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
from unittest.mock import patch

C = Path(__file__).resolve().parent
A = C.parent
OUT = A / 'runtime' / 'exit-monitor-gate'
sys.path.insert(0, str(C))
from game_run_safety import cleanup, prepare_private_prefix

GPP = ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-static', '-static-libgcc', '-static-libstdc++']
CHILD = r'''
#include <windows.h>
#include <cstdlib>
#include <cstring>
int main(int argc, char** argv) {
    if (argc > 2 && !std::strcmp(argv[1], "spawn")) {   // leave a detached grandchild running, like winedevice
        STARTUPINFOA si{}; si.cb = sizeof si; PROCESS_INFORMATION pi{};
        char cmd[512]; std::strcpy(cmd, argv[2]);
        std::strcat(cmd, " sleep 20000");
        if (!CreateProcessA(nullptr, cmd, nullptr, nullptr, FALSE, DETACHED_PROCESS, nullptr, nullptr, &si, &pi)) return 90;
        CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
        return 5;
    }
    if (argc > 2 && !std::strcmp(argv[1], "sleep")) { Sleep(std::atoi(argv[2])); return 0; }
    if (argc > 2 && !std::strcmp(argv[1], "exit")) { Sleep(300); return std::atoi(argv[2]); }
    return 64;
}
'''


def report(path):
    lines = path.read_text().splitlines()
    assert lines and lines[-1] == 'done=1', ('report incomplete', lines)
    return dict(line.split('=', 1) for line in lines)


def part_a(work, env):
    src = work / 'child.cpp'; src.write_text(CHILD)
    for s, exe in [(C / 'exit_monitor.cpp', 'exit_monitor.exe'), (src, 'child.exe')]:
        assert s.is_file(), f'{s.name} absent'
        r = subprocess.run([*GPP, str(s), '-o', str(work / exe)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-1500:]
    def wine(*args, timeout=60):
        start = time.monotonic()
        r = subprocess.run(['wine', 'exit_monitor.exe', *args], cwd=work, env=env, capture_output=True, timeout=timeout)
        return r.returncode, time.monotonic() - start
    code, _ = wine('r-exit.txt', 'child.exe', 'exit', '7')
    m = report(work / 'r-exit.txt')
    assert code == 7 and m['exit_code'] == '7', ('exit code not mirrored', code, m)
    assert int(m['pid']) > 0 and 250 <= int(m['elapsed_ms']) < 20000, m
    # The wine host process may outlive the target while a detached grandchild runs (that is the C2 confusion
    # itself), so time the REPORT, not the launcher: it must be complete while the 20 s grandchild is still alive.
    p = subprocess.Popen(['wine', 'exit_monitor.exe', 'r-spawn.txt', 'child.exe', 'spawn', 'child.exe'], cwd=work, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    start, m = time.monotonic(), None
    while time.monotonic() - start < 15 and m is None:
        f = work / 'r-spawn.txt'
        if f.exists() and f.read_text().endswith('done=1\n'):
            m = report(f)
        time.sleep(.1)
    assert m is not None, 'monitor waited for a detached grandchild, not the target'
    assert m['exit_code'] == '5' and int(m['elapsed_ms']) < 10000, ('grandchild case', m)
    assert p.wait(timeout=60) == 5, 'monitor exit code not mirrored in the grandchild case'
    code, _ = wine('r-missing.txt', 'no-such-child.exe')
    m = report(work / 'r-missing.txt')
    assert code != 0 and m.get('error') == 'launch' and 'exit_code' not in m, ('launch failure', code, m)
    keep = work / 'r-keep.txt'; keep.write_bytes(b'prior evidence')
    code, _ = wine('r-keep.txt', 'child.exe', 'exit', '0')
    assert code != 0 and keep.read_bytes() == b'prior evidence', 'existing report overwritten'
    code, _ = wine()
    assert code != 0, 'usage error accepted'


def part_b():
    spec = importlib.util.spec_from_file_location('exit_monitor_replay', A / 'replay/run_replay.py')
    replay = importlib.util.module_from_spec(spec); spec.loader.exec_module(replay)
    base = A / 'runtime/exit-monitor-gate'; base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as temporary:
        w = Path(temporary); out = w / 'replay'; dll = w / 'dll'
        (dll / 'nier_render_fonts').mkdir(parents=True)
        (dll / 'd3d11.dll').write_bytes(b'mocked')
        conf = w / 'rtx.conf'; conf.write_text('rtx.test = false\n')
        def build(bin_dir, fake):
            bin_dir.mkdir(parents=True, exist_ok=True)
            for name in ['capture_replay.exe', 'd3d11_dlaa.dll', 'fake_remix.dll', 'exit_monitor.exe']:
                (bin_dir / name).write_bytes(b'fixture ' + name.encode())
        def run(label, flags, target_code, launcher):
            commands = []
            class Child:
                returncode = None
                def __init__(self, cwd): self.cwd = Path(cwd); self.start = time.monotonic()
                def poll(self):
                    if launcher == 'exits' and time.monotonic() - self.start > .5:
                        self.returncode = 0
                    return self.returncode
                def wait(self, timeout=None):
                    end = time.monotonic() + (timeout if timeout is not None else 1e9)
                    while self.poll() is None:
                        if time.monotonic() >= end: raise subprocess.TimeoutExpired('launcher', timeout)
                        time.sleep(.05)
                    return self.returncode
            def launch(cmd, cwd=None, env=None, **kwargs):
                commands.append(list(cmd))
                if target_code is not None:   # the target exits quickly; the report is written by the monitor
                    i = cmd.index('./exit_monitor.exe')
                    (Path(cwd) / cmd[i + 1]).write_text(f'pid=42\nexit_code={target_code}\nelapsed_ms=300\ndone=1\n')
                return Child(cwd)
            with contextlib.ExitStack() as stack:
                for attr, value in [('OUT', out), ('DLL', dll), ('build', build), ('cleanup', lambda token, prefix: [4242]),
                                    ('summarise', lambda run: {'result': {'presented': '1'}})]:
                    stack.enter_context(patch.object(replay, attr, value))
                stack.enter_context(patch.object(replay.pack_capture, 'pack', lambda *a, **k: {'scene_size': (32, 32)}))
                stack.enter_context(patch.object(replay.subprocess, 'Popen', launch))
                stack.enter_context(patch.dict(os.environ, {}, clear=True))
                stack.enter_context(patch.object(sys, 'argv', ['run_replay.py', label, 'unused', '--mode', 'off', '--frames', '1',
                                                              '--conf', str(conf), '--isolated-prefix', *flags]))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                start = time.monotonic()
                code = replay.main()
                seconds = time.monotonic() - start
            return code, seconds, commands, json.loads((out / label / 'summary.json').read_text()), out / label
        # Default: unchanged command, no target_exit, a launcher timeout stays a failure.
        code, _, cmds, s, _ = run('default', ['--timeout', '2'], None, 'lingers')
        assert not any('exit_monitor' in c for c in cmds[0]), 'monitor used without --exit-monitor'
        assert code == 1 and s['exit'] == 'timeout' and s.get('target_exit') is None, s
        # Target exits 0, launcher lingers: stop after the grace, report forced services separately, accept.
        code, seconds, cmds, s, run_dir = run('lingers', ['--exit-monitor', '--exit-grace', '1', '--timeout', '60'], 0, 'lingers')
        cmd = cmds[0]
        i = cmd.index('./exit_monitor.exe')
        assert cmd[i + 2] == './capture_replay.exe', ('monitor must wrap the replayer', cmd)
        assert Path(cmd[i + 1]).name == cmd[i + 1], 'report path must be run-relative'
        assert (run_dir / 'exit_monitor.exe').read_bytes() == b'fixture exit_monitor.exe', 'monitor not staged into the run'
        assert seconds < 20, 'waited for the launcher timeout after the target had exited'
        t = s['target_exit']
        assert t['exit_code'] == 0 and t['elapsed_ms'] == 300 and t['pid'] == 42, t
        assert s['exit'] == 'target-exited' and s['forced_pids'] == [4242], s
        assert code == 0, 'clean target exit with lingering services must pass and list the forced cleanup'
        # Target exit code nonzero: failure even though presented.
        code, _, _, s, _ = run('bad-code', ['--exit-monitor', '--exit-grace', '1', '--timeout', '60'], 3, 'lingers')
        assert code == 1 and s['target_exit']['exit_code'] == 3, s
        # Monitor never reports (target hang): launcher timeout, no target_exit, failure.
        code, _, _, s, _ = run('hang', ['--exit-monitor', '--exit-grace', '1', '--timeout', '2'], None, 'lingers')
        assert code == 1 and s['exit'] == 'timeout' and s['target_exit'] is None, s
        # Launcher exits by itself after the target: normal exit code kept.
        code, _, _, s, _ = run('normal', ['--exit-monitor', '--timeout', '60'], 0, 'exits')
        assert code == 0 and s['exit'] == 0 and s['target_exit']['exit_code'] == 0, s


def main():
    part_b()
    OUT.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix='session-', dir=OUT))
    template = OUT / 'template'; template.mkdir(exist_ok=True)
    token = uuid.uuid4().hex
    prefix = prepare_private_prefix(template, session / 'prefix', token)
    work = session / 'work'; work.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('NIER_', 'MOCK_', 'FAKE_', 'WINE'))}
    env.update(WINEPREFIX=str(prefix), NIER_RUN_TOKEN=token, STEAM_COMPAT_DATA_PATH=str(prefix), WINEDEBUG='-all',
               HOME=str(session), DISPLAY='', WAYLAND_DISPLAY='', WINEDLLOVERRIDES='winemenubuilder.exe=d;mscoree,mshtml=')
    try:
        part_a(work, env)
    finally:
        subprocess.run(['wineserver', '-k'], env=env, capture_output=True)
        cleanup(token, prefix)


if __name__ == '__main__':
    try:
        main(); print(json.dumps({'passed': True}))
    except (Exception, SystemExit) as exc:
        print(json.dumps({'passed': False, 'error': repr(exc)[:1800]})); sys.exit(1)
