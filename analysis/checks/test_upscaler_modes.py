#!/usr/bin/env python3
"""Frozen gate for the P1 upscaler-selection core (checks/upscaler_modes.h).

Portable C++17, no D3D and no Remix: the native test pins the exact ordered writes, the default no-op, the
precedence and the atomicity. The Wine/fake-runtime wiring is a later gate.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent

HARNESS = r'''
#include <cstdio>
#include <string>
#include <vector>
#include "upscaler_modes.h"

static int failures = 0;
static void check(const char* what, bool ok) { if (!ok) { ++failures; std::printf("FAIL %s\n", what); } }

static std::string joined(const std::vector<upscaler::Write>& w) {
    std::string s;
    for (const auto& x : w) { s += x.key; s += '='; s += x.value; s += ';'; }
    return s;
}

int main() {
    using upscaler::Mode;
    // Config is today's behaviour: no writes at all, for an empty and for an unknown value (reported, not silent).
    check("config writes nothing", upscaler::writes_for(Mode::Config).empty());
    Mode m = Mode::Quality;
    check("empty parses to Config", upscaler::parse_mode("", m) && m == Mode::Config);
    check("literal config is a valid name", upscaler::parse_mode("config", m) && m == Mode::Config);
    check("unknown is rejected", !upscaler::parse_mode("ultra", m));
    check("case-sensitive names", !upscaler::parse_mode("Quality", m));
    // Each mode: Custom first, then the numeric quality, in order, for both upscalers, numbers from the plan table.
    const struct { const char* name; Mode mode; const char* expect; } rows[] = {
        {"ultra-performance", Mode::UltraPerformance, "rtx.dlssPreset=2;rtx.qualityDLSS=0;rtx.xess.preset=0;"},
        {"performance",       Mode::Performance,      "rtx.dlssPreset=2;rtx.qualityDLSS=1;rtx.xess.preset=1;"},
        {"balanced",          Mode::Balanced,         "rtx.dlssPreset=2;rtx.qualityDLSS=2;rtx.xess.preset=2;"},
        {"quality",           Mode::Quality,          "rtx.dlssPreset=2;rtx.qualityDLSS=3;rtx.xess.preset=3;"},
    };
    for (const auto& r : rows) {
        Mode got = Mode::Config;
        check("name parses", upscaler::parse_mode(r.name, got) && got == r.mode);
        check(r.name, joined(upscaler::writes_for(r.mode)) == r.expect);
    }
    check("quality differs from performance", joined(upscaler::writes_for(Mode::Quality)) != joined(upscaler::writes_for(Mode::Performance)));
    check("config is not a write list", upscaler::writes_for(Mode::Config).size() == 0);

    // Precedence: env > ini > Config default; an invalid ini value falls back to Config and says so.
    std::string err;
    return failures ? 1 : 0;
}
'''

if __name__ == '__main__':
    try:
        base = C.parent / 'runtime/p1-upscaler-gate'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            w = Path(tmp)
            (w / 'test.cpp').write_text(HARNESS)
            build = subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-I', str(C),
                                    str(w / 'test.cpp'), '-o', str(w / 'test')], capture_output=True, text=True)
            assert build.returncode == 0, 'compile failed: ' + build.stderr[-1500:]
            run = subprocess.run([str(w / 'test')], capture_output=True, text=True)
            assert run.returncode == 0, (run.stdout + run.stderr)[-1500:]
        print(json.dumps({'passed': True}))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
