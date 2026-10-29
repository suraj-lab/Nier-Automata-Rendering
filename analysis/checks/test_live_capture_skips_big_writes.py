#!/usr/bin/env python3
"""Gate: a buffer the game writes through a mapped pointer is only mirrored on the CPU when it is small.

Measured on the real game: with the live scene on, the main thread sat inside the memcpy in note_write reading a
4 MiB mapped buffer (three debugger samples, source pointer + 4194304 = end of the mapping). Wine hands back
write-combined memory, so that read is far slower than a normal copy. Above a threshold the bytes must be dropped
instead, with the identity bumped, so the geometry built from them is rebuilt through the existing bounded
staging read. Small geometry and constant buffers keep the exact behaviour they had.

No D3D device is created: a fake ID3D11Buffer supplies GetDesc, and note_write's other calls are AddRef/Release.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
PREFIX = C.parent / 'runtime/live-geometry/prefix'
SOURCE = r'''
#include "live_capture.h"
#include <cstdio>
#include <vector>

struct FakeBuffer final : ID3D11Buffer {
    ULONG refs = 0;
    int desc_calls = 0;
    D3D11_BUFFER_DESC desc{};
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
    ULONG STDMETHODCALLTYPE Release() override { return --refs; }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID, void** out) override { *out = this; AddRef(); return S_OK; }
    void STDMETHODCALLTYPE GetDevice(ID3D11Device**) override {}
    HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID, UINT*, void*) override { return E_FAIL; }
    HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID, UINT, const void*) override { return E_FAIL; }
    HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID, const IUnknown*) override { return E_FAIL; }
    void STDMETHODCALLTYPE GetType(D3D11_RESOURCE_DIMENSION*) override {}
    void STDMETHODCALLTYPE SetEvictionPriority(UINT) override {}
    UINT STDMETHODCALLTYPE GetEvictionPriority() override { return 0; }
    void STDMETHODCALLTYPE GetDesc(D3D11_BUFFER_DESC* out) override { *out = desc; ++desc_calls; }
};

int main() {
    auto make = [](UINT bytes, UINT binds, D3D11_USAGE usage) {
        auto* b = new FakeBuffer();
        b->desc.ByteWidth = bytes;
        b->desc.BindFlags = binds;
        b->desc.Usage = usage;
        return b;
    };

    // 1. A 4 MiB dynamic vertex buffer: nothing is copied, the identity moves so the mesh is rebuilt.
    FakeBuffer* big = make(4u << 20, D3D11_BIND_VERTEX_BUFFER, D3D11_USAGE_DYNAMIC);
    std::vector<unsigned char> big_data(big->desc.ByteWidth, 0xAB);
    live_capture::note_write(big, big_data.data(), big_data.size());
    const live_capture::Shadow* big_shadow = live_capture::find_shadow(big);
    const bool skipped = big_shadow && big_shadow->bytes.empty() && big_shadow->generation == 1 &&
                         live_capture::skipped_writes.load() == 1 && !big_shadow->trimmable;

    // 2. Small geometry is still mirrored exactly, and marked as written so it is never dropped.
    FakeBuffer* small = make(8u << 10, D3D11_BIND_VERTEX_BUFFER, D3D11_USAGE_DEFAULT);
    std::vector<unsigned char> small_data(small->desc.ByteWidth);
    for (std::size_t i = 0; i < small_data.size(); ++i) small_data[i] = static_cast<unsigned char>(i * 7 + 1);
    live_capture::note_write(small, small_data.data(), small_data.size());
    const live_capture::Shadow* small_shadow = live_capture::find_shadow(small);
    const bool copied = small_shadow && small_shadow->bytes == small_data && small_shadow->written &&
                        !small_shadow->trimmable && live_capture::skipped_writes.load() == 1;

    // 3. Constant buffers are small and are always kept, whatever their flags.
    FakeBuffer* cb = make(64, D3D11_BIND_CONSTANT_BUFFER, D3D11_USAGE_DYNAMIC);
    unsigned char cb_data[64];
    for (int i = 0; i < 64; ++i) cb_data[i] = static_cast<unsigned char>(0xF0 - i);
    live_capture::note_write(cb, cb_data, sizeof cb_data);
    const live_capture::Shadow* cb_shadow = live_capture::find_shadow(cb);
    const bool constant = cb_shadow && cb_shadow->bytes.size() == 64 && cb_shadow->bytes[0] == 0xF0 &&
                          cb_shadow->bytes[63] == 0xB1;

    // 4. The half that matters for accounting: a buffer that IS resident and then grows past the threshold must have
    //    its bytes dropped, shadow_bytes corrected, and its identity (generation) advanced so the mesh rebuilds.
    FakeBuffer* grow = make(8u << 10, D3D11_BIND_VERTEX_BUFFER, D3D11_USAGE_DYNAMIC);
    std::vector<unsigned char> grow_data(grow->desc.ByteWidth, 0x5A);
    live_capture::note_write(grow, grow_data.data(), grow_data.size());
    const std::uint64_t before_identity = live_capture::identity(grow);
    grow->desc.ByteWidth = 4u << 20;  // same buffer object, larger size
    std::vector<unsigned char> grown(grow->desc.ByteWidth, 0x5B);
    live_capture::note_write(grow, grown.data(), grown.size());
    const live_capture::Shadow* grow_shadow = live_capture::find_shadow(grow);
    const std::uint64_t after_identity = live_capture::identity(grow);
    // Resident bytes are now only the 8 KiB `small` buffer and the 64-byte constant buffer.
    const bool dropped = grow_shadow && grow_shadow->bytes.empty() && before_identity != after_identity &&
                         grow_shadow->generation == 2 && live_capture::skipped_writes.load() == 2 &&
                         live_capture::shadow_bytes == (8u << 10) + 64 && grow->refs == 1;

    const ULONG big_refs = big->refs;
    std::printf("skipped=%d copied=%d constant=%d dropped=%d skipped_count=%llu big_refs=%lu desc_calls=%d\n",
                skipped ? 1 : 0, copied ? 1 : 0, constant ? 1 : 0, dropped ? 1 : 0,
                live_capture::skipped_writes.load(), big_refs, big->desc_calls);
    return 0;
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='skipbig-'))
    (work / 'probe.cpp').write_text(SOURCE)
    r = subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-static',
                        '-I', str(C), str(work / 'probe.cpp'), '-o', str(work / 'probe.exe')],
                       capture_output=True, text=True)
    if r.returncode:
        print(json.dumps({'passed': False, 'error': 'build:\n' + r.stderr[-1500:]}, indent=2))
        sys.exit(1)
    env = {**os.environ, 'WINEPREFIX': str(PREFIX), 'WINEDEBUG': '-all'}
    run = subprocess.run(['wine', str(work / 'probe.exe')], capture_output=True, text=True, env=env, timeout=180)
    line = next((l for l in run.stdout.splitlines() if l.startswith('skipped=')), '')
    ok = line == 'skipped=1 copied=1 constant=1 dropped=1 skipped_count=2 big_refs=1 desc_calls=1'
    print(json.dumps({'passed': ok, 'observed': line} if ok else
                     {'passed': False, 'error': f'observed {line!r} (stderr: {run.stderr[-300:]!r})'}, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
