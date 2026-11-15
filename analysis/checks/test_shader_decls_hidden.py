#!/usr/bin/env python3
"""Independent malformed-container checks supplement the frozen parser gate."""
import json
import struct
import sys

import dump_shader_decls as parser
from test_shader_decls import container, fixture


def rejected(call, message):
    try:
        call()
    except ValueError:
        return
    raise AssertionError(message)


def main():
    for fields in [(1, 0, 0, 0), (0, 28, 1, 0)]:
        overlap = bytearray(64)
        struct.pack_into('<7I', overlap, 0, *fields, 0xffff0500, 0, 0)
        rejected(lambda: parser.declarations(overlap), 'nonempty RDEF table overlaps header')
    for size in [0, 35, 99999]:
        data = bytearray(container(fixture(5)))
        struct.pack_into('<I', data, 24, size)
        rejected(lambda: parser.chunks(data), 'invalid declared DXBC total size accepted')
    data = bytearray(container(fixture(5)))
    struct.pack_into('<I', data, 32, 0)
    rejected(lambda: parser.chunks(data), 'chunk overlaps container header')
    data = bytearray(fixture(5))
    struct.pack_into('<I', data, 100, 128)
    rejected(lambda: parser.declarations(data), 'variable extends beyond cbuffer size')
    data = bytearray(fixture(5))
    struct.pack_into('<I', data, 16, 0xffff0600)
    rejected(lambda: parser.declarations(data), 'unknown shader model guessed')
    print(json.dumps({'passed': True}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
