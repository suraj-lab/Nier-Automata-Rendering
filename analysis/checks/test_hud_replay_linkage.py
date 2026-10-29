#!/usr/bin/env python3
"""Gate: hud_replay's PS inputs sit in the same registers as its VS outputs.

DXVK links stages by register, Wine's GL path by semantic, so the Wine mocks cannot see a mismatch. Live 2026-10-29:
the PS lacked SV_POSITION, read the pixel position as uv, and the whole frame became one clamped corner texel.
Compiles the exact shader strings from hud_replay.h (Wine D3DCompile) and compares signature registers.
"""
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
OUT = C.parent / 'runtime/hud-linkage'
HELPER = r'''
#include <windows.h>
#include <d3dcompiler.h>
#include <cstdio>
#include <cstring>
#include <vector>
typedef HRESULT (WINAPI *Compile)(LPCVOID, SIZE_T, LPCSTR, const D3D_SHADER_MACRO*, ID3DInclude*, LPCSTR, LPCSTR, UINT, UINT, ID3DBlob**, ID3DBlob**);
int main(int argc, char** argv) {  // in out profile
    if (argc != 4) return 2;
    HMODULE m = LoadLibraryA("d3dcompiler_47.dll");
    Compile c = m ? reinterpret_cast<Compile>(GetProcAddress(m, "D3DCompile")) : nullptr;
    FILE* f = std::fopen(argv[1], "rb"); if (!c || !f) return 3;
    std::vector<char> src(1 << 16); size_t n = std::fread(src.data(), 1, src.size(), f); std::fclose(f);
    ID3DBlob* b = nullptr; ID3DBlob* e = nullptr;
    if (FAILED(c(src.data(), n, "s", nullptr, nullptr, "main", argv[3], 0, 0, &b, &e))) {
        if (e) std::fprintf(stderr, "%s", static_cast<char*>(e->GetBufferPointer())); return 4;
    }
    FILE* o = std::fopen(argv[2], "wb"); std::fwrite(b->GetBufferPointer(), 1, b->GetBufferSize(), o); std::fclose(o);
    return 0;
}
'''


def signature(blob, tag):
    count = struct.unpack_from('<I', blob, 28)[0]
    for off in struct.unpack_from('<' + 'I' * count, blob, 32):
        if blob[off:off + 4] == tag:
            z = blob[off + 8:off + 8 + struct.unpack_from('<I', blob, off + 4)[0]]
            out = {}
            for i in range(struct.unpack_from('<I', z, 0)[0]):
                name, idx, sv, typ, reg, mask, rw = struct.unpack_from('<5I2B2x', z, 8 + 24 * i)
                out[(z[name:].split(b'\0', 1)[0].decode().upper(), idx)] = reg
            return out
    raise AssertionError(f'{tag} missing')


def source(text, name):
    m = re.search(r'static const char ' + name + r'\[\] =\s*((?:(?:\s*//[^\n]*)*\s*"(?:[^"\\]|\\.)*")+)\s*;', text)
    assert m, f'{name} not found in hud_replay.h'
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', re.sub(r'//[^\n]*', '', m.group(1)))
    return ''.join(parts).encode().decode('unicode_escape')


def main():
    text = (C / 'hud_replay.h').read_text()
    OUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, WINEPREFIX=str(OUT / 'prefix'), WINEDEBUG='-all', WINEDLLOVERRIDES='winemenubuilder.exe=d;mscoree,mshtml=')
    with tempfile.TemporaryDirectory(dir=OUT) as tmp:
        w = Path(tmp)
        (w / 'h.cpp').write_text(HELPER)
        subprocess.run(['x86_64-w64-mingw32-g++', '-O2', '-static', str(w / 'h.cpp'), '-o', str(w / 'h.exe')], check=True)
        blobs = {}
        for name, profile in [('vs_src', 'vs_4_0'), ('ps_src', 'ps_4_0')]:
            (w / f'{name}.hlsl').write_text(source(text, name))
            r = subprocess.run(['wine', str(w / 'h.exe'), str(w / f'{name}.hlsl'), str(w / f'{name}.dxbc'), profile],
                               env=env, capture_output=True, text=True, timeout=120)
            assert r.returncode == 0, f'{name} compile failed: {r.stderr[-800:]}'
            blobs[name] = (w / f'{name}.dxbc').read_bytes()
    vs_out = signature(blobs['vs_src'], b'OSGN')
    ps_in = signature(blobs['ps_src'], b'ISGN')
    for key, reg in ps_in.items():
        assert key in vs_out, f'PS input {key} not written by VS'
        assert vs_out[key] == reg, f'PS input {key} in register {reg}, VS writes it to {vs_out[key]} (DXVK links by register)'
    print(json.dumps({'passed': True, 'vs_out': {f'{k[0]}{k[1]}': v for k, v in vs_out.items()},
                      'ps_in': {f'{k[0]}{k[1]}': v for k, v in ps_in.items()}}))


if __name__ == '__main__':
    try:
        main()
    except (AssertionError, subprocess.SubprocessError) as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
