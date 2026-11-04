#!/usr/bin/env python3
"""Build the proxy d3d11.dll with the in-game menu into analysis/runtime/menu-dll/ (never the game folder).
Checks the export table against the original mod and that no D3D/DXGI/d3dcompiler DLL is imported."""
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

C = pathlib.Path(__file__).resolve().parent
A = C.parent
PREVIEW = A / 'menu-preview'
OUT = A / 'runtime' / 'menu-dll'
sys.path.insert(0, str(PREVIEW))
import build as preview_build  # noqa: E402
from build import put  # noqa: E402  (style token generation + vendor hash checks)


def main():
    manifest = json.loads((PREVIEW / 'vendor/manifest.json').read_text())
    for name, info in manifest['files'].items():
        assert hashlib.sha256((PREVIEW / name).read_bytes()).hexdigest() == info['sha256'], name
    preview_build.OUT.mkdir(parents=True, exist_ok=True)
    preview_build.generate_style()
    OUT.mkdir(parents=True, exist_ok=True)
    imgui = PREVIEW / 'vendor/imgui'
    sources = [C / 'd3d11_scale_setter.cpp', C / 'menu_overlay.cpp', C / 'remix_live.cpp', PREVIEW / 'panel.cpp',
               *(imgui / n for n in ['imgui.cpp', 'imgui_draw.cpp', 'imgui_tables.cpp', 'imgui_widgets.cpp']),
               imgui / 'backends/imgui_impl_win32.cpp', imgui / 'backends/imgui_impl_dx11.cpp']
    dll = OUT / 'd3d11.dll'
    built = OUT / f'd3d11.{os.getpid()}.tmp.dll'  # linked here, then put() beside the gates that copy d3d11.dll
    cmd = ['x86_64-w64-mingw32-g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
           '-static', '-static-libgcc', '-static-libstdc++', '-Wl,--no-insert-timestamp',
           # Reproducible by construction: ld derives the image base from the output path by default, and every
           # absolute pointer follows it, so the same sources hashed differently per build directory. objcopy
           # (the alternative way to strip) rewrites the PE TimeDateStamp with the current time, which would undo
           # that; stripping via the linker keeps the timestamp zero. No DWARF sidecar: nothing reads it
           # (read_minidump.py resolves module+RVA), and it was 10.9 MB of the 15.5 MB file.
           '-Wl,--image-base,0x180000000', '-Wl,--strip-debug',
           # ImGui asserts must never abort the game; no XInput DLL is loaded into the game for gamepads.
           '-DIM_ASSERT(_EXPR)=((void)0)', '-DIMGUI_IMPL_WIN32_DISABLE_GAMEPAD',
           '-I' + str(imgui), '-I' + str(preview_build.OUT), '-I' + str(PREVIEW), '-I' + str(C),
           '-isystem', str(A / 'remix-probe/vendor'),  # pinned remix_c.h; the runtime itself is loaded at run time
           *map(str, sources), str(C / 'd3d11_log_proxy.def'), '-ldwmapi', '-lgdi32', '-limm32', '-ldxguid', '-o', str(built)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    (OUT / 'build.log').write_text(p.stdout + p.stderr)
    if p.returncode:
        built.unlink(missing_ok=True)
        print(p.stderr[-4000:])
        return 1
    put(dll, built.read_bytes())
    built.unlink()
    fonts = OUT / 'nier_render_fonts'
    for src in sorted((PREVIEW / 'vendor/fonts').rglob('*')):  # includes the OFL LICENSE.txt
        if src.is_file():
            (fonts / src.relative_to(PREVIEW / 'vendor/fonts')).parent.mkdir(parents=True, exist_ok=True)
            put(fonts / src.relative_to(PREVIEW / 'vendor/fonts'), src.read_bytes())
    put(OUT / 'LICENSE-ImGui.txt', (imgui / 'LICENSE.txt').read_bytes())
    exports = subprocess.run(['python3', str(C / 'verify_scale_setter_exports.py'), str(dll)],
                             capture_output=True, text=True)
    raw = subprocess.run(['x86_64-w64-mingw32-objdump', '-p', str(dll)], capture_output=True, text=True, check=True).stdout
    imports = sorted(set(re.findall(r'DLL Name: (\S+)', raw)))
    forbidden = [i for i in imports if i.lower().startswith(('d3d11', 'dxgi', 'd3dcompiler', 'xinput', 'd3d9'))]
    # Source snapshot: lets a gate reuse this DLL while nothing it was built from has changed (test_menu_overlay.build).
    snapshot = {}
    for src in list(C.glob('*.h')) + list(C.glob('*.cpp')) + [PREVIEW / 'panel.cpp']:
        snapshot[str(src.relative_to(A))] = hashlib.sha256(src.read_bytes()).hexdigest()
    result = {'passed': exports.returncode == 0 and not forbidden, 'source_sha256': snapshot,
              'dll': str(dll.relative_to(A.parent)),
              'sha256': hashlib.sha256(dll.read_bytes()).hexdigest(),
              'imports': imports, 'forbidden_imports': forbidden,
              'export_check': exports.stdout.strip().splitlines(), 'installed': False}
    put(OUT / 'validation.json', (json.dumps(result, indent=2) + '\n').encode())
    print(json.dumps({k: result[k] for k in ('passed', 'sha256', 'imports', 'forbidden_imports')}, indent=1))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
