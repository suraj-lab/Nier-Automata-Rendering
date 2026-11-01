#!/usr/bin/env python3
"""Frozen native gate for bounded, diagnostic-only visibility deltas; no GPU/game needed."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include "visibility_trace.h"
#include <cassert>
#include <cstdio>
#include <vector>
using namespace visibility_trace;
static Event event(unsigned key, Reason reason = Reason::Accepted, unsigned target = 900) {
    Event e{}; e.source = key; e.geometry = key; e.target_w = target; e.target_h = 600;
    e.reason = reason; e.instances = 1; e.index_count = 600; e.position[0] = 23;
    return e;
}
int main() {
    static_assert(kMaxEvents == 4096, "capture storage must be bounded");
    Batch b;
    for (unsigned i = 0; i != kMaxEvents + 3; ++i) b.add(event(i + 1));
    assert(b.events.size() == kMaxEvents && b.dropped == 3);
    std::vector<Change> out;
    auto emit = [&](const Change& c) { out.push_back(c); };
    Tracker t;
    Batch first; first.add(event(10)); first.add(event(10)); first.add(event(20, Reason::Pass));
    t.consume(1, first, emit);
    assert(out.size() == 2 && t.tracked() == 2);
    assert(out[0].event.source == 10 && out[0].calls == 2 && out[0].instances == 2);
    assert(out[0].mask == (1ull << static_cast<unsigned>(Reason::Accepted)));
    assert(out[0].event.position[0] == 23 && !out[0].missing);
    out.clear();
    t.consume(2, first, emit); assert(out.empty());
    Batch changed; changed.add(event(10, Reason::Data)); changed.add(event(20, Reason::Pass));
    t.consume(3, changed, emit);
    assert(out.size() == 1 && out[0].event.source == 10 && !out[0].missing);
    assert(out[0].mask == (1ull << static_cast<unsigned>(Reason::Data)));
    out.clear();
    Batch incomplete; incomplete.dropped = 1;
    t.consume(4, incomplete, emit); assert(out.empty()); // unknown != vanished
    Batch empty;
    t.consume(5, empty, emit); assert(out.size() == 2);
    assert(out[0].missing && out[1].missing && out[0].sequence == 5);
    out.clear();
    t.consume(6, empty, emit); assert(out.empty()); // absent only once
    t.consume(7, first, emit); assert(out.size() == 2 && !out[0].missing);
    out.clear();
    t.consume(7, empty, emit); t.consume(1, empty, emit); assert(out.empty()); // monotonic snapshots
    Batch other; other.add(event(10, Reason::Accepted, 300));
    t.consume(8, other, emit);
    assert(t.tracked() == 3); // shadow target must not overwrite scene target
    Tracker bounded(2, 2);
    Batch many; many.add(event(1)); many.add(event(2)); many.add(event(3));
    out.clear(); bounded.consume(1, many, emit);
    assert(bounded.tracked() == 2 && bounded.untracked == 1 && out.size() == 2);
    out.clear(); bounded.consume(2, empty, emit);
    assert(out.empty() && bounded.suppressed == 2); // hard output cap; state still bounded
    // Every reason has a stable nonempty label; no claim of engine/runtime culling is manufactured.
    for (unsigned i = 0; i < static_cast<unsigned>(Reason::Count); ++i)
        assert(reason_name(static_cast<Reason>(i))[0]);
    std::puts("bounded aggregation, transitions, incomplete snapshots, monotonicity, target isolation, output cap");
}
'''


def reference():
    """Independent tiny state oracle: unknown snapshots cannot imply missing; only newer snapshots apply."""
    state, changes, sequence = set(), [], 0
    for seq, keys, complete in [(1, {10, 20}, True), (2, {10, 20}, True), (3, set(), False),
                                (4, set(), True), (5, {10, 20}, True), (4, set(), True)]:
        if seq <= sequence:
            continue
        sequence = seq
        changes += [(seq, k, 'seen') for k in sorted(keys - state)]
        if complete:
            changes += [(seq, k, 'missing') for k in sorted(state - keys)]
            state = keys
        else:
            state |= keys
    return changes


def main():
    try:
        assert reference() == [(1, 10, 'seen'), (1, 20, 'seen'), (4, 10, 'missing'),
                               (4, 20, 'missing'), (5, 10, 'seen'), (5, 20, 'seen')]
        header = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else C / 'visibility_trace.h'
        with tempfile.TemporaryDirectory(prefix='visibility-trace-') as d:
            d = Path(d)
            (d / 'visibility_trace.h').write_bytes(header.read_bytes())
            (d / 'test.cpp').write_text(HARNESS)
            p = subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-O1',
                                '-fsanitize=address,undefined', str(d / 'test.cpp'), '-o', str(d / 'test')],
                               capture_output=True, text=True)
            assert p.returncode == 0, 'native compile: ' + p.stderr[-3500:]
            p = subprocess.run([str(d / 'test')], capture_output=True, text=True)
            assert p.returncode == 0, 'native run: ' + (p.stdout + p.stderr)[-3500:]
        print(json.dumps({'passed': True, 'checks': p.stdout.strip()}))
    except Exception as e:
        print(json.dumps({'passed': False, 'error': str(e)}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
