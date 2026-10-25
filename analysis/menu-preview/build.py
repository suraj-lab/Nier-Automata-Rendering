#!/usr/bin/env python3
"""Build isolated preview binaries. Never reads/writes the game installation."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "analysis/runtime/menu-preview/build"


def generate_style():
    subprocess.run(["python3", str(ROOT / "analysis/checks/test_menu_style_tokens.py")], check=True)
    tokens = json.loads((ROOT / "analysis/menu-design/claude_style_tokens.json").read_text())
    lines = ['// Generated from the checked Claude Design token snapshot; do not edit.',
             '#pragma once', '#include "imgui.h"', 'namespace preview_style {', 'namespace colors {']
    for name, value in tokens['colors'].items():
        rgb = [int(value[i:i+2], 16) for i in (1, 3, 5)]
        lines.append(f'inline constexpr ImU32 {name} = IM_COL32({rgb[0]}, {rgb[1]}, {rgb[2]}, 255);')
    for group in ['layout', 'typography']:
        lines.append('}' + f' namespace {group} {{')
        for name, value in tokens[group].items():
            if type(value) in (int, float):
                lines.append(f'inline constexpr float {name} = {float(value)}f;')
    lines += ['}', '}']
    (OUT / 'style_tokens.h').write_text('\n'.join(lines) + '\n')


def main():
    manifest = json.loads((HERE / 'vendor/manifest.json').read_text())
    for name, info in manifest['files'].items():
        assert hashlib.sha256((HERE/name).read_bytes()).hexdigest() == info['sha256'], name
    OUT.mkdir(parents=True, exist_ok=True)
    generate_style()
    shutil.copytree(HERE/'vendor/fonts', OUT/'fonts', dirs_exist_ok=True)
    shutil.copy2(HERE/'vendor/imgui/LICENSE.txt', OUT/'LICENSE-ImGui.txt')
    imgui = HERE/'vendor/imgui'
    core = [imgui/n for n in ['imgui.cpp', 'imgui_draw.cpp', 'imgui_tables.cpp', 'imgui_widgets.cpp']]
    common = ['-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
              '-I'+str(imgui), '-I'+str(OUT), '-I'+str(HERE)]
    subprocess.run(['g++', *common, '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(HERE/'panel.cpp'), str(HERE/'panel_test.cpp'), *map(str, core),
                    '-o', str(OUT/'panel_test')], check=True)
    subprocess.run([str(OUT/'panel_test'), str(OUT/'fonts')], check=True)
    subprocess.run(['x86_64-w64-mingw32-g++', *common, '-static', '-static-libgcc', '-static-libstdc++',
                    str(HERE/'panel.cpp'), str(HERE/'preview_win32.cpp'), *map(str, core),
                    str(imgui/'backends/imgui_impl_win32.cpp'), str(imgui/'backends/imgui_impl_dx11.cpp'),
                    '-ld3d11', '-ldxgi', '-ld3dcompiler', '-ldwmapi', '-lgdi32', '-limm32',
                    '-o', str(OUT/'nier_menu_preview.exe')], check=True)
    print(json.dumps({'passed': True, 'executable': str(OUT/'nier_menu_preview.exe'),
                      'limits': 'Standalone UI only; no game hooks/config writer. Windows build not yet executed.'}))


if __name__ == '__main__':
    main()
