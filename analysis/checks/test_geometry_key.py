#!/usr/bin/env python3
"""Gate: secondary-stream variants keep one key per object and never alias two different objects in a frame."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include "geometry_key.h"
#include <cassert>
#include <cstdio>

int main() {
    using geometry_key::variant;
    std::map<std::uint64_t, std::vector<std::uint64_t>> seen;
    // Frame 1: one object, its slot-2 stream at A. Frame 2: the stream moved to B. Same key both frames.
    assert(variant(7, 0xA, seen) == 7);
    seen.clear();
    assert(variant(7, 0xB, seen) == 7);
    // Instancing: the same draw repeated with the same streams stays one key (one mesh).
    assert(variant(7, 0xB, seen) == 7);
    // A second object sharing position/index/layout but with other secondary streams gets its own stable key.
    const std::uint64_t other = variant(7, 0xC, seen);
    assert(other != 7);
    assert(variant(7, 0xC, seen) == other);
    // Next frame, same order: same keys. The variant depends on order, not on the pointers.
    seen.clear();
    assert(variant(7, 0xD, seen) == 7 && variant(7, 0xE, seen) == other);
    // Distinct base keys never collide through their variants.
    seen.clear();
    assert(variant(8, 0xA, seen) == 8 && variant(8, 0xB, seen) != variant(7, 0xB, seen));
    std::puts("stable across secondary-stream moves, instancing shared, same-frame variants distinct and stable");
    return 0;
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='geometry-key-'))
    (work / 't.cpp').write_text(HARNESS)
    build = subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                            '-I', str(C), str(work / 't.cpp'), '-o', str(work / 't')], capture_output=True, text=True)
    if build.returncode:
        print(json.dumps({'passed': False, 'error': 'compile:\n' + build.stderr[-1500:]}))
        return 1
    run = subprocess.run([str(work / 't')], capture_output=True, text=True)
    if run.returncode:
        print(json.dumps({'passed': False, 'error': 'run:\n' + (run.stdout + run.stderr)[-1500:]}))
        return 1
    print(json.dumps({'passed': True, 'checks': run.stdout.strip()}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
