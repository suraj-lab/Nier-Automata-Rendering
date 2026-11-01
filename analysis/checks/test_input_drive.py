#!/usr/bin/env python3
"""Gate: the pop-in experiment's input script (input_drive.h) parses strictly and labels time correctly.

A wrong phase label puts turn frames into the still-camera column of the fit, so a malformed script must be refused
whole, and phase boundaries must be exact.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include "input_drive.h"
#include <cassert>
#include <cstdio>

int main() {
    using namespace input_drive;
    const auto s = parse("still:30,turn:8:40,still:2.5,walk:8,turn:4:-40");
    assert(s.size() == 5);
    const auto b = parse("back:3,walk:2");
    assert(b.size() == 2 && b[0].kind == Kind::Back && at(b, 1).walk == -1 && at(b, 4).walk == 1 && at(b, 1).dx == 0);
    assert(parse("back:3:1").empty() && parse("back").empty());
    assert(s[1].kind == Kind::Turn && s[1].seconds == 8 && s[1].dx == 40);
    assert(s[2].seconds == 2.5 && s[3].kind == Kind::Walk && s[4].dx == -40);
    // Malformed anywhere: nothing, so a typo cannot silently shift every later phase.
    for (const char* bad : {"", "still", "still:", "still:0", "still:-1", "still:5:3", "turn:5", "turn:5:0",
                            "turn:5:x", "spin:5", "still:5,,walk:3", "still:5x", "walk:3,turn:2:4:1"})
        assert(parse(bad).empty());
    // Boundaries: a phase owns [start, end); before the start and after the end nothing is driven.
    assert(at(s, -0.1).phase == -1);
    assert(at(s, 0).phase == 0 && at(s, 0).dx == 0 && at(s, 0).walk == 0);
    assert(at(s, 29.999).phase == 0 && at(s, 30).phase == 1 && at(s, 30).dx == 40);
    assert(at(s, 38).phase == 2 && at(s, 40.5).phase == 3 && at(s, 40.5).walk == 1 && at(s, 40.5).dx == 0);
    assert(at(s, 48.5).phase == 4 && at(s, 48.5).dx == -40);
    assert(at(s, 52.5).phase == -1 && at(s, 1e9).phase == -1);
    assert(at({}, 1).phase == -1);
    // Not started: nothing is driven whatever the script says.
    script = s;
    assert(current().phase == -1);
    start_us = now_us();
    assert(current().phase == 0);
    std::puts("strict parse, phase boundaries, not driving before start or after end");
    return 0;
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='input-drive-'))
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
