#!/usr/bin/env python3
"""Gate: a pixel shader address reused by a later CreatePixelShader resolves to the NEW bytecode (shader_capture.h).

Found 2026-11-13 (L8): the store was append-only and lookup returned the first match, so after the game released a
shader and the driver reused its address, live_capture read the old shader's disassembly for the new one: lit surfaces
got a shadow caster's alpha test and no roles. The hook is driven natively with a stub CreatePixelShader that returns
the same address twice with different bytecode; lookup must return the second blob and take_reused() must name the
address once (live_capture.h drops its cached PixelInfo for it). Built with mingw, run under Wine (CPU only).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
SRC = r'''
#include "shader_capture.h"
#include <cstdio>
static ID3D11PixelShader* const kSame = reinterpret_cast<ID3D11PixelShader*>(std::uintptr_t(0x5000));
static HRESULT STDMETHODCALLTYPE stub(ID3D11Device*, const void*, SIZE_T, ID3D11ClassLinkage*, ID3D11PixelShader** out) {
    *out = kSame; return S_OK;
}
int main() {
    shader_capture::next().store(reinterpret_cast<void*>(&stub));
    const unsigned char a[8] = {'D','X','B','C',1,1,1,1}, b[8] = {'D','X','B','C',2,2,2,2};
    ID3D11PixelShader* got = nullptr;
    int fails = 0;
    shader_capture::hooked_create_pixel_shader(nullptr, a, sizeof a, nullptr, &got);
    std::vector<unsigned char> code;
    if (!shader_capture::lookup(kSame, code) || code.size() != 8 || code[4] != 1) { std::printf("FAIL first lookup\n"); ++fails; }
    if (!shader_capture::take_reused().empty()) { std::printf("FAIL first creation reported as reuse\n"); ++fails; }
    shader_capture::hooked_create_pixel_shader(nullptr, b, sizeof b, nullptr, &got);
    if (!shader_capture::lookup(kSame, code) || code[4] != 2) { std::printf("FAIL reused address returns the old bytecode\n"); ++fails; }
    const auto reused = shader_capture::take_reused();
    if (reused.size() != 1 || reused[0] != kSame) { std::printf("FAIL reuse not reported\n"); ++fails; }
    if (!shader_capture::take_reused().empty()) { std::printf("FAIL reuse reported twice\n"); ++fails; }
    std::printf("failures=%d\n", fails);
    return fails ? 1 : 0;
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='shader-reuse-', dir=str(Path.home())))
    (work / 't.cpp').write_text(SRC)
    subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-static',
                    '-I', str(C), str(work / 't.cpp'), '-o', str(work / 't.exe')], check=True)
    env = {**os.environ, 'WINEPREFIX': str(work / 'prefix'), 'WINEDEBUG': '-all', 'DISPLAY': ''}
    r = subprocess.run(['wine', str(work / 't.exe')], capture_output=True, text=True, timeout=300, env=env)
    out = r.stdout.strip()
    ok = r.returncode == 0 and 'failures=0' in out
    print(json.dumps({'passed': ok, 'output': out}))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
