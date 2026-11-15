#!/usr/bin/env python3
"""Self-check for tools/prune_scratch.py on a fake tree: what it may and may not select."""
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

A = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prune', A / 'tools/prune_scratch.py')
prune = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prune)

root = Path(tempfile.mkdtemp())
(root / 'notes.md').write_text('evidence in runtime/gate-a/run-keepme01\n')
prune.A = root
rt = root / 'runtime'
old = time.time() - 5 * 3600


def mk(rel, age=old):
    p = rt / rel
    p.mkdir(parents=True)
    os.utime(p, (age, age))
    return p


mk('gate-a/run-aaaaaaa1'); mk('gate-a/run-aaaaaaa2'); mk('gate-a/build-aaaaaaa3')
mk('gate-a/run-keepme01')                       # referenced in a .md
mk('gate-a/run-aaaaaaa4', time.time())          # young: possibly in use
mk('gate-a/run-zzzzzzz9', old + 60)             # newest old one... but the young one is newest overall
mk('gate-a/prefix'); mk('gate-a/run-short')     # not scratch names
mk('replay/run-aaaaaaa5'); mk('game-runs/run-aaaaaaa6')
os.symlink(rt / 'gate-a/run-aaaaaaa1', rt / 'gate-a/run-linklink')
(rt / 'gate-a/validation.json').write_text('{}')
mk('gate-b/run-bbbbbbb1')                       # only one: it is the newest, kept

got = {k: sorted(d.name for d in v) for k, v in prune.candidates(rt).items()}
want = {'gate-a': ['build-aaaaaaa3', 'run-aaaaaaa1', 'run-aaaaaaa2', 'run-zzzzzzz9'], 'gate-b': []}
ok = got == want
print(json.dumps({'passed': ok, 'got': got, 'want': want}))
sys.exit(0 if ok else 1)
