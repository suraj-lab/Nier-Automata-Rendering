#!/usr/bin/env python3
"""Gate: input_layout_hook's store must return the NEWEST elements for a layout pointer (a freed layout's address
is reused by the next CreateInputLayout) and must not grow when the same pointer is recorded again.
Built with mingw, run under the live-geometry Wine prefix; no D3D device is created."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
PREFIX = C.parent / 'runtime/live-geometry/prefix'
SOURCE = r'''
#include "input_layout_hook.h"
#include <cstdio>
int main() {
    auto* fake = reinterpret_cast<ID3D11InputLayout*>(static_cast<std::uintptr_t>(0x12345678));
    std::vector<input_layout_hook::Element> first(1), second(2);
    first[0].semantic = "OLD";
    second[0].semantic = "NEW"; second[1].semantic = "NEW";
    input_layout_hook::record(fake, std::move(first));
    input_layout_hook::record(fake, std::move(second));
    input_layout_hook::Layout out;
    const bool found = input_layout_hook::lookup(fake, out);
    std::printf("found=%d count=%zu first=%s stored=%zu\n", found ? 1 : 0, out.elements.size(),
                out.elements.empty() ? "" : out.elements[0].semantic.c_str(), input_layout_hook::store().size());
    return 0;
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='ilstore-'))
    (work / 'probe.cpp').write_text(SOURCE)
    r = subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-static', '-I', str(C),
                        str(work / 'probe.cpp'), '-o', str(work / 'probe.exe')], capture_output=True, text=True)
    if r.returncode:
        print(json.dumps({'passed': False, 'error': 'build:\n' + r.stderr[-1500:]}, indent=2)); sys.exit(1)
    env = {**os.environ, 'WINEPREFIX': str(PREFIX), 'WINEDEBUG': '-all'}
    run = subprocess.run(['wine', str(work / 'probe.exe')], capture_output=True, text=True, env=env, timeout=120)
    line = next((l for l in run.stdout.splitlines() if l.startswith('found=')), '')
    ok = line == 'found=1 count=2 first=NEW stored=1'
    print(json.dumps({'passed': ok, 'observed': line} if ok else {'passed': False, 'error': f'observed {line!r}'}, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
