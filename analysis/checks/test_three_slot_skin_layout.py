#!/usr/bin/env python3
"""Gate: the pinned upstream skinning shader, fed the way rtx_remix_api.cpp feeds it, reproduces our
four-weight bake only when real vertices sit three slots apart. Proves (a) the 1-float weight stride
reproduces the reference to float rounding with that layout, (b) today's dense call does not, so the
check has teeth, and (c) the upstream source under test is the revision the manifest pinned."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPSTREAM = HERE / 'upstream_rtx'
FIXTURE = HERE / 'fixtures/skin-weights-nier.json'
SOURCE = HERE / 'skin_layout_check.cpp'


def compile_and_run(source, work, extra=()):
    exe = work / 'skin_layout_check'
    build = subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', *extra, '-I', str(HERE),
                            '-I', str(UPSTREAM), str(source), '-o', str(exe)],
                           capture_output=True, text=True)
    if build.returncode:
        raise SystemExit(build.stdout + build.stderr)
    return subprocess.run([str(exe), str(FIXTURE)], capture_output=True, text=True)


def main():
    manifest = json.loads((UPSTREAM / 'MANIFEST.json').read_text())
    for name, want in manifest['files'].items():
        got = hashlib.sha256((UPSTREAM / name).read_bytes()).hexdigest()
        assert got == want, f'{name} is not the pinned upstream revision: {got} != {want}'
    work = Path(tempfile.mkdtemp(prefix='skin-layout-'))
    good = compile_and_run(SOURCE, work)
    assert good.returncode == 0, good.stdout + good.stderr
    rows = [line for line in good.stdout.splitlines() if line.startswith('draw_')]
    assert len(rows) == 3, good.stdout
    for row in rows:
        fields = dict(part.split('=') for part in row.split()[1:])
        assert float(fields['spread_vs_reference']) < 1e-4, row
        assert float(fields['dense_vs_reference']) > 1e-2, row

    # Mutation: make the spread layout dense again (the bug) and require the check to fail on real data.
    mutated = work / 'mutated.cpp'
    mutated.write_text(SOURCE.read_text().replace('static std::size_t spread(std::size_t i) { return 3 * i; }',
                                                  'static std::size_t spread(std::size_t i) { return i; }'))
    bad = compile_and_run(mutated, work)
    assert bad.returncode != 0 and 'FAIL' in bad.stdout + bad.stderr, bad.stdout + bad.stderr

    print(json.dumps({
        'passed': True, 'work': str(work), 'draws': len(rows),
        'upstream': {'repo': manifest['repo'], 'ref': manifest['ref'],
                     'skinning_h_sha256': manifest['files']['pass/skinning.h']},
        'measured': {row.split()[0]: dict(part.split('=') for part in row.split()[1:]) for row in rows},
        'limits': ('Compares the pinned upstream shader compiled as C++ (shim types, not dxvk SIMD math) against our '
                   'reference bake on real captured weights. It does not prove the shipped runtime binary matches '
                   'those sources; that needs REPROBE_SPREAD=1 in the skin-stride probe on the laptop.'),
    }, indent=2))


if __name__ == '__main__':
    main()
