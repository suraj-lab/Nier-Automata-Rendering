#!/usr/bin/env python3
"""Gate: the funnel ledger accounts for every draw and every instance, and prints it in one bounded line."""
import json
import subprocess
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include "funnel.h"
#include <cassert>
#include <cstring>
#include <string>
using namespace funnel;
using visibility_trace::Reason;

int main() {
    // Every reason counts into its own bucket, and the total is the number of draws.
    for (unsigned i = 0; i < kReasons; ++i) count(static_cast<Reason>(i), i + 1);
    Totals t = take();
    assert(t.other == 0 && balance(t) == std::string("ok"));
    unsigned long long expect = 0;
    for (unsigned i = 0; i < kReasons; ++i) { assert(t.reason[i] == i + 1); expect += i + 1; }
    assert(draws(t) == expect);

    // Instances are counted by outcome, and the histogram line stays bounded even when every bucket is non-zero.
    count_instance(Reason::Drawn, 5);
    count_instance(Reason::MeshMissing, 7);
    count_instance(Reason::BadTransform, 1);
    count_instance(Reason::DrawFailed, 2);
    count_instance(Reason::Accepted, 99);          // not an instance outcome: must land in `other`, not silently vanish
    Totals u = take();
    assert(u.instance_drawn == 5 && u.instance_missing == 7 && u.instance_bad_transform == 1 && u.instance_failed == 2);
    assert(instances(u) == 15 && u.other == 99 && balance(u) == std::string("UNCOUNTED"));

    char line[512];
    const int n = format(line, sizeof line, u);
    assert(n > 0 && static_cast<unsigned>(n) < sizeof line);
    const std::string s(line);
    assert(s.find("draws=") == 0 && s.find("instances=15") != std::string::npos);
    assert(s.find("mesh_missing=7") != std::string::npos && s.find("balance=UNCOUNTED") != std::string::npos);

    // A window where every reason fires still fits the buffer: the line must never be truncated silently.
    Totals wide;
    for (unsigned i = 0; i < kReasons; ++i) wide.reason[i] = 1000000 + i;
    wide.instance_drawn = 1000000; wide.instance_missing = 999999;
    char big[1024];
    const int m = format(big, sizeof big, wide);
    assert(m > 0 && static_cast<unsigned>(m) < sizeof big);
    // A buffer too small must not overflow: snprintf truncates, the count stays a real length.
    char tiny[16];
    format(tiny, sizeof tiny, wide);
    assert(std::strlen(tiny) < sizeof tiny);

    // take() resets, so two windows never double-count.
    Totals empty = take();
    assert(draws(empty) == 0 && instances(empty) == 0 && empty.other == 0);
    std::puts("per-reason buckets, instance outcomes, uncounted detection, bounded line, reset");
}
'''


def main():
    try:
        with tempfile.TemporaryDirectory(prefix='funnel-') as d:
            d = Path(d)
            (d / 'test.cpp').write_text(HARNESS)
            p = subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                                '-I', str(C), str(d / 'test.cpp'), '-o', str(d / 'test')],
                               capture_output=True, text=True)
            assert p.returncode == 0, 'compile:\n' + p.stderr[-3000:]
            p = subprocess.run([str(d / 'test')], capture_output=True, text=True)
            assert p.returncode == 0, 'run:\n' + (p.stdout + p.stderr)[-3000:]
        print(json.dumps({'passed': True, 'checks': p.stdout.strip()}))
    except Exception as e:
        print(json.dumps({'passed': False, 'error': str(e)[-2500:]}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
