#!/usr/bin/env python3
"""DDS header gate: a DX10 FourCC must have DDPF_FOURCC, or Remix parses zero-bit RGB and divides by zero."""
import importlib.util
import json
import struct
from pathlib import Path


def main():
    p = Path(__file__).resolve().parents[1] / 'remix-probe/scene_from_frame.py'
    spec = importlib.util.spec_from_file_location('scene_converter', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    cases = [('rgba8', m.sky_dds(), 8, 8, 28, 4),
             ('rgba16f', m.sky_dds_hdr(), 128, 64, 10, 8),
             ('rgba16f512', m.sky_dds_hdr(512, 256), 512, 256, 10, 8)]
    for name, b, w, h, fmt, bpp in cases:
        assert b[:4] == b'DDS ' and b[84:88] == b'DX10', name
        assert struct.unpack_from('<II', b, 12) == (h, w), name
        pf_size, pf_flags = struct.unpack_from('<II', b, 76)
        assert pf_size == 32 and pf_flags & 4, name + ': missing DDPF_FOURCC; DX10 text alone does not select a format'
        flags = struct.unpack_from('<I', b, 8)[0]
        assert flags & 8, name + ': DDSD_PITCH required for the recorded row pitch'
        assert struct.unpack_from('<I', b, 20)[0] == w * bpp, name
        caps = struct.unpack_from('<I', b, 108)[0]
        assert caps & 8 and caps & 0x400000 and caps & 0x1000, name + ': mip chain needs COMPLEX/MIPMAP/TEXTURE caps'
        assert struct.unpack_from('<5I', b, 128) == (fmt, 3, 0, 1, 0), name
        size, levels = 0, 0
        while True:
            levels += 1
            size += w * h * bpp
            if w == 1 and h == 1:
                break
            w, h = max(1, w // 2), max(1, h // 2)
        assert struct.unpack_from('<I', b, 28)[0] == levels and len(b) == 148 + size, name
    print(json.dumps({'passed': True, 'cases': len(cases)}))


if __name__ == '__main__':
    try:
        main()
    except AssertionError as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        raise SystemExit(1)
