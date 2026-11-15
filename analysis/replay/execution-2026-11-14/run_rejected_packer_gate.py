#!/usr/bin/env python3
"""Reproduce the rejected spike's UNIT gate, not integration acceptance."""
import hashlib
import importlib.util
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('pack_capture', root / 'pack_capture_candidate.py')
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)
sys.modules['pack_capture'] = candidate
frozen = root / 'test_pack_capture_content_frozen.py'
assert hashlib.sha256(frozen.read_bytes()).hexdigest() == 'c1fbf90b1a05fa5b1a56a6eb6be4fe9fdcc3becc8bf2687fcb664f96287b1ed1'
virtual_path = root.parents[1] / 'checks/test_pack_capture_content.py'
exec(compile(frozen.read_text(), str(virtual_path), 'exec'), {'__name__': '__main__', '__file__': str(virtual_path)})
