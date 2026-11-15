#!/usr/bin/env python3
"""Delete gate scratch folders: analysis/runtime/<gate>/<run|build|session|hidden|upscaler>-<8 chars>.

  prune_scratch.py            dry run: counts per gate folder, nothing deleted
  prune_scratch.py --delete   delete them

Kept always: the newest scratch folder per gate folder, anything modified in the last 2 hours (a running gate),
anything whose folder name appears in a receipt, the plan or another analysis/*.md, and the evidence folders below.
Files directly in a gate folder (validation.json, mutations.json, ...) are never touched.
"""
import re
import shutil
import sys
import time
from pathlib import Path

A = Path(__file__).resolve().parents[1]
RUNTIME = A / 'runtime'
KEEP_PARENTS = {'replay', 'game-runs', 'auto', 'remix-probe', 'native-hud', 'menu-preview', 'tmp', 'hud-evidence'}
SCRATCH = re.compile(r'(run|build|session|hidden|upscaler)-[a-z0-9_]{8}')
MIN_AGE_S = 2 * 3600


def referenced_text():
    docs = list(A.glob('*.md')) + list((A / 'replay').rglob('*.md'))
    return '\n'.join(p.read_text(errors='replace') for p in docs)


def candidates(runtime=RUNTIME, now=None):
    now = time.time() if now is None else now
    refs = referenced_text()
    out = {}
    for parent in sorted(p for p in runtime.iterdir() if p.is_dir() and not p.is_symlink()):
        if parent.name in KEEP_PARENTS:
            continue
        found = [d for d in parent.iterdir()
                 if d.is_dir() and not d.is_symlink() and SCRATCH.fullmatch(d.name)]
        if not found:
            continue
        found.sort(key=lambda d: d.stat().st_mtime)
        newest = found[-1]
        out[parent.name] = [d for d in found if d != newest and now - d.stat().st_mtime > MIN_AGE_S
                            and d.name not in refs]
    return out


def main():
    delete = '--delete' in sys.argv
    plan = candidates()
    total = 0
    for parent, dirs in plan.items():
        if dirs:
            print(f'{len(dirs):5d}  {parent}')
            total += len(dirs)
    print(f'{total} scratch folders {"deleted" if delete else "would be deleted (dry run; pass --delete)"}')
    if delete:
        for dirs in plan.values():
            for d in dirs:
                # the tree is ours (gate scratch); never follow links out of it
                assert d.resolve().is_relative_to(RUNTIME.resolve()) and not d.is_symlink(), d
                shutil.rmtree(d)


if __name__ == '__main__':
    main()
