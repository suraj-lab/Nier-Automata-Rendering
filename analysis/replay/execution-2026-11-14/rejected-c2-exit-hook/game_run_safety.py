#!/usr/bin/env python3
"""Report-only save protection and exact, pidfd-pinned cleanup for owned game runs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import time


def acquire_run_lock(path, label, recover_stale=False):
    """One run at a time: exclusive create, live owner refused, stale only with an explicit flag."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {'pid': os.getpid(), 'label': label, 'started': f'{time.time():.3f}'}
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        try:
            held = json.loads(path.read_text())
            pid, owner = int(held['pid']), str(held['label'])
        except (OSError, ValueError, KeyError, TypeError):
            raise RuntimeError(f'run lock {path} is unreadable; remove it by hand after checking for a live run')
        if pid != os.getpid():
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                if not recover_stale:
                    raise RuntimeError(f'stale run lock from {owner!r} (pid {pid} is gone); pass recover_stale=True')
            except PermissionError:
                raise RuntimeError(f'run lock held by {owner!r} (pid {pid}); refusing to run')
            else:
                raise RuntimeError(f'run lock held by {owner!r} (pid {pid}); refusing to run')
        if not recover_stale:
            raise RuntimeError(f'run lock already held (label {owner!r}, pid {pid}); refusing to run')
        os.unlink(path)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(fd, 'w') as stream:
        json.dump(record, stream)
    return {'path': path, **record}


def release_run_lock(handle):
    """Idempotent, and never removes a lock another owner has taken over."""
    path = Path(handle['path'])
    try:
        held = json.loads(path.read_text())
    except (OSError, ValueError):
        return
    if int(held.get('pid', -1)) == handle['pid'] and held.get('label') == handle['label']:
        path.unlink(missing_ok=True)


def safe_label(label):
    if not label or label in ('.', '..') or Path(label).name != label or any(c in label for c in '\\:'):
        raise ValueError(f'unsafe run label: {label!r}')
    if any(ord(c) < 32 or ord(c) == 127 for c in label):
        raise ValueError(f'unsafe run label: {label!r}')
    return label


def validate_prefix(prefix, real_save):
    root = Path(prefix).resolve(strict=True)
    user = root / 'pfx/drive_c/users/steamuser'
    if not user.is_dir():
        raise ValueError('copied prefix has no steamuser directory')
    for name in ['Documents', 'My Documents']:
        documents = user / name
        for path in [documents, documents / 'My Games/NieR_Automata']:
            resolved = path.resolve()
            if not resolved.is_relative_to(root) or resolved == Path(real_save).resolve():
                raise ValueError(f'copied save path escapes prefix: {path} -> {resolved}')
    if not Path(real_save).is_dir():
        raise ValueError('real save directory unavailable; cannot establish protection')


def snapshot(save, destination):
    save, destination = Path(save), Path(destination)
    if not save.is_dir():
        raise ValueError('save directory unavailable')
    paths = sorted(save.rglob('*'))
    if any(p.is_symlink() for p in paths):
        raise ValueError('save directory contains symlinks; refusing ambiguous snapshot')
    destination.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(save)
        data = path.read_bytes()
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        hashes[str(relative)] = hashlib.sha256(data).hexdigest()
    return hashes


def verify_save(save, before, destination):
    after = snapshot(save, destination)
    return after, before == after


def owned_pids(token, prefix, proc=Path('/proc')):
    if not token:
        raise ValueError('empty ownership token')
    root = Path(prefix).resolve()
    required = {b'NIER_RUN_TOKEN=' + token.encode(), b'STEAM_COMPAT_DATA_PATH=' + os.fsencode(root)}

    def in_prefix(value):  # path-component match: /x/prefix2 is not inside /x/prefix
        path = Path(os.fsdecode(value).rstrip('/'))
        return path == root or root in path.parents

    owned = []
    for entry in Path(proc).iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            environment = set((entry / 'environ').read_bytes().split(b'\0'))
        except OSError:
            continue
        if required <= environment:
            owned.append(int(entry.name))
            continue
        # Wine services (winedevice.exe, ...) inherit the prefix but never the token; leaving them orphaned them with
        # no wineserver, spinning (execution-2026-11-14 C2). Another run's token still means not ours.
        if any(e.startswith(b'NIER_RUN_TOKEN=') for e in environment):
            continue
        paths = [e.split(b'=', 1)[1] for e in environment if e.startswith((b'STEAM_COMPAT_DATA_PATH=', b'WINEPREFIX='))]
        if any(p and in_prefix(p) for p in paths):
            owned.append(int(entry.name))
    return sorted(owned)


def cleanup(token, prefix):
    forced = []
    for sig in [signal.SIGTERM, signal.SIGKILL]:
        for pid in owned_pids(token, prefix):
            try:
                fd = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            try:
                # Revalidate after pinning the PID so PID reuse cannot select another process.
                if pid in owned_pids(token, prefix):
                    signal.pidfd_send_signal(fd, sig)
                    if sig == signal.SIGKILL:
                        forced.append(pid)
            except ProcessLookupError:
                pass
            finally:
                os.close(fd)
        if sig == signal.SIGTERM:
            time.sleep(0.2)
    return forced


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['before', 'after'])
    ap.add_argument('--save', required=True, type=Path)
    ap.add_argument('--prefix', required=True, type=Path)
    ap.add_argument('--state', required=True, type=Path)
    args = ap.parse_args()
    if args.action == 'before':
        validate_prefix(args.prefix, args.save)
        # Refuse state reuse; retained diagnostics must never be overwritten.
        args.state.mkdir(parents=True, exist_ok=False)
        hashes = snapshot(args.save, args.state / 'before')
        (args.state / 'before.json').write_text(json.dumps(hashes, indent=2) + '\n')
        print('save guard: validated copied prefix; before snapshot preserved')
        return 0
    before = json.loads((args.state / 'before.json').read_text())
    after, ok = verify_save(args.save, before, args.state / 'after')
    (args.state / 'after.json').write_text(json.dumps(after, indent=2) + '\n')
    print('save guard: real save unchanged' if ok else 'save guard: REAL SAVE CHANGED; both versions preserved; no restoration performed')
    return 0 if ok else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f'save guard: refused: {exc}')
        raise SystemExit(1)
