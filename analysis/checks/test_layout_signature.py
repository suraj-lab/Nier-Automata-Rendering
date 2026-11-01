#!/usr/bin/env python3
"""Gate: the no-POSITION refusal carries a bounded, stable layout signature."""
import json
import subprocess
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
HARNESS = r'''
#include <cassert>
#include <cstring>
#include <string>
#include "layout_signature.h"

using live_decode::Element;
static Element e(const char* sem, int fmt, bool inst = false) { return Element{sem, fmt, 0, 0, inst}; }

int main() {
    // Sorted, duplicate-collapsed, and format-bearing: two layouts that differ only in a format stay distinct.
    const std::string a = layout_signature::of({e("TEXCOORD", 34), e("NORMAL", 6)});
    const std::string b = layout_signature::of({e("NORMAL", 6), e("TEXCOORD", 34), e("TEXCOORD", 34)});
    assert(a == b && a == "NORMAL:6,TEXCOORD:34");
    assert(layout_signature::of({e("TEXCOORD", 16), e("NORMAL", 6)}) != a);

    // Per-instance elements never supply a position, so they are left out of the signature.
    assert(layout_signature::of({e("TEXCOORD", 34), e("INSTANCEID", 30, true)}) == "TEXCOORD:34");
    assert(layout_signature::of({}) == "(no per-vertex elements)");

    // A pathological layout cannot grow past the buffer.
    std::vector<Element> many;
    for (int i = 0; i < 64; ++i) many.push_back(e("SEMANTICNAME", 1000 + i));
    const std::string big = layout_signature::of(many);
    assert(big.size() < layout_signature::kMaxLen);

    // Distinct signatures are capped; the rest are counted, never silently dropped.
    layout_signature::take();
    for (int i = 0; i < 20; ++i) layout_signature::note({e("A", i)});
    layout_signature::note({e("A", 3)});
    auto rows = layout_signature::take();
    assert(rows.size() == layout_signature::kMaxDistinct);
    assert(rows[0].count == 2);                       // sorted by count: the repeated one leads
    unsigned long long sum = 0;
    for (const auto& r : rows) sum += r.count;
    assert(sum + (20 - layout_signature::kMaxDistinct) == 21);
    assert(layout_signature::take().empty());          // take() resets

    std::puts("signature formatting, per-instance exclusion, bounded length, distinct cap, reset");
}
'''


def main():
    try:
        with tempfile.TemporaryDirectory(prefix='layout-sig-') as d:
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
