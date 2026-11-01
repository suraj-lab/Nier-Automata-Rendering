#!/usr/bin/env python3
"""Independent boundary cases added during trace review; no GPU or target process."""
import json
from pathlib import Path
import subprocess
import tempfile

C = Path(__file__).resolve().parent
SOURCE = r'''
#include "visibility_trace.h"
#include <cassert>
#include <cstring>
#include <vector>
using namespace visibility_trace;
int main() {
    assert(std::strcmp(reason_name(Reason::Sky), "sky") == 0);
    assert(std::strcmp(reason_name(static_cast<Reason>(~0u)), "unknown") == 0);
    Batch b; Event e; e.source = 3; e.geometry = 4; e.instances = 1;
    e.reason = static_cast<Reason>(~0u); b.add(e);
    Tracker t; std::vector<Change> changes;
    auto emit = [&](const Change& c) { changes.push_back(c); };
    t.consume(0, b, emit); assert(t.tracked() == 0 && changes.empty());
    t.consume(1, b, emit); assert(changes.size() == 1 && changes[0].mask == 0);
    b.events[0].position[0] = 99; // animation alone must not flood the trace
    t.consume(2, b, emit); assert(changes.size() == 1);
    Tracker none(0, 0); none.consume(1, b, emit);
    assert(none.tracked() == 0 && none.untracked == 1 && none.suppressed == 0);
    Tracker quiet(1, 0); quiet.consume(1, b, emit);
    assert(quiet.tracked() == 1 && quiet.suppressed == 1);
    b.events[0].reason = Reason::Sky;
    quiet.consume(2, b, emit); assert(quiet.suppressed == 2);
}
'''


def main():
    try:
        with tempfile.TemporaryDirectory(prefix='trace-hidden-') as d:
            d = Path(d); (d / 'test.cpp').write_text(SOURCE)
            p = subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                '-fsanitize=address,undefined', '-I', str(C), str(d / 'test.cpp'),
                                '-o', str(d / 'test')], capture_output=True, text=True)
            assert p.returncode == 0, p.stderr[-2500:]
            p = subprocess.run([str(d / 'test')], capture_output=True, text=True)
            assert p.returncode == 0, (p.stdout + p.stderr)[-2500:]
        print(json.dumps({'passed': True, 'checks': 'sky reason, malformed enum, monotonic zero, pose-only changes, zero limits'}))
    except Exception as e:
        print(json.dumps({'passed': False, 'error': str(e)})); return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
