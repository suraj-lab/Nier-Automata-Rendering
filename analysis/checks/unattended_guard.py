"""Unattended authorization guard. Interactive use (NIER_UNATTENDED != "1") is unchanged.

Under NIER_UNATTENDED=1 (set by analysis/tools/overnight.sh) a live action needs the user's own authorization file,
~/.config/nier-auto/authorization.json, for example:

    {"expires": "2026-11-16T12:00:00Z", "desktop_live_runs": 10, "dll_installs": 6,
     "laptop_sessions": 0, "attempts_per_item": 3}

Every granted use is appended to ~/.config/nier-auto/usage.jsonl with the authorization's sha256, so caps count per
authorization and a new file starts fresh. Gate: checks/test_unattended_guard.py.
shortcut: a tripwire, not a sandbox - the agent runs as the same user and could edit this file or the authorization;
overnight.sh pins their hashes and stops the loop if they change.
"""
import datetime
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

A = Path(__file__).resolve().parents[1]
CAPS = {'desktop_live_run': 'desktop_live_runs', 'dll_install': 'dll_installs', 'laptop': 'laptop_sessions'}
DEFAULT_ATTEMPTS = 3
SUITE_MAX_AGE_S = 3 * 3600


def unattended():
    return os.environ.get('NIER_UNATTENDED') == '1'


def _folder():
    return Path.home() / '.config/nier-auto'


def _refuse(why):
    raise SystemExit(f'unattended: refused: {why}')


def _stem(item):
    return re.sub(r'-\d+$', '', str(item))


def _green_suite():
    suites = sorted(A.glob('runtime/suite-*/full-suite.json'), key=lambda p: p.stat().st_mtime)
    if not suites:
        _refuse('dll_install needs a full suite run (runtime/suite-*/full-suite.json); none found')
    newest = suites[-1]
    try:
        passed = json.loads(newest.read_text()).get('passed') is True
    except (OSError, ValueError):
        passed = False
    if not passed:
        _refuse(f'newest suite {newest} is not green')
    if time.time() - newest.stat().st_mtime > SUITE_MAX_AGE_S:
        _refuse(f'newest suite {newest} is older than 3 h; rerun it first')


def authorize(action, item):
    """Return if `action` on `item` may run now; otherwise raise SystemExit('unattended: refused: ...')."""
    if not unattended():
        return
    if action not in CAPS:
        _refuse(f'unknown action {action!r}')
    path = _folder() / 'authorization.json'
    try:
        raw = path.read_bytes()
        grant = json.loads(raw)
        expires = datetime.datetime.strptime(grant['expires'], '%Y-%m-%dT%H:%M:%SZ').replace(
            tzinfo=datetime.timezone.utc)
        cap = int(grant.get(CAPS[action], 0))
        attempts = int(grant.get('attempts_per_item', DEFAULT_ATTEMPTS))
    except FileNotFoundError:
        _refuse(f'no authorization file {path}; the user writes it')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _refuse(f'invalid authorization file {path}: {exc}')
    if datetime.datetime.now(datetime.timezone.utc) >= expires:
        _refuse(f'authorization expired at {grant["expires"]}')
    if cap <= 0:
        _refuse(f'{action} is not granted ({CAPS[action]} = {cap})')
    sha = hashlib.sha256(raw).hexdigest()
    usage_path = _folder() / 'usage.jsonl'
    used = []
    if usage_path.exists():
        for line in usage_path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('auth_sha256') == sha and row.get('action') == action:
                used.append(row)
    if len(used) >= cap:
        _refuse(f'{action} cap {cap} used up for this authorization')
    if sum(_stem(r.get('item')) == _stem(item) for r in used) >= attempts:
        _refuse(f'{action} attempts for {_stem(item)!r} used up ({attempts})')
    if action == 'dll_install':
        _green_suite()
    row = {'time': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'action': action, 'item': str(item), 'auth_sha256': sha}
    with usage_path.open('a') as f:
        f.write(json.dumps(row) + '\n')


def report_run(summary):
    """Unattended: a save mismatch stops the overnight loop (BLOCKED); nothing is restored."""
    if not unattended() or summary.get('save_ok', False):
        return
    blocked = A / 'runtime/auto/BLOCKED'
    blocked.parent.mkdir(parents=True, exist_ok=True)
    with blocked.open('a') as f:
        f.write(f'save verification failed in run {summary.get("label")!r}: both save versions are preserved in its '
                f'run folder; stop all runs and ask the user. Nothing was restored.\n')
    print(f'unattended: save mismatch recorded in {blocked}', file=sys.stderr)
