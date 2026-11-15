#!/usr/bin/env python3
"""Frozen A0 RDEF fixture gate; optional candidate module path for isolated workers."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys


def fixture(major):
    stride = 40 if major >= 5 else 24
    b = bytearray(300)
    struct.pack_into('<7I', b, 0, 1, 64, 1, 32, 0xffff0000 | major << 8, 0, 240)
    struct.pack_into('<8I', b, 32, 240, 0, 0, 0, 0, 2, 1, 0)
    struct.pack_into('<6I', b, 64, 240, 2, 96, 128, 0, 0)
    struct.pack_into('<6I', b, 96, 248, 16, 16, 0, 0, 0)
    struct.pack_into('<6I', b, 96 + stride, 256, 64, 16, 0, 0, 0)
    b[240:244] = b'CB2\0'
    b[248:254] = b'light\0'
    b[256:260] = b'fog\0'
    return bytes(b)


def container(payload):
    b = bytearray(44)
    b[:4] = b'DXBC'
    struct.pack_into('<III', b, 24, len(b) + len(payload), 1, 36)
    b[36:40] = b'RDEF'
    struct.pack_into('<I', b, 40, len(payload))
    return bytes(b) + payload


def check(candidate):
    for major in [4, 5]:
        rdef = fixture(major)
        assert candidate.declarations(rdef) == ([('CB2', 128, [('light', 16, 16), ('fog', 64, 16)])], [('CB2', 'cbuffer', 2, 1)]), f'SM{major}: wrong RDEF origin/stride'
        assert candidate.chunks(container(rdef)) == {'RDEF': [rdef]}
        for truncated in [rdef[:12], rdef[:75], rdef[:110], rdef[:258]]:
            try:
                candidate.declarations(truncated)
            except ValueError:
                pass
            else:
                raise AssertionError('truncated RDEF accepted')
        bad = bytearray(rdef)
        struct.pack_into('<I', bad, 96, 99999)
        try:
            candidate.declarations(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('out-of-bounds variable name accepted')
    for bad in [b'DXBC', container(fixture(5))[:-1], container(fixture(5))[:35]]:
        try:
            candidate.chunks(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('truncated DXBC accepted')
    assert candidate.chunks(b'not DXBC') == {}
    # Independent real shader assertions, when locally available; never download fixtures.
    shaders = Path(__file__).resolve().parents[1] / 'runtime/laptop-play-20261114/shaders'
    checked = []
    for name, variable, offset in [('ps_550344741192.dxbc', 'g_lightColor', 0), ('ps_550347548488.dxbc', 'g_WaterFogParam', 208)]:
        path = shaders / name
        if not path.exists():
            continue
        data = path.read_bytes()
        cb, _ = candidate.declarations(candidate.chunks(data)['RDEF'][0])
        assert any(v == variable and start == offset for _, _, variables in cb for v, start, _ in variables), name + ': real declaration mismatch'
        checked.append({'file': name, 'sha256': hashlib.sha256(data).hexdigest()})
    return checked


if __name__ == '__main__':
    try:
        path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name('dump_shader_decls.py')
        spec = importlib.util.spec_from_file_location('candidate_shader_decls', path)
        candidate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(candidate)
        real = check(candidate)
        print(json.dumps({'passed': True, 'real_fixtures': real}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
