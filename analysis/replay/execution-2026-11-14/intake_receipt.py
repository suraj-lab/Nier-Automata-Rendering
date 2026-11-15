#!/usr/bin/env python3
"""One-shot, read-only raw capture audit; manifests and packs go to a new runtime receipt."""
import hashlib
import json
from pathlib import Path
import sys
import time

A = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pack_capture_candidate as pack_capture  # Isolated rejected spike, never the production packer.


def inventory(root):
    rows = []
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            raise ValueError(f'raw symlink requires provenance review: {p}')
        if p.is_file():
            s = p.stat()
            rows.append((p.relative_to(root).as_posix(), s.st_size, s.st_mtime_ns))
    return rows


def main():
    out = A / 'runtime/a1-intake-20261114'
    out.mkdir(exist_ok=False)
    expected = {'frame_67279062': (22380, 5813513277), 'frame_67078468': (29363, 14317920437)}
    summary = {}
    for name, counts in expected.items():
        raw = A / 'runtime/laptop-play-20261114' / name
        before = inventory(raw)
        assert (len(before), sum(row[1] for row in before)) == counts, f'{name}: transfer inventory changed'
        manifest = out / (name + '.jsonl')
        started = time.monotonic()
        with manifest.open('x') as stream:
            for relative, size, _ in before:
                p = raw / relative
                with p.open('rb') as source:
                    digest = hashlib.file_digest(source, 'sha256').hexdigest()
                stream.write(json.dumps({'path': relative, 'bytes': size, 'sha256': digest}, sort_keys=True) + '\n')
        assert inventory(raw) == before, 'capture changed during local hashing'
        pack_started = time.monotonic()
        packed = pack_capture.pack(raw, out / name, dedup_content=True)
        assert inventory(raw) == before, 'packer modified raw capture'
        summary[name] = {'files': counts[0], 'bytes': counts[1], 'local_manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
                         'hash_seconds': round(pack_started - started, 3), 'pack_seconds': round(time.monotonic() - pack_started, 3),
                         'packed': packed, 'raw_stat_inventory_unchanged': True, 'source_hash_verified': False,
                         'accepted': False, 'provenance': 'Transfer counts/sizes matched planning inventory; no remote source SHA-256 manifest available. Content candidate later rejected on geometry regression.'}
        print(name, json.dumps(summary[name]), flush=True)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    main()
