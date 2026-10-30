#!/usr/bin/env python3
"""Print per-section SHA-256 of PE files.

Why: `build_menu_dll.py` links with `--no-insert-timestamp` but ld still picks a different image base per output path,
and MinGW's static libstdc++/libgcc bring ~10 MB of DWARF whose addresses follow that base. Whole-file hashes of the
same sources therefore differ between build directories. Only `.text` is base-independent: compare `.text` to decide
whether two DLLs were built from the same source, and treat a whole-file match as "same build directory".

  python3 analysis/tools/pe_sections.py a.dll b.dll
"""
import hashlib
import pathlib
import re
import subprocess
import sys


def sections(path):
    out = subprocess.run(['x86_64-w64-mingw32-objdump', '-h', path], capture_output=True, text=True, check=True).stdout
    data = pathlib.Path(path).read_bytes()
    found = {}
    for m in re.finditer(r'^\s+\d+ (\S+)\s+([0-9a-f]+)\s+[0-9a-f]+\s+[0-9a-f]+\s+([0-9a-f]+)', out, re.M):
        name, size, off = m.group(1), int(m.group(2), 16), int(m.group(3), 16)
        if size and off:
            found[name] = hashlib.sha256(data[off:off + size]).hexdigest()
    return found


def main():
    paths = sys.argv[1:]
    if not paths:
        print(__doc__)
        return 2
    names = [pathlib.Path(p).name for p in paths]
    table = [sections(p) for p in paths]
    keys = [k for k in ('.text', '.rdata', '.data', '.idata', '.edata', '.reloc') if any(k in t for t in table)]
    print('file            ' + ''.join(f'{n[:20]:>22}' for n in names))
    print('sha256 (whole)  ' + ''.join(f'{hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()[:20]:>22}' for p in paths))
    for k in keys:
        row = [t.get(k, '-')[:20] for t in table]
        print(f'{k:15} ' + ''.join(f'{v:>22}' for v in row) + ('' if len(set(row)) == 1 else '  differs'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
