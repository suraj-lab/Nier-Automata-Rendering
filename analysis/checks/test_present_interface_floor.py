#!/usr/bin/env python3
"""Gate the real swapchain_slots function against legal COM interface aliases (no D3D device).

A swapchain returned by CreateSwapChainForHwnd is already v1. If querying v1 returns another interface pointer,
copying only 18 base entries loses Present1. Extract the actual function into an x64 Wine probe; fake objects only
implement IUnknown, the only methods the function calls. ABI table sizes remain SDK assertions in test_live_camera.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

C = Path(__file__).resolve().parent
OUT = C.parent / 'runtime/present-overlay-rehook'


def main():
    text = (C / 'menu_overlay.cpp').read_text()
    start = text.index('std::size_t swapchain_slots(')
    function = text[start:text.index('\nvoid adopt(', start)]
    source = r'''
#include <dxgi1_5.h>
#include <utility>
#include <algorithm>
#include <cstddef>
#include <cstdio>
'''+ function + r'''
struct Fake final : IUnknown {
    bool alias = false;
    IUnknown* other = nullptr;
    unsigned releases = 0;
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID, void** out) override { *out = alias ? other : this; return S_OK; }
    ULONG STDMETHODCALLTYPE AddRef() override { return 1; }
    ULONG STDMETHODCALLTYPE Release() override { ++releases; return 1; }
};
int main() {
    Fake f, other; f.other = &other;
    auto* sc = reinterpret_cast<IDXGISwapChain*>(&f);
    int failed = 0;
    // No aliases: all versions share the original vptr and the entire v4 table is copied.
    if (swapchain_slots(sc, 18) != 41 || f.releases != 4) ++failed;
    // A legal alias on QueryInterface: preserve the interface the factory already promised us.
    f.alias = true;
    if (swapchain_slots(sc, 29) != 29) ++failed;
    if (swapchain_slots(sc, 18) != 18) ++failed;
    if (other.releases != 2) ++failed;
    std::printf("failures=%d\n", failed);
    return failed ? 1 : 0;
}
'''
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=OUT) as td:
        d = Path(td)
        (d / 'floor.cpp').write_text(source)
        r = subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-static',
                            str(d / 'floor.cpp'), '-o', str(d / 'floor.exe')], capture_output=True, text=True)
        if r.returncode:
            print(json.dumps({'passed': False, 'error': r.stderr[-1500:]})); return 1
        env = {**os.environ, 'WINEPREFIX': str(OUT / 'prefix'), 'WINEDEBUG': '-all'}
        r = subprocess.run(['wine', str(d / 'floor.exe')], env=env, capture_output=True, text=True, timeout=90)
        print(json.dumps({'passed': r.returncode == 0, 'observed': r.stdout.strip(), 'stderr': r.stderr[-300:]}))
        return 0 if r.returncode == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
