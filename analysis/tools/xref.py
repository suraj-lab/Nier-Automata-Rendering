#!/usr/bin/env python3
"""Find code references to a string or address in a PE image, without a disassembler database.

The REA MCP server is not configured for Ghidra in this environment, and the interesting questions
here are of the form "which code reads this option name" (useDenoiser, the DDS parser, the capture
env vars). This answers that: locate the data, then scan code for RIP-relative operands that resolve
to it. Every hit is re-decoded with objdump so a false positive is visible rather than assumed.

Usage:
  xref.py <pe> --string useDenoiser [--limit N] [--verify]   # also matches wider strings containing it
  xref.py <pe> --va 0x190d96018
"""
import re
import struct
import subprocess
import sys


def sections(data):
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    opt_size = struct.unpack_from('<H', data, pe + 20)[0]
    nsections = struct.unpack_from('<H', data, pe + 6)[0]
    opt = pe + 24
    pe64 = struct.unpack_from('<H', data, opt)[0] == 0x20b
    image_base = struct.unpack_from('<Q' if pe64 else '<I', data, opt + (24 if pe64 else 28))[0]
    out = []
    sec = opt + opt_size
    for i in range(nsections):
        name = data[sec + i * 40:sec + i * 40 + 8].rstrip(b'\0').decode('latin-1')
        vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', data, sec + i * 40 + 8)
        out.append({'name': name, 'va': image_base + vaddr, 'vsize': vsize,
                    'off': rawptr, 'rawsize': rawsize})
    return image_base, out


def off_to_va(sects, off):
    for s in sects:
        if s['off'] <= off < s['off'] + s['rawsize']:
            return s['va'] + (off - s['off'])
    return None


def main():
    path = sys.argv[1]
    data = open(path, 'rb').read()
    image_base, sects = sections(data)
    limit = 20
    verify = '--verify' in sys.argv
    for i, a in enumerate(sys.argv):
        if a == '--limit':
            limit = int(sys.argv[i + 1])

    targets = []  # (va, label)
    if '--string' in sys.argv:
        needle = sys.argv[sys.argv.index('--string') + 1].encode()
        for m in re.finditer(re.escape(needle), data):
            va = off_to_va(sects, m.start())
            if va is None:
                continue
            end = data.find(b'\0', m.start())
            label = data[m.start():end if end != -1 else m.start() + len(needle)].decode('latin-1')[:60]
            targets.append((va, f'string @{va:#x} {label!r}'))
    elif '--va' in sys.argv:
        targets.append((int(sys.argv[sys.argv.index('--va') + 1], 0), 'explicit'))
    else:
        print('need --string or --va', file=sys.stderr)
        sys.exit(2)

    code = [s for s in sects if s['name'] == '.text']
    if not code:
        print('no .text section', file=sys.stderr)
        sys.exit(2)
    text = code[0]
    print(f'{path}: image base {image_base:#x}, .text {text["vsize"]:#x} bytes at VA {text["va"]:#x}')

    for target_va, label in targets:
        print(f'\n=== {label} ===')
        hits = []
        for s in code:
            blob = data[s['off']:s['off'] + s['rawsize']]
            for i in range(3, len(blob) - 4):
                disp = struct.unpack_from('<i', blob, i)[0]
                if (s['va'] + i + 4 + disp) == target_va:
                    # Step back over the instruction prefix that precedes the disp32. `lea r,[rip+..]` is
                    # 48 8D /r (3 bytes), `call [rip+..]` is FF 15 (2 bytes) and its REX form is 3. Getting
                    # this wrong silently reports off-by-one addresses (seen 2026-10-27 on NieR's IAT xrefs).
                    if i >= 2 and blob[i - 2] == 0xFF and blob[i - 1] == 0x15:
                        start = s['va'] + i - 2
                    elif i >= 3 and blob[i - 3] in (0x48, 0x4C) and blob[i - 2] == 0xFF and blob[i - 1] == 0x15:
                        start = s['va'] + i - 3
                    else:
                        start = s['va'] + i - 3
                    hits.append(start)
        print(f'  {len(hits)} candidate reference(s)')
        for va in hits[:limit]:
            line = ''
            if verify:
                p = subprocess.run(['x86_64-w64-mingw32-objdump', '-d', '--no-show-raw-insn', '-M', 'intel',
                                    f'--start-address={va}', f'--stop-address={va + 10}', path],
                                   capture_output=True, text=True, timeout=300)
                body = [l.split('\t')[-1].strip() for l in p.stdout.splitlines()
                        if re.match(r'^\s+[0-9a-f]+:', l)]
                line = body[0] if body else '(no decode)'
            print(f'   ref @{va:#x}  {line}')


if __name__ == '__main__':
    main()
