#!/usr/bin/env python3
"""Gate: the Remix materials we create are opaque, filtered and repeating unless a cutout is asked for.

nscn::detail::make_material_info is used by both the captured-scene and the live path. Before 2026-10-29 it left
MaterialInfo zero-initialised (filterMode 0 = nearest, wrapMode 0 = clamp) and enabled blending (blendType_hasvalue 1,
type 2) with alphaTestType 0 (kNever): every surface was see-through by its texture alpha, tiled textures smeared into
streaks, and textures were blocky (laptop A/B renders of capture frame_23275488). Values follow NVIDIA's remix.h
defaults: filter 1 linear, wrap 1 repeat, no blending, alpha test 7 kAlways; cutout = alpha test 4 kGreater at 128.
mingw + Wine (remix_c.h includes windows.h); no GPU.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
SRC = r'''
#include <cstdio>
#include "nscn_scene.h"
int main() {
    for (int cutout = 0; cutout < 2; ++cutout) {
        remixapi_MaterialInfo info; remixapi_MaterialInfoOpaqueEXT ext;
        nscn::detail::make_material_info(info, ext, L"x.dds", 7, cutout != 0);
        std::printf("%d %u %u %u %d %d %d %u %d %d\n", cutout, info.filterMode, info.wrapModeU, info.wrapModeV,
                    ext.blendType_hasvalue, ext.useDrawCallAlphaState, ext.alphaTestType, ext.alphaReferenceValue,
                    info.pNext == &ext, ext.sType == REMIXAPI_STRUCT_TYPE_MATERIAL_INFO_OPAQUE_EXT);
    }
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='mat-'))
    (work / 'm.cpp').write_text(SRC)
    r = subprocess.run(['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-static', '-I', str(C), '-isystem',
                        str(C.parent / 'remix-probe/vendor'), str(work / 'm.cpp'), '-o', str(work / 'm.exe')],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    env = {**__import__('os').environ, 'WINEDEBUG': '-all', 'WINEPREFIX': str(C.parent / 'runtime/material-defaults/prefix')}
    run = subprocess.run(['wine', str(work / 'm.exe')], capture_output=True, text=True, check=True, env=env, timeout=300)
    rows = [list(map(int, l.split())) for l in run.stdout.replace('\r', '').split('\n') if l.strip()]
    opaque, cutout = rows
    assert opaque[1:4] == [1, 1, 1], f'opaque: filter/wrapU/wrapV must be linear/repeat/repeat, got {opaque[1:4]}'
    assert opaque[4] == 0, 'opaque: blending enabled (surfaces see-through by texture alpha)'
    assert opaque[6] == 7, f'opaque: alphaTestType {opaque[6]} (7 = kAlways; 0 = kNever discards everything)'
    assert cutout[1:5] == [1, 1, 1, 0] and cutout[6:8] == [4, 128], f'cutout material wrong: {cutout}'
    assert opaque[8] == 1 and opaque[9] == 1, 'pNext / sType chain broken'
    print(json.dumps({'passed': True, 'opaque': opaque, 'cutout': cutout}))


if __name__ == '__main__':
    try:
        main()
    except AssertionError as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
