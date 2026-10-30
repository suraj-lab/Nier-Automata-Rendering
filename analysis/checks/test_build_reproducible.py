"""Gate: the built proxy DLL must be byte-identical when the same commit is built in two different directories.

Why this exists: before 2026-10-30 the linker derived the PE image base from the output path and every absolute
pointer followed it (plus 10.9 MB of DWARF from the static libstdc++/libgcc objects), so the same sources produced a
different whole-file SHA-256 per build directory. Hash-pinned install receipts then could not distinguish "the source
changed" from "the build ran elsewhere". The build now pins `-Wl,--image-base` and keeps the DWARF beside the DLL
instead of inside it; this gate proves the result, and fails if the flags are dropped or `-g` comes back.

Builds take ~20 s each, so this is the slowest gate in the suite. It copies only what the build reads.
"""
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
A = HERE.parent
NEEDED = ['checks', 'menu-preview', 'menu-design', 'remix-probe', 'input']  # read by build_menu_dll.py, preview/
#                                                             build.py, the style-token gate and the export check


def build(root):
    p = subprocess.run(['python3', str(root / 'analysis/checks/build_menu_dll.py')],
                       capture_output=True, text=True, cwd=root)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    out = root / 'analysis/runtime/menu-dll'
    validation = json.loads((out / 'validation.json').read_text())
    assert validation['passed'], validation
    dll = (out / 'd3d11.dll').read_bytes()
    sections = subprocess.run(['x86_64-w64-mingw32-objdump', '-h', str(out / 'd3d11.dll')],
                              capture_output=True, text=True, check=True).stdout
    assert not re.search(r'\.debug_info|\.debug_line\b', sections), 'debug info is back inside the DLL'
    base = re.search(r'^\s+0 \S+\s+[0-9a-f]+\s+([0-9a-f]+)', sections, re.M).group(1)
    return {'sha256': hashlib.sha256(dll).hexdigest(), 'size': len(dll), 'base': base,
            'imports': validation['imports'], 'exports': validation['export_check']}


def main():
    work = pathlib.Path(tempfile.mkdtemp(prefix='nier-repro-'))
    results = {}
    try:
        for name in ('tree-a', 'tree-b'):
            root = work / name
            for sub in NEEDED:
                shutil.copytree(A / sub, root / 'analysis' / sub, symlinks=True)
            results[name] = build(root)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    a, b = results['tree-a'], results['tree-b']
    # ld reports the base + 0x1000; the point is that it is the pinned one and not path-derived
    assert a['base'] == b['base'] and int(a['base'], 16) == 0x180001000, (a['base'], b['base'])
    assert a['size'] == b['size'], (a['size'], b['size'])
    assert a['sha256'] == b['sha256'], (a['sha256'], b['sha256'])
    assert a['imports'] == b['imports'] and a['exports'] == b['exports']
    print(json.dumps({'passed': True, 'sha256': a['sha256'], 'size': a['size'], 'image_base': a['base'],
                      'note': 'same sources, two directories, one hash'}, indent=1))


if __name__ == '__main__':
    main()
