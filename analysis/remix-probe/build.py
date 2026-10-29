#!/usr/bin/env python3
"""Arch-only preparation: CPU self-check and Windows x64 cross-build. NEVER runs Windows/Wine/Remix."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / 'runtime' / 'remix-probe'


def main():
    # Optional: `build.py --mesh <captured_mesh.h>` builds the captured-mesh variant (remix-mesh.exe);
    # `build.py --scene` builds the scene.bin loader (remix-scene.exe). Default: the reference triangle.
    mesh = Path(sys.argv[2]).resolve() if len(sys.argv) == 3 and sys.argv[1] == '--mesh' else None
    scene = sys.argv[1:] == ['--scene']
    variant = 'mesh' if mesh else 'scene' if scene else None
    manifest = json.loads((HERE / 'vendor/manifest.json').read_text())
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert digest(HERE / 'vendor/remix_c.h') == manifest['sha256'], 'Pinned SDK header changed'
    OUT.mkdir(parents=True, exist_ok=True)
    source = HERE / 'triangle.cpp'
    native = OUT / (f'cpu-check-{variant}' if variant else 'cpu-check')
    exe = OUT / (f'remix-{variant}.exe' if variant else 'remix-triangle.exe')
    common = ['-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror']
    if mesh:
        assert mesh.name == 'captured_mesh.h' and mesh.exists(), mesh
        common += ['-DCAPTURED_MESH', '-I', str(mesh.parent)]
    if scene:
        common += ['-DSCENE_FILE', '-I', str(HERE.parent / 'checks')]  # light_convert.h, shared with the live path
    steps = [
        ('native-build', ['g++', *common, '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                          str(source), '-o', str(native)]),
        ('cpu-check', [str(native)]),
        ('windows-x64-cross-build', ['x86_64-w64-mingw32-g++', *common, '-municode', '-static',
                                    '-static-libgcc', '-static-libstdc++', '-isystem', str(HERE / 'vendor'),
                                    str(source), '-o', str(exe)]),
    ]
    receipt = {'passed': False, 'source_sha256': digest(source), 'sdk_commit': manifest['commit'],
               'mesh_header_sha256': digest(mesh) if mesh else None,
               'steps': [], 'windows_executed': False, 'remix_loaded': False, 'laptop_contacted': False,
               'limits': 'Preparation only; CPU assertions and PE cross-build do not prove runtime ABI, GPU rendering or visual correctness.'}
    for name, cmd in steps:
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=OUT)
        (OUT / (name + (f'-{variant}' if variant else '') + '.log')).write_text(p.stdout + p.stderr)
        receipt['steps'].append({'name': name, 'exit': p.returncode})
        if p.returncode:
            (OUT / (f'validation-{variant}.json' if variant else 'validation.json')).write_text(json.dumps(receipt, indent=2) + '\n')
            print(p.stdout + p.stderr)
            raise SystemExit(p.returncode)
    p = subprocess.run(['x86_64-w64-mingw32-objdump', '-p', str(exe)], capture_output=True, text=True, check=True)
    imports = sorted(line.split('DLL Name:', 1)[1].strip() for line in p.stdout.splitlines() if 'DLL Name:' in line)
    assert not any(name.lower().startswith(('d3d9', 'dxgi', 'd3d11', 'vulkan', 'cuda')) for name in imports), imports
    receipt.update(passed=True, exe_sha256=digest(exe), imports=imports)
    (OUT / (f'validation-{variant}.json' if variant else 'validation.json')).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
