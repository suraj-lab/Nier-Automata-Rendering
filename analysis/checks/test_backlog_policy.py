#!/usr/bin/env python3
"""Gate: the build budget rises only during a backlog, stays bounded, and does nothing when it is off.

live-churn measured the failure this guards: when a new area streams in, instances reached the renderer before
their meshes existed for 50.5% of the frame (16,129 of 31,925) while the 4 ms build budget deferred 2,915 builds.
A spike should cost frame time, not holes.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include "backlog_policy.h"
#include <cassert>
#include <cstdio>

int main() {
    using backlog_policy::budget;
    // A normal frame keeps the configured budget (live-churn steady state is 0.5-2.3% unbuilt).
    assert(budget(4000, 9000, 120) == 4000);
    assert(budget(4000, 9000, 207) == 4000);
    // A stream-in spike raises it, bounded, so the spike costs frames instead of holes.
    assert(budget(4000, 31925, 16129) == backlog_policy::kBoosted);
    assert(budget(4000, 47342, 10748) == backlog_policy::kBoosted);
    // Boundaries: exactly at the share raises, just under does not, no instances is not a spike.
    assert(budget(4000, 1000, 100) == backlog_policy::kBoosted);
    assert(budget(4000, 1000, 99) == 4000);
    assert(budget(4000, 0, 0) == 4000);
    // Disabled stays disabled, and the boost itself is capped so a long spike cannot stall the game.
    assert(budget(0, 1000, 900) == 0);
    assert(backlog_policy::kBoosted <= backlog_policy::kMaxBudget);
    std::puts("configured budget, spike boost, boundaries, disabled, ceiling");
    return 0;
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='backlog-policy-'))
    (work / 't.cpp').write_text(HARNESS)
    build = subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-I', str(C),
                            str(work / 't.cpp'), '-o', str(work / 't')], capture_output=True, text=True)
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
