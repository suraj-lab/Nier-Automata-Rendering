#!/usr/bin/env python3
"""Frozen C3b native DDS gate: full linear-light mip payloads, legacy level zero."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
HARNESS = r'''
#include "terrain_bake.h"
#include <cstdio>
static unsigned u32(const std::vector<unsigned char>& b, unsigned o) {
    unsigned v = 0; std::memcpy(&v, b.data() + o, 4); return v;
}
static bool check(bool ok, const char* why) { if (!ok) std::fprintf(stderr, "%s\n", why); return ok; }
int main() {
    bool ok = true;
    terrain_bake::Image im; im.w = im.h = 512; im.rgba.assign(512 * 512 * 4, 0.25f);
    const auto old = terrain_bake::dds_bytes(im);
    const auto all = terrain_bake::dds_bytes(im, true);
    ok &= check(all.size() == 1398248, "512 full-chain payload size");
    if (all.size() != 1398248) return 1;
    ok &= check(u32(all, 28) == 10, "512 full-chain mip count");
    ok &= check(u32(all, 20) == 2048 && (u32(all, 8) & 0x20000) && !(u32(all, 8) & 0x80000), "pitch/mip flags, no compressed linear-size flag");
    ok &= check((u32(all, 108) & 0x401008) == 0x401008, "mipmap/complex/texture caps");
    ok &= check(old.size() == 148 + 512 * 512 * 4 && u32(old, 28) == 1, "legacy default unchanged");
    ok &= check(std::equal(old.begin() + 148, old.end(), all.begin() + 148), "level zero byte-identical");
    std::size_t offset = 148;
    for (unsigned dim = 512; dim; dim >>= 1) {
        ok &= check(all[offset] == old[148] && all[offset + 3] == old[151], "constant color preserved at each mip offset");
        offset += dim * dim * 4;
    }
    ok &= check(offset == all.size(), "exact final offset");
    terrain_bake::Image two; two.w = two.h = 2;
    two.rgba = {0,0,0,1, 1,1,1,1, 0,0,0,1, 1,1,1,1};
    const auto filtered = terrain_bake::dds_bytes(two, true);
    ok &= check(filtered.size() == 168 && filtered[164] >= 187 && filtered[164] <= 188 && filtered[167] == 255, "linear RGB average, not sRGB-byte average");
    terrain_bake::Image odd; odd.w = 3; odd.h = 1;
    odd.rgba = {0,0,0,1, 0,0,0,1, 1,1,1,1};
    const auto npot = terrain_bake::dds_bytes(odd, true);
    ok &= check(npot.size() == 164 && u32(npot, 28) == 2 && npot[160] >= 155 && npot[160] <= 157, "odd-width tail included in linear average");
    terrain_bake::Image invalid;
    ok &= check(terrain_bake::dds_bytes(invalid, true).empty(), "reject zero-size image");
    invalid.w = invalid.h = 2; invalid.rgba.assign(3, 0.f);
    ok &= check(terrain_bake::dds_bytes(invalid, true).empty(), "reject short pixel payload");
    return ok ? 0 : 1;
}
'''


if __name__ == '__main__':
    try:
        base = C.parent / 'runtime/c3b-mip-gate'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            w = Path(tmp); (w / 'test.cpp').write_text(HARNESS)
            r = subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-I', str(C), str(w / 'test.cpp'), '-o', str(w / 'test')], capture_output=True, text=True)
            assert r.returncode == 0, 'compile failed: ' + r.stderr[-1800:]
            r = subprocess.run([str(w / 'test')], capture_output=True, text=True)
            assert r.returncode == 0, r.stdout + r.stderr
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
