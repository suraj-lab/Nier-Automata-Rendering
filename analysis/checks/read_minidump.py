#!/usr/bin/env python3
"""Read a Windows x64 minidump (e.g. Remix's Sentry/crashpad report) without extra packages.

Usage: python3 analysis/checks/read_minidump.py <file.dmp> [module-substring-to-symbolise ...]
Prints the exception (code, address, module+RVA), the faulting thread's registers, and a heuristic call chain: every
qword on that thread's stack that points into a loaded module's image, as module+RVA. Read-only.
"""
import struct
import sys

STREAM_THREADS, STREAM_MODULES, STREAM_MEM, STREAM_EXCEPTION, STREAM_MEM64 = 3, 4, 5, 6, 9


def main():
    path = sys.argv[1]
    data = open(path, 'rb').read()
    sig, ver, nstreams, dir_rva = struct.unpack_from('<4sIII', data, 0)
    assert sig == b'MDMP', sig
    streams = {}
    for i in range(nstreams):
        kind, size, rva = struct.unpack_from('<III', data, dir_rva + 12 * i)
        streams[kind] = (size, rva)

    def mdstring(rva):
        n = struct.unpack_from('<I', data, rva)[0]
        return data[rva + 4:rva + 4 + n].decode('utf-16-le', 'replace')

    modules = []
    _, rva = streams[STREAM_MODULES]
    count = struct.unpack_from('<I', data, rva)[0]
    for i in range(count):
        base, size, _, _, name_rva = struct.unpack_from('<QIIII', data, rva + 4 + 108 * i)
        modules.append((base, size, mdstring(name_rva)))

    def where(addr):
        for base, size, name in modules:
            if base <= addr < base + size:
                return f'{name.split(chr(92))[-1]}+0x{addr - base:x}'
        return f'0x{addr:x} (no module)'

    # Memory64 list: address -> file offset, for reading the stack.
    ranges = []
    if STREAM_MEM64 in streams:
        _, rva = streams[STREAM_MEM64]
        n, base_rva = struct.unpack_from('<QQ', data, rva)
        off = base_rva
        for i in range(n):
            start, size = struct.unpack_from('<QQ', data, rva + 16 + 16 * i)
            ranges.append((start, size, off))
            off += size

    if STREAM_MEM in streams:  # 32-bit-offset memory list (crashpad writes this one)
        _, rva = streams[STREAM_MEM]
        n = struct.unpack_from('<I', data, rva)[0]
        for i in range(n):
            start, size, off = struct.unpack_from('<QII', data, rva + 4 + 16 * i)
            ranges.append((start, size, off))

    def read(addr, n):
        for start, size, off in ranges:
            if start <= addr and addr + n <= start + size:
                return data[off + addr - start:off + addr - start + n]
        return None

    _, rva = streams[STREAM_EXCEPTION]
    tid, _, code, flags, _, address, nparams, _ = struct.unpack_from('<IIIIQQII', data, rva)
    params = struct.unpack_from('<15Q', data, rva + 8 + 32)[:nparams]
    ctx_size, ctx_rva = struct.unpack_from('<II', data, rva + 8 + 32 + 120)
    print(f'exception      code=0x{code:08x} at {where(address)} (0x{address:x}) thread {tid}')
    if code == 0xc0000005 and len(params) >= 2:
        print(f'               {"write" if params[0] == 1 else "read" if params[0] == 0 else "execute"} of 0x{params[1]:x}')
    names = ['rax', 'rcx', 'rdx', 'rbx', 'rsp', 'rbp', 'rsi', 'rdi', 'r8', 'r9', 'r10', 'r11', 'r12', 'r13', 'r14', 'r15']
    regs = struct.unpack_from('<16Q', data, ctx_rva + 0x78)
    rip = struct.unpack_from('<Q', data, ctx_rva + 0xF8)[0]
    print('registers      ' + ' '.join(f'{n}={v:x}' for n, v in zip(names, regs)))
    print(f'rip            {where(rip)}')
    rsp = regs[4]
    print('stack chain (qwords on the faulting stack that point into a module; heuristic, innermost first):')
    shown = 0
    for i in range(0, 0x4000, 8):
        b = read(rsp + i, 8)
        if b is None:
            break
        v = struct.unpack('<Q', b)[0]
        w = where(v)
        if 'no module' not in w:
            print(f'  rsp+0x{i:04x}  {w}')
            shown += 1
            if shown >= 40:
                break
    want = [s.lower() for s in sys.argv[2:]]
    for base, size, name in modules:
        if not want or any(s in name.lower() for s in want):
            print(f'module         0x{base:x} size 0x{size:x} {name}')


if __name__ == '__main__':
    main()
