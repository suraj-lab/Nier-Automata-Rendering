#!/usr/bin/env python3
"""Average N Remix post-tonemap DDS frames (legacy header, D3DFMT_A16B16G16R16F) into one 8-bit PNG.

Usage: dds_stack.py <out.png> <a.dds> [b.dds ...]
"""
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

FOURCC_F16 = 113  # D3DFMT_A16B16G16R16F


def load(path):
    d = Path(path).read_bytes()
    if len(d) < 128 or d[:4] != b'DDS ':
        raise ValueError(f'{path}: not a DDS file')
    head = d[4:128]
    h, w = struct.unpack_from('<II', head, 8)
    if struct.unpack_from('<I', head, 80)[0] != FOURCC_F16:
        raise ValueError(f'{path}: not a 16-bit float DDS (fourcc != {FOURCC_F16})')
    px = np.frombuffer(d, '<f2', offset=128)
    if px.size < h * w * 4:
        raise ValueError(f'{path}: truncated payload')
    return px[:h * w * 4].reshape(h, w, 4)[:, :, :3].astype(np.float32)


def main(argv):
    if len(argv) < 3:
        print('usage: dds_stack.py <out.png> <a.dds> [b.dds ...]', file=sys.stderr)
        return 2
    try:
        frames = [load(p) for p in argv[1:]]
        h, w = frames[0].shape[:2]
        if any(f.shape[:2] != (h, w) for f in frames):
            print('dds_stack: frames differ in size', file=sys.stderr)
            return 2
        mean = np.mean(frames, axis=0)
        if not np.isfinite(mean).all():  # a NaN/Inf texel would silently become black in the cast below
            print('dds_stack: non-finite pixel values', file=sys.stderr)
            return 2
        srgb = mean ** (1 / 2.2) * 255
        Image.fromarray(srgb.clip(0, 255).astype(np.uint8)).save(argv[0])
    except (ValueError, OSError) as e:
        print(f'dds_stack: {e}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
