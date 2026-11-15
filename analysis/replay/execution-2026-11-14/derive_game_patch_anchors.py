#!/usr/bin/env python3
"""Derive patch anchors for the installed NieRAutomata.exe (read-only).

The three patch headers pin build-specific RVAs. Steam updated the game (installed SHA-256
09854c2d…, pinned-by-comment build was 44ee2dc0…), so `depth patch result: signature-mismatch`
is fail-closed behaviour, not a bug. This script reports, per anchor, whether the current build
still matches, and where the unique equivalent sits if the RVAs moved.

Usage: python3 derive_game_patch_anchors.py [--exe PATH] [--json OUT]
"""
import argparse
import json
import struct
from pathlib import Path

DEFAULT_EXE = Path('/mnt/second/SteamLibrary/steamapps/common/NieRAutomata/NieRAutomata.exe')

# Anchors copied from checks/depth_patch.h, checks/scale_patch.h, checks/proxy_patch.h.
ANCHORS = {
    'depth_prologue': (0x258fe0, bytes([0x48, 0x89, 0x5c, 0x24, 0x20, 0x55, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57])),
    'depth_patch': (0x25904e, bytes([0x89, 0x4d, 0xc0, 0x89, 0x45, 0xc4])),
    'scale_sig1': (0x248179, bytes([0x4c, 0x8b, 0x15, 0x20, 0x70, 0x53, 0x01])),
    'scale_sig2': (0x2481b8, bytes([0xf3, 0x41, 0x0f, 0x59, 0x82, 0x80, 0x00, 0x00, 0x00])),
    'proxy_out_width': (0x18791, bytes([0x45, 0x8b, 0xc5, 0x48, 0x8d, 0x15, 0x35, 0x9e, 0x03, 0x00])),
    'proxy_out_height': (0x187a3, bytes([0x45, 0x8b, 0xc4, 0x48, 0x8d, 0x15, 0x33, 0x9e, 0x03, 0x00])),
    'proxy_output': (0x18006, bytes([0x44, 0x8b, 0xc7, 0x8b, 0xd6])),
}
OLD_RENDERER_GLOBAL = 0x177f1a0


class Image:
    def __init__(self, data):
        self.data = data
        pe = struct.unpack_from('<I', data, 0x3c)[0]
        assert data[pe:pe + 4] == b'PE\0\0'
        count = struct.unpack_from('<H', data, pe + 6)[0]
        opt = pe + 24
        self.image_base = struct.unpack_from('<Q', data, opt + 24)[0]
        sec = opt + struct.unpack_from('<H', data, pe + 20)[0]
        self.sections = []
        for i in range(count):
            name = data[sec + i * 40:sec + i * 40 + 8].rstrip(b'\0').decode('ascii', 'replace')
            vsize, vaddr, rawsize, rawptr = struct.unpack_from('<4I', data, sec + i * 40 + 8)
            self.sections.append({'name': name, 'vaddr': vaddr, 'vsize': vsize, 'rawptr': rawptr, 'rawsize': rawsize})

    def offset(self, rva):
        for s in self.sections:
            if s['vaddr'] <= rva < s['vaddr'] + max(s['vsize'], s['rawsize']):
                delta = rva - s['vaddr']
                return s['rawptr'] + delta if delta < s['rawsize'] else None
        return None

    def rva_of(self, offset):
        for s in self.sections:
            if s['rawptr'] <= offset < s['rawptr'] + s['rawsize']:
                return s['vaddr'] + (offset - s['rawptr'])
        return None

    def read(self, rva, n):
        off = self.offset(rva)
        return None if off is None else self.data[off:off + n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', default=str(DEFAULT_EXE), type=Path)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    data = a.exe.read_bytes()
    image = Image(data)
    import hashlib
    report = {'exe': str(a.exe), 'sha256': hashlib.sha256(data).hexdigest(), 'image_base': hex(image.image_base),
              'anchors': {}}
    for name, (rva, sig) in ANCHORS.items():
        current = image.read(rva, len(sig))
        hits = []
        start = 0
        while True:
            i = data.find(sig, start)
            if i < 0:
                break
            start = i + 1
            hits.append(image.rva_of(i))
        report['anchors'][name] = {'declared_rva': hex(rva), 'matches_at_declared_rva': current == sig,
                                   'equivalent_hits': len(hits), 'first_hits': [hex(h) for h in hits[:4]]}
    # Renderer global: resolve the `mov r10,[rip+disp32]` that feeds the scale multiply.
    sig2 = ANCHORS['scale_sig2'][1]
    sites = []
    start = 0
    while True:
        i = data.find(sig2, start)
        if i < 0:
            break
        start = i + 1
        for back in range(6, 60):
            j = i - back
            if j >= 0 and data[j:j + 3] == b'\x4c\x8b\x15':
                disp = struct.unpack_from('<i', data, j + 3)[0]
                sites.append({'scale_rva': hex(image.rva_of(i)),
                              'load_rva': hex(image.rva_of(j)),
                              'global_rva': hex(image.rva_of(j) + 7 + disp)})
                break
    report['renderer_global'] = {'old': hex(OLD_RENDERER_GLOBAL), 'candidates': sites}
    text = json.dumps(report, indent=2)
    print(text)
    if a.json:
        a.json.write_text(text + '\n')


if __name__ == '__main__':
    main()
