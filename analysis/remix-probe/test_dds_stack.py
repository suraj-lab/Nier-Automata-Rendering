#!/usr/bin/env python3
"""Frozen gate for dds_stack.py: average N Remix post-tonemap DDS frames into one PNG.

Usage: test_dds_stack.py <candidate.py>
The candidate CLI is `python3 <candidate> <out.png> <frame.dds> [frame.dds ...]`. It averages the frames in
linear space and writes an 8-bit sRGB PNG. Remix writes these frames with a legacy DDS header (fourcc 113 =
D3DFMT_A16B16G16R16F), 16-bit float RGBA, payload at byte 128.
Prints {"passed": true, "checks": [...]} on success.
"""
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

FOURCC_F16 = 113  # D3DFMT_A16B16G16R16F, what Remix's rtxImagePostTonemapping uses


def write_frame(path, rgb):
    """A legacy-header DDS holding `rgb` (h, w, 3) as 16-bit float RGBA."""
    h, w = rgb.shape[:2]
    head = bytearray(124)
    struct.pack_into('<7I', head, 0, 124, 0x1 | 0x2 | 0x4 | 0x1000, h, w, 8 * w, 0, 1)
    struct.pack_into('<I', head, 72, 32)           # DDS_PIXELFORMAT.dwSize
    head[80:84] = struct.pack('<I', FOURCC_F16)    # dwFourCC
    struct.pack_into('<I', head, 104, 0x1000)      # DDSCAPS_TEXTURE
    px = np.concatenate([rgb, np.ones((h, w, 1), np.float32)], axis=2).astype('<f2')
    Path(path).write_bytes(b'DDS ' + bytes(head) + px.tobytes())


def expect_fail(candidate, args, work, name):
    out = work / 'out.png'
    if out.exists():
        out.unlink()
    p = subprocess.run([sys.executable, str(candidate), str(out), *[str(a) for a in args]],
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 2, f'{name}: exit {p.returncode} (want 2): {p.stderr[-300:]}'
    assert 'Traceback' not in p.stderr, f'{name}: traceback instead of a clean exit'
    assert not out.exists(), f'{name}: wrote output on failure'


def main():
    candidate = Path(sys.argv[1]).resolve()
    work = Path(tempfile.mkdtemp(prefix='dds-stack-'))
    checks = []
    try:
        # 1. Hand-computed average: black + white must land mid-grey after the sRGB encode.
        a = np.zeros((8, 8, 3), np.float32)
        b = np.ones((8, 8, 3), np.float32)
        write_frame(work / 'black.dds', a)
        write_frame(work / 'white.dds', b)
        out = work / 'out.png'
        p = subprocess.run([sys.executable, str(candidate), str(out), str(work / 'black.dds'), str(work / 'white.dds')],
                           capture_output=True, text=True, timeout=300)
        assert p.returncode == 0, f'avg of two frames: exit {p.returncode}: {p.stderr[-400:]}'
        assert out.exists(), 'avg of two frames: no output'
        px = np.asarray(Image.open(out).convert('RGB'), np.float32) / 255.0
        expected = (0.5 ** (1 / 2.2))
        assert abs(float(px.mean()) - expected) < 0.02, f'average is {px.mean():.3f}, want about {expected:.3f}'
        assert float(px.max() - px.min()) < 0.02, 'average is not uniform; frames were not averaged per pixel'
        checks.append(f'black + white average to mid-grey ({px.mean():.3f})')

        # 2. Averaging identical frames must reproduce the single frame.
        write_frame(work / 'g1.dds', a + 0.25)
        write_frame(work / 'g2.dds', a + 0.25)
        p = subprocess.run([sys.executable, str(candidate), str(out), str(work / 'g1.dds'), str(work / 'g2.dds')],
                           capture_output=True, text=True, timeout=300)
        assert p.returncode == 0, f'identical frames: exit {p.returncode}: {p.stderr[-300:]}'
        got = float((np.asarray(Image.open(out).convert('RGB'), np.float32) / 255.0).mean())
        assert abs(got - 0.25 ** (1 / 2.2)) < 0.02, f'identical frames drifted: {got:.3f}'
        checks.append('identical frames reproduce one frame')

        # 3. Mismatched sizes and non-DDS input are clean failures, not tracebacks.
        write_frame(work / 'small.dds', np.zeros((4, 4, 3), np.float32))
        expect_fail(candidate, [work / 'black.dds', work / 'small.dds'], work, 'mismatched sizes')
        (work / 'junk.dds').write_bytes(b'not a dds at all')
        expect_fail(candidate, [work / 'black.dds', work / 'junk.dds'], work, 'non-DDS input')
        # A non-finite payload must be rejected, not averaged into a silently black frame.
        write_frame(work / 'nan.dds', np.full((8, 8, 3), np.nan, np.float32))
        expect_fail(candidate, [work / 'black.dds', work / 'nan.dds'], work, 'NaN payload')
        checks.append('mismatched sizes, non-DDS input and NaN payload exit 2')

        print(json.dumps({'passed': True, 'checks': checks}, indent=2))
    except AssertionError as e:
        print(json.dumps({'passed': False, 'error': str(e), 'checks_passed': checks}, indent=2))
        sys.exit(1)
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
