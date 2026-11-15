#!/usr/bin/env python3
"""A0 hidden negatives: copying a private prefix must never follow destination links or replace existing data."""
import json
from pathlib import Path
import sys
import tempfile

C = Path(__file__).resolve().parent
sys.path.insert(0, str(C))
import game_run_safety as safety


def check():
    base = C.parent / 'runtime/a0-private-prefix-hidden'
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as temporary:
        w = Path(temporary)
        template = w / 'template'
        template.mkdir()
        (template / 'payload').write_bytes(b'copied prefix data')
        outside = w / 'not-owned'
        outside.mkdir()
        (outside / 'keep').write_bytes(b'not ours')
        leaf = w / 'leaf'
        leaf.symlink_to(outside / 'missing-prefix', target_is_directory=True)
        parent = w / 'parent'
        parent.symlink_to(outside, target_is_directory=True)
        for destination in [leaf, parent / 'missing-parent-prefix']:
            try:
                safety.prepare_private_prefix(template, destination, 'tok')
            except (ValueError, FileExistsError):
                pass
            else:
                raise AssertionError(f'destination link followed: {destination.name}')
        assert sorted(p.name for p in outside.iterdir()) == ['keep'], 'copy wrote through a destination link'
        assert (outside / 'keep').read_bytes() == b'not ours'
        assert leaf.is_symlink() and parent.is_symlink(), 'caller-owned destination links changed'
        # An existing caller-owned tree is never merged into or overwritten.
        try:
            safety.prepare_private_prefix(template, outside, 'tok')
        except (ValueError, FileExistsError):
            pass
        else:
            raise AssertionError('existing destination was merged')
        # Marker paths and root aliases are not ownership proof.
        private = safety.prepare_private_prefix(template, w / 'private', 'tok')
        proc = w / 'proc'
        (proc / '101').mkdir(parents=True)
        (proc / '101/environ').write_bytes(b'WINEPREFIX=' + str(private).encode() + b'/pfx\0')
        marker = private / '.nier-run-owner.json'
        original = marker.read_bytes()
        marker.unlink()
        saved = w / 'marker-copy'
        saved.write_bytes(original)
        marker.symlink_to(saved)
        assert safety.owned_pids('tok', private, proc=proc) == [], 'symlinked receipt trusted'
        marker.unlink()
        marker.write_bytes(original)
        alias = w / 'private-alias'
        alias.symlink_to(private, target_is_directory=True)
        assert safety.owned_pids('tok', alias, proc=proc) == [], 'aliased root trusted as a private capability'
        parent_alias = w / 'private-parent-alias'
        parent_alias.symlink_to(w, target_is_directory=True)
        assert safety.owned_pids('tok', parent_alias / 'private', proc=proc) == [], 'symlinked prefix ancestor trusted'



if __name__ == '__main__':
    try:
        check()
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
