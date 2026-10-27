#!/usr/bin/env python3
"""Minimal PE export/import reader, no third-party modules.

The .trex runtime and NvRemixBridge are the two modules the interop question depends on, and the analysis
box has no pefile. Reads the export name table and the imported DLL names only -- enough to answer "which
entry points does this build actually expose", which the earlier probes had to guess at.

Usage: pe_info.py <file.dll> [--grep prefix[,prefix...]] [--json]
"""
import json
import struct
import sys


def read_sections(data):
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    opt_size = struct.unpack_from('<H', data, pe + 20)[0]
    nsections = struct.unpack_from('<H', data, pe + 6)[0]
    opt = pe + 24
    pe64 = struct.unpack_from('<H', data, opt)[0] == 0x20b
    image_base = struct.unpack_from('<Q' if pe64 else '<I', data, opt + (24 if pe64 else 28))[0]
    sections = []
    sec = opt + opt_size
    for i in range(nsections):
        name = data[sec + i * 40:sec + i * 40 + 8].rstrip(b'\0').decode('latin-1')
        vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', data, sec + i * 40 + 8)
        sections.append({'name': name, 'va': image_base + vaddr, 'vsize': vsize,
                         'off': rawptr, 'rawsize': rawsize})
    return image_base, sections


def read(path):
    data = open(path, 'rb').read()
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    assert data[pe:pe + 4] == b'PE\0\0', 'not a PE image'
    machine, nsections = struct.unpack_from('<HH', data, pe + 4)
    opt_size = struct.unpack_from('<H', data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from('<H', data, opt)[0]
    pe64 = magic == 0x20b
    # Data directories start after the optional header's fixed part.
    dd = opt + (112 if pe64 else 96)
    image_base, _secs = read_sections(data)
    sections = [(s['name'], s['va'] - image_base, s['vsize'], s['off'], s['rawsize']) for s in _secs]

    def off(rva):  # RVA -> file offset
        for _, vaddr, size, rawptr, rawsize in sections:
            if vaddr <= rva < vaddr + size:
                delta = rva - vaddr
                if delta >= rawsize:
                    return None
                return rawptr + delta
        return None

    def cstr(rva):
        o = off(rva)
        if o is None:
            return None
        end = data.index(b'\0', o)
        return data[o:end].decode('latin-1')

    out = {'path': path, 'machine': machine, 'pe64': pe64, 'exports': [], 'imports': []}
    exp_rva, exp_size = struct.unpack_from('<II', data, dd)
    if exp_rva:
        e = off(exp_rva)
        n_names = struct.unpack_from('<I', data, e + 24)[0]
        names_rva, ords_rva = struct.unpack_from('<II', data, e + 32)
        for i in range(n_names):
            nrva = struct.unpack_from('<I', data, off(names_rva) + i * 4)[0]
            ordinal = struct.unpack_from('<H', data, off(ords_rva) + i * 2)[0]
            name = cstr(nrva)
            fn_rva = struct.unpack_from('<I', data, off(exp_rva + 40) + ordinal * 4)[0]
            out['exports'].append({'name': name, 'ordinal': ordinal, 'rva': fn_rva,
                                   'forwarder': bool(exp_rva <= fn_rva < exp_rva + exp_size)})
    imp_rva = struct.unpack_from('<I', data, dd + 8)[0]
    if imp_rva:
        o = off(imp_rva)
        while True:
            desc = data[o:o + 20]
            if len(desc) < 20 or not any(desc):
                break
            name_rva = struct.unpack_from('<I', desc, 12)[0]
            out['imports'].append({'dll': cstr(name_rva), 'first_thunk': struct.unpack_from('<I', desc, 0)[0]})
            o += 20
    out['image_base'] = image_base
    return out


def import_names(path):
    """Resolve every imported function to its IAT slot VA, so xref.py can find call sites."""
    data = open(path, 'rb').read()
    image_base, sects = read_sections(data)
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    opt = pe + 24
    pe64 = struct.unpack_from('<H', data, opt)[0] == 0x20b
    dd = opt + (112 if pe64 else 96)
    imp_rva = struct.unpack_from('<I', data, dd + 8)[0]
    out = []
    if not imp_rva:
        return image_base, out

    class _S:
        pass

    st = [_S() for _ in sects]
    for o, s in zip(st, sects):
        o.name, o.va, o.vsize, o.off, o.rawsize = s['name'], s['va'], s['vsize'], s['off'], s['rawsize']

    def off(rva):
        va = image_base + rva
        for s in st:
            if s.va <= va < s.va + s.rawsize:
                return s.off + (va - s.va)
        return None

    def cstr(rva):
        o = off(rva)
        if o is None:
            return None
        return data[o:data.index(b'\0', o)].decode('latin-1')

    step = 8 if pe64 else 4
    mask = (1 << 63) if pe64 else (1 << 31)
    o = off(imp_rva)
    while True:
        desc = data[o:o + 20]
        if len(desc) < 20 or not any(desc):
            break
        ilt, _, _, name_rva, iat = struct.unpack_from('<IIIII', desc)
        dll = cstr(name_rva)
        table = ilt or iat
        i = 0
        while True:
            slot = off(table + i * step)
            if slot is None:
                break
            entry = struct.unpack_from('<Q' if pe64 else '<I', data, slot)[0]
            if entry == 0:
                break
            slot_va = image_base + iat + i * step
            if entry & mask:
                name = f'ordinal{entry & 0xffff}'
            else:
                name = cstr((entry & 0x7fffffff) + 2)  # skip the 2-byte hint
            out.append({'dll': dll, 'name': name, 'slot_va': slot_va})
            i += 1
        o += 20
    return image_base, out


def main():
    path = sys.argv[1]
    prefixes = None
    as_json = '--json' in sys.argv
    for a in sys.argv[2:]:
        if a.startswith('--imports'):
            image_base, imports = import_names(path)
            want = a.split('=', 1)[1].lower() if '=' in a else ''
            hits = [i for i in imports if want in (i['dll'] or '').lower()]
            print(f'{path}: {len(hits)} imported symbol(s) from DLLs matching {want!r}')
            for i in hits:
                print(f"  {i['dll']}!{i['name']}  slot={i['slot_va']:#x}")
            return
        if a.startswith('--grep'):
            prefixes = a.split('=', 1)[1].split(',') if '=' in a else None
    info = read(path)
    if prefixes is not None:
        info['exports'] = [e for e in info['exports'] if any((e['name'] or '').startswith(p) for p in prefixes)]
    if as_json:
        print(json.dumps(info, indent=2))
        return
    print(f"{path}: {'PE32+' if info['pe64'] else 'PE32'}, "
          f"{len(info['exports'])} exports, {len(info['imports'])} imported DLLs")
    for e in info['exports']:
        print(f"  export {e['name'] or '(ordinal ' + str(e['ordinal']) + ')'}"
              f"{' [forwarder]' if e['forwarder'] else ''}")
    for i in info['imports']:
        print(f"  import {i['dll']}")


if __name__ == '__main__':
    main()
