#!/usr/bin/env python3
"""Frozen T1.2: unsigned R11G11B10 decoding with HDR preservation; existing raw header, not a new format."""
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import numpy as np
from PIL import Image

C = Path(__file__).resolve().parent
A = C.parent
sys.path.insert(0, str(A / 'replay'))


def reference(bits, fraction_bits):
    exp, mantissa = bits >> fraction_bits, bits & ((1 << fraction_bits) - 1)
    if exp == 31: return math.inf if mantissa == 0 else math.nan
    if exp == 0: return math.ldexp(mantissa, -14-fraction_bits)
    return math.ldexp(1 + mantissa / (1 << fraction_bits), exp-15)


def check():
    path = A / 'replay/raw_image.py'
    assert path.is_file(), 'R11G11B10 raw decoder absent'
    spec = importlib.util.spec_from_file_location('raw_hdr_candidate', path)
    candidate = importlib.util.module_from_spec(spec); spec.loader.exec_module(candidate)
    decode = getattr(candidate, 'decode_raw', None)
    assert callable(decode), 'decode_raw entry point absent'
    # Independent hand-computed values; R/G subnormal step differs from B.
    assert reference(1,6) == 2**-20 and reference(1,5) == 2**-19
    assert reference(15 << 6,6) == 1 and reference(16 << 6,6) == 2 and reference(17 << 5,5) == 4
    words = [r | ((2047-r) << 11) | ((r % 1024) << 22) for r in range(2048)]
    raw = struct.pack('<3I',2048,1,26) + struct.pack('<2048I',*words)
    rgb = decode(raw)
    assert isinstance(rgb,np.ndarray) and rgb.shape == (1,2048,3) and rgb.dtype == np.float32
    want = np.array([[reference(r,6),reference(2047-r,6),reference(r % 1024,5)] for r in range(2048)],dtype=np.float32)[None]
    assert np.array_equal(np.isnan(rgb),np.isnan(want)), 'NaN lost/clamped'
    assert np.array_equal(np.isposinf(rgb),np.isposinf(want)), 'positive infinity lost/clamped'
    mask = np.isfinite(want)
    assert np.array_equal(rgb[mask],want[mask]), 'wrong exponent/mantissa/channel layout'
    assert not np.signbit(rgb[rgb == 0]).any(), 'unsigned zero gained a sign'
    assert float(np.nanmax(np.where(np.isfinite(rgb),rgb,0))) > 60000, 'HDR range clamped or gamma fitted'
    for invalid in [b'',raw[:11],raw[:-1],raw+b'\0',struct.pack('<3I',0,1,26),struct.pack('<3I',0xffffffff,0xffffffff,26),struct.pack('<3I',1,1,10)+b'\0'*4]:
        try: decode(invalid)
        except ValueError: pass
        else: raise AssertionError('malformed/unsupported raw silently decoded')
    import run_replay
    base = A / 'runtime/raw-hdr-gate'; base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as temporary:
        w=Path(temporary)
        pixels=np.array([[[0,1,127,255],[128,254,255,0]],[[255,0,128,32],[2,3,4,64]]],dtype=np.uint8)
        for fmt in [28,29,87,91]:
            stored=pixels[..., [2,1,0,3]] if fmt in (87,91) else pixels
            body=struct.pack('<3I',2,2,fmt)+stored.tobytes()
            decoded=decode(body)
            assert np.array_equal(decoded,pixels[...,:3].astype(np.float32)/np.float32(255)), '8-bit channel/transfer changed'
            p=w/f'{fmt}.raw';p.write_bytes(body)
            png=w/f'{fmt}.png';run_replay.raw_to_png(p,png)
            assert np.array_equal(np.asarray(Image.open(png).convert('RGB')),pixels[...,:3]), 'legacy PNG bytes changed'
            assert p.read_bytes()==body, 'decoder normalized original raw in place'
        hdr=w/'hdr.raw';hdr.write_bytes(raw)
        target=w/'existing.png';target.write_bytes(b'keep prior artifact')
        try:run_replay.raw_to_png(hdr,target)
        except ValueError as exc:assert 'HDR' in str(exc) or 'float' in str(exc)
        else:raise AssertionError('HDR was silently written as clamped/misinterpreted 8-bit PNG')
        assert target.read_bytes()==b'keep prior artifact' and hdr.read_bytes()==raw


if __name__=='__main__':
    try:
        check();print(json.dumps({'passed':True}))
    except Exception as exc:
        print(json.dumps({'passed':False,'error':str(exc)[:1700]}));sys.exit(1)
