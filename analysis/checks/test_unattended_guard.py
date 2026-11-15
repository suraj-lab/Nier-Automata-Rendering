#!/usr/bin/env python3
"""Frozen gate: unattended authorization guard (checks/unattended_guard.py).

Contract (written by the lead before the implementation exists):
  * Interactive use (NIER_UNATTENDED != "1") is unchanged: authorize() returns and writes nothing.
  * NIER_UNATTENDED=1: an action runs only if ~/.config/nier-auto/authorization.json (written by the user) is valid,
    not expired, grants the action, its per-authorization cap is not used up and the item's attempts are not used up.
    Each granted use is appended to ~/.config/nier-auto/usage.jsonl with the authorization's sha256; a new
    authorization file therefore starts fresh counts. Refusal = SystemExit whose text starts "unattended: refused".
  * dll_install additionally needs the newest analysis/runtime/suite-*/full-suite.json to be passed and < 3 h old.
  * report_run(summary): unattended + save_ok false -> analysis/runtime/auto/BLOCKED names the save mismatch.
  * The real entry points refuse before any side effect: install_live_dll.py --install, game_run.py, laptop_port.py.
"""
import datetime
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

A = Path(__file__).resolve().parents[1]
GUARD = A / 'checks' / 'unattended_guard.py'
failures = []


def check(name, ok, detail=''):
    if not ok:
        failures.append(f'{name}: {detail}')


def iso(hours):
    t = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours)
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


def load(tree):
    spec = importlib.util.spec_from_file_location(f'guard_{abs(hash(str(tree)))}', tree / 'analysis/checks/unattended_guard.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refused(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except SystemExit as exc:
        return str(exc.code).startswith('unattended: refused')
    return False


def fresh(root):
    """A private copy of the guard in a fake analysis/ tree plus a private HOME."""
    tree = Path(tempfile.mkdtemp(dir=root))
    (tree / 'analysis/checks').mkdir(parents=True)
    shutil.copyfile(GUARD, tree / 'analysis/checks/unattended_guard.py')
    home = tree / 'home'
    home.mkdir()
    os.environ['HOME'] = str(home)
    return tree, home


def write_auth(home, **grant):
    path = home / '.config/nier-auto/authorization.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(grant))
    return path


def write_suite(tree, passed, age_hours=0.0):
    path = tree / f'analysis/runtime/suite-gate-{len(list(tree.glob("analysis/runtime/suite-*")))}/full-suite.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'passed': passed, 'total': 1}))
    stamp = datetime.datetime.now().timestamp() - age_hours * 3600
    os.utime(path, (stamp, stamp))


def unit(root):
    saved = dict(os.environ)
    try:
        # 1 interactive: no effect, no files
        tree, home = fresh(root)
        os.environ.pop('NIER_UNATTENDED', None)
        g = load(tree)
        check('interactive returns', not refused(g.authorize, 'desktop_live_run', 'camp'))
        check('interactive writes nothing', not any(home.rglob('*')), list(home.rglob('*')))
        g.report_run({'save_ok': False})
        check('interactive report writes nothing', not (tree / 'analysis/runtime/auto/BLOCKED').exists())

        os.environ['NIER_UNATTENDED'] = '1'
        # 2 no authorization; 3 malformed; 4 expired; unknown action
        tree, home = fresh(root)
        g = load(tree)
        check('missing auth refused', refused(g.authorize, 'desktop_live_run', 'camp'))
        p = write_auth(home)
        p.write_text('{not json')
        check('malformed refused', refused(g.authorize, 'desktop_live_run', 'camp'))
        write_auth(home, expires=iso(-1), desktop_live_runs=5)
        check('expired refused', refused(g.authorize, 'desktop_live_run', 'camp'))
        write_auth(home, expires='tomorrow', desktop_live_runs=5)
        check('unparseable expiry refused', refused(g.authorize, 'desktop_live_run', 'camp'))
        write_auth(home, expires=iso(5), desktop_live_runs=5)
        check('unknown action refused', refused(g.authorize, 'format_disk', 'x'))
        check('ungranted action refused', refused(g.authorize, 'laptop', 'x'))

        # 5 cap; 6 attempts per item incl. numbered retries; 7 new authorization resets
        tree, home = fresh(root)
        g = load(tree)
        auth = write_auth(home, expires=iso(5), desktop_live_runs=3, attempts_per_item=2)
        check('run 1', not refused(g.authorize, 'desktop_live_run', 'pond-ab-1'))
        check('run 2 same item', not refused(g.authorize, 'desktop_live_run', 'pond-ab-2'))
        check('item attempts exhausted', refused(g.authorize, 'desktop_live_run', 'pond-ab-3'))
        check('other item ok', not refused(g.authorize, 'desktop_live_run', 'camp-sky'))
        check('cap exhausted', refused(g.authorize, 'desktop_live_run', 'desert-x'))
        usage = (home / '.config/nier-auto/usage.jsonl').read_text().splitlines()
        sha = hashlib.sha256(auth.read_bytes()).hexdigest()
        check('usage lines = granted uses', len(usage) == 3, usage)
        check('usage keyed by auth sha', all(json.loads(l).get('auth_sha256') == sha for l in usage), usage[:1])
        write_auth(home, expires=iso(6), desktop_live_runs=1)
        check('new authorization resets counts', not refused(g.authorize, 'desktop_live_run', 'desert-x'))
        check('new authorization cap', refused(g.authorize, 'desktop_live_run', 'other'))
        check('default attempts_per_item exists', hasattr(g, 'DEFAULT_ATTEMPTS') and g.DEFAULT_ATTEMPTS >= 1)

        # 9 dll_install needs a fresh green suite
        tree, home = fresh(root)
        g = load(tree)
        write_auth(home, expires=iso(5), dll_installs=5)
        check('dll without suite refused', refused(g.authorize, 'dll_install', 'abc'))
        write_suite(tree, False, age_hours=1)   # v2: older than the fresh green one below (v1 wrote it as newest)
        check('dll red suite refused', refused(g.authorize, 'dll_install', 'abc'))
        write_suite(tree, True, age_hours=4)
        check('dll stale suite refused', refused(g.authorize, 'dll_install', 'abc'))
        write_suite(tree, True, age_hours=0.1)
        check('dll fresh green suite ok', not refused(g.authorize, 'dll_install', 'abc'))
        write_suite(tree, False, age_hours=0.0)
        check('newest suite decides', refused(g.authorize, 'dll_install', 'abd'))

        # laptop
        tree, home = fresh(root)
        g = load(tree)
        write_auth(home, expires=iso(5), laptop_sessions=1)
        check('laptop granted', not refused(g.authorize, 'laptop', 'install'))
        check('laptop cap', refused(g.authorize, 'laptop', 'run'))

        # 10 save mismatch -> BLOCKED
        g.report_run({'label': 'x', 'save_ok': True})
        check('save ok no BLOCKED', not (tree / 'analysis/runtime/auto/BLOCKED').exists())
        g.report_run({'label': 'pond-ab-1', 'save_ok': False})
        blocked = tree / 'analysis/runtime/auto/BLOCKED'
        check('save mismatch BLOCKED', blocked.exists() and 'save' in blocked.read_text().lower()
              and 'pond-ab-1' in blocked.read_text(), blocked.read_text() if blocked.exists() else 'missing')
    finally:
        os.environ.clear()
        os.environ.update(saved)


def integration(root):
    home = Path(tempfile.mkdtemp(dir=root))
    fakebin = Path(tempfile.mkdtemp(dir=root))
    marker = fakebin / 'called'
    for tool in ('ssh', 'scp', 'gamescope'):
        (fakebin / tool).write_text(f'#!/bin/sh\necho "$0 $*" >> {marker}\nexit 1\n')
        (fakebin / tool).chmod(0o755)
    env = dict(os.environ, NIER_UNATTENDED='1', HOME=str(home), PATH=f'{fakebin}:{os.environ["PATH"]}',
               NIER_RUN_LOCK=str(home / 'run.lock'))
    backups = A / 'backups'
    before = sorted(p.name for p in backups.iterdir()) if backups.exists() else []
    r = subprocess.run([sys.executable, str(A / 'checks/install_live_dll.py'), '--install', '--expect', '0' * 64],
                       env=env, capture_output=True, text=True, timeout=60)
    check('install refused', r.returncode != 0 and 'unattended: refused' in r.stderr, r.stderr[-300:])
    after = sorted(p.name for p in backups.iterdir()) if backups.exists() else []
    check('install made no backup folder', before == after)
    # v3: unique label, and a folder made by a broken guard is removed (fake gamescope makes that run fail at launch)
    label = 'guard-gate-probe-' + os.urandom(4).hex() + 'x'
    run_dir = A / 'runtime/game-runs' / label
    try:
        r = subprocess.run([sys.executable, str(A / 'runtime/game-runs/game_run.py'), label, '--live',
                            '--isolated-prefix'], env=env, capture_output=True, text=True, timeout=60)
        check('game_run refused', r.returncode != 0 and 'unattended: refused' in r.stderr, r.stderr[-300:])
        check('game_run made no run folder', not run_dir.exists())
    finally:
        if run_dir.exists():
            shutil.rmtree(run_dir)
    for cmd in (['install'], ['run', 'x', '--live'], ['restore']):
        r = subprocess.run([sys.executable, str(A / 'deploy/laptop_port.py'), *cmd], env=env,
                           capture_output=True, text=True, timeout=60)
        check(f'laptop {cmd[0]} refused', r.returncode != 0 and 'unattended: refused' in r.stderr, r.stderr[-300:])
    check('no ssh/scp/gamescope call', not marker.exists(), marker.read_text() if marker.exists() else '')
    # interactive default unchanged: dry-run installer still reaches its own hash check
    plain = {k: v for k, v in os.environ.items() if k != 'NIER_UNATTENDED'}
    r = subprocess.run([sys.executable, str(A / 'checks/install_live_dll.py'), '--expect', '0' * 64],
                       env=plain, capture_output=True, text=True, timeout=60)
    text = r.stdout + r.stderr
    check('interactive installer unchanged', 'unattended' not in text and
          ('is not the reviewed one' in text or 'candidate missing' in text), text[-300:])


def main():
    root = Path(tempfile.mkdtemp(prefix='unattended-guard-', dir=A / 'runtime' if (A / 'runtime').exists() else None))
    try:
        if not GUARD.exists():
            failures.append(f'missing {GUARD}')
        else:
            unit(root)
            integration(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(json.dumps({'passed': not failures, 'failures': failures}, indent=1))
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(main())
