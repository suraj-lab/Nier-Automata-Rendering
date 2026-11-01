#!/usr/bin/env python3
"""Gate: the frame-to-frame presence watch reports exactly the keys that left and arrived."""
import json
import subprocess
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include "dropout_watch.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <map>
#include <set>

using dropout_watch::Watch;
using Keys = std::set<std::uint64_t>;

int main() {
    Watch w;
    // First step only primes: nothing can have "left" yet.
    auto s0 = w.step(Keys{1, 2, 3});
    assert(!dropout_watch::notable(s0) && s0.dropped.empty() && s0.appeared.empty() && s0.present == 3);
    assert(w.primed() && w.size() == 3);

    // One key leaves: exactly that key, and it is not "notable" below the threshold.
    auto s1 = w.step(Keys{1, 3});
    assert(s1.dropped.size() == 1 && s1.dropped[0] == 2 && s1.appeared.empty());
    assert(!dropout_watch::notable(s1));

    // The key returns: it is "appeared", not "dropped".
    auto s2 = w.step(Keys{1, 2, 3});
    assert(s2.appeared.size() == 1 && s2.appeared[0] == 2 && s2.dropped.empty());

    // Everything leaves on one frame; below the threshold this is still not "notable".
    auto s3 = w.step(Keys{});
    assert(s3.dropped.size() == 3 && !dropout_watch::notable(s3));      // 3 < default threshold of 8
    assert((s3.dropped == std::vector<std::uint64_t>{1, 2, 3}));

    // An empty frame in between then a return is still measured against the previous step.
    auto s4 = w.step(Keys{7});
    assert(s4.appeared.size() == 1 && s4.appeared[0] == 7 && s4.dropped.empty());

    // Sorted, unique, and stable when nothing changes.
    auto s5 = w.step(Keys{7});
    assert(s5.dropped.empty() && s5.appeared.empty() && s5.present == 1);

    // Threshold is inclusive and applies to arrivals too.
    Watch big;
    Keys a; for (std::uint64_t i = 0; i < 20; ++i) a.insert(i);
    big.step(a);
    Keys b; for (std::uint64_t i = 10; i < 20; ++i) b.insert(i);
    auto d = big.step(b);
    assert(d.dropped.size() == 10 && dropout_watch::notable(d));
    assert(!dropout_watch::notable(d, 11));


    // Camera motion: identical arrays are motionless; a translation and a 90-degree turn are measured exactly.
    {
        float a[14] = {0,0,0, 0,0,-1, 0,1,0, 1,0,0, 50,0};
        float b[14] = {0,0,0, 0,0,-1, 0,1,0, 1,0,0, 50,0};
        auto m0 = dropout_watch::motion(a, b);
        assert(m0.valid && m0.moved == 0.f && m0.turned_deg < 1e-3f);
        b[0] = 3.f; b[2] = 4.f;
        auto m1 = dropout_watch::motion(a, b);
        assert(std::fabs(m1.moved - 5.f) < 1e-5f && m1.turned_deg < 1e-3f);
        b[3] = 1.f; b[5] = 0.f;
        auto m2 = dropout_watch::motion(a, b);
        assert(std::fabs(m2.turned_deg - 90.f) < 1e-3f);
        b[0] = std::nanf("");
        assert(!dropout_watch::motion(a, b).valid);
        float z[14] = {};
        assert(!dropout_watch::motion(z, z).valid);   // zero forward: no direction to compare
    }
    // Visibility of what dropped: the largest last-known fraction, unknown keys contribute nothing.
    {
        std::map<std::uint64_t, double> last{{1, 0.02}, {2, 0.6}, {3, 0.1}};
        assert(dropout_watch::max_fraction({1, 3}, last) == 0.1);
        assert(dropout_watch::max_fraction({2, 9}, last) == 0.6);
        assert(dropout_watch::max_fraction({9}, last) == 0.0);
        assert(dropout_watch::max_fraction({}, last) == 0.0);
    }

    // Attribution: every dropped key lands in exactly one bucket, and an arrival explains at most one departure.
    {
        using dropout_watch::Ident; using dropout_watch::Seen;
        std::map<std::uint64_t, Ident> prev{
            {10, {100, 7, 300, 0}},    // drawn again under a new occurrence key (same source)
            {11, {101, 8, 600, 30}},   // drawn again under a new key, same index buffer and range (pointer churn)
            {12, {102, 9, 900, 0}},    // same range, but its index buffer was recreated (shape churn)
            {13, {103, 5, 400, 0}},    // the game still drew it; we rejected it this frame (reason 1 = pass)
            {14, {104, 5, 500, 0}},    // reached the renderer but failed there
            {15, {105, 6, 700, 0}},    // nothing this frame refers to it at all
            {16, {106, 4, 800, 0}},    // a second departure competing for the same arrival as key 17
            {17, {107, 4, 800, 0}},
        };
        std::vector<Seen> cap{
            {20, 100, 7, 300, 0, 23},   // key 20, source 100 (key 10's draw), unchanged
            {21, 201, 8, 600, 30, 0},   // key 21, new source, same ib/range as key 11
            {22, 202, 99, 900, 0, 0},   // key 22, new ib, same range as key 12
            {13, 103, 5, 400, 0, 1},    // key 13 itself, rejected as pass
            {14, 104, 5, 500, 0, 23},
            {23, 207, 4, 800, 0, 0},    // one arrival for the two departures 16 and 17
            {0, 0, 0, 100, 0, 3},       // an early reject without a key never matches anything
        };
        std::map<std::uint64_t, unsigned> submit_other{{14, 17}};   // 17 = draw_failed
        auto why = dropout_watch::attribute({10, 11, 12, 13, 14, 15, 16, 17}, {20, 21, 22, 23}, prev, cap, submit_other);
        assert(why.churn_occurrence == 1);
        assert(why.churn_pointer == 2);           // keys 11 and one of 16/17
        assert(why.churn_shape == 1);
        assert(why.capture[1] == 1);
        assert(why.submit_other == 1);
        assert(why.absent == 2);                  // key 15 and the other of 16/17
        unsigned total = why.churn_occurrence + why.churn_pointer + why.churn_shape + why.submit_other + why.absent;
        for (unsigned c : why.capture) total += c;
        assert(total == 8);                       // closed ledger: one bucket per dropped key
        // Nothing known about a key from last frame: it can only be absent or explained by this frame directly.
        auto bare = dropout_watch::attribute({50}, {}, {}, {}, {});
        assert(bare.absent == 1);
    }

    // Churn breakdown: for a same-IB/range re-key, which key component moved; and whether the new key was built.
    {
        using dropout_watch::Ident; using dropout_watch::Seen;
        Ident base{100, 7, 300, 0}; base.vb = 50; base.vb_offset = 0; base.base_vertex = 0; base.layout = 9;
        std::map<std::uint64_t, Ident> prev{{1, base}, {2, base}, {3, base}, {4, base}};
        prev[2].start_index = 600;  prev[3].start_index = 900;  prev[4].start_index = 1200;
        auto arrival = [&](std::uint64_t key, unsigned start) {
            Seen s{key, 900 + key, 7, 300, start, 0}; s.vb = 50; s.vb_offset = 0; s.base_vertex = 0; s.layout = 9; return s;
        };
        Seen a = arrival(11, 0);    a.vb_offset = 4096;            // ring-buffer style: same buffer, new offset
        Seen b = arrival(12, 600);  b.vb = 51;                     // buffer recreated or swapped
        Seen c = arrival(13, 900);  c.base_vertex = 64; c.layout = 10;   // two components at once
        Seen d = arrival(14, 1200);                                // none of the four: another slot or stride moved
        std::set<std::uint64_t> missing{11, 13};                   // arrived before its mesh was built
        auto why = dropout_watch::attribute({1, 2, 3, 4}, {11, 12, 13, 14}, prev, {a, b, c, d}, {}, &missing);
        assert(why.churn_pointer == 4);
        assert(why.moved_vb == 1 && why.moved_offset == 1 && why.moved_base == 1 && why.moved_layout == 1);
        assert(why.moved_other == 1);
        assert(why.arrived_missing == 2);
        // Without the build-state set the count stays zero rather than guessing.
        auto blind = dropout_watch::attribute({1}, {11}, prev, {a}, {});
        assert(blind.churn_pointer == 1 && blind.arrived_missing == 0 && blind.moved_offset == 1);
    }

    // Same IB and range is not proof of the same object (engines share index buffers between tiles): where the
    // arrival sits decides it. same <1 cm, near <1 unit (a moving object), far = a different object.
    {
        using dropout_watch::Ident; using dropout_watch::Seen;
        Ident base{100, 7, 300, 0}; base.vb = 50;
        std::map<std::uint64_t, Ident> prev{{1, base}, {2, base}, {3, base}};
        prev[2].start_index = 600; prev[3].start_index = 900;
        prev[1].position[0] = 10.f; prev[2].position[0] = 10.f; prev[3].position[0] = 10.f;
        Seen a{11, 911, 7, 300, 0, 0};   a.vb = 51; a.position[0] = 10.004f;              // same spot
        Seen b{12, 912, 7, 300, 600, 0}; b.vb = 51; b.position[0] = 10.f; b.position[2] = 0.5f;  // moved a little
        Seen c{13, 913, 7, 300, 900, 0}; c.vb = 51; c.position[0] = 40.f;               // another tile
        auto why = dropout_watch::attribute({1, 2, 3}, {11, 12, 13}, prev, {a, b, c}, {});
        assert(why.churn_pointer == 3);
        assert(why.place_same == 1 && why.place_near == 1 && why.place_far == 1);
    }
    std::puts("priming, single departures, return as arrival, synchronous event, threshold, camera motion, dropped fraction, attribution, churn breakdown, churn place");
}
'''


def main():
    try:
        with tempfile.TemporaryDirectory(prefix='dropout-watch-') as d:
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
