#!/usr/bin/env python3
"""Frozen native gate for the ephemeral Remix base-game scale policy.
Usage: test_remix_scale.py <render_settings.h>; no DLL, game, or GPU is loaded.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HARNESS = r'''
#include "render_settings.h"
#include <cassert>
#include <cstdio>
#include <initializer_list>
#include <string_view>
using namespace render_settings;
int main() {
    unsigned checks = 0;
    for (Mode mode : {Mode::Native, Mode::Custom75}) {
        for (bool valid : {false, true}) {
            for (bool defaulted : {false, true}) {
                const Settings settings{mode, valid, defaulted};
                for (auto remix : {L"", L"0", L"1", L"true", L"01", L"1 ", L" 1", L"11"}) {
                    for (auto cheap : {L"", L"0", L"1", L"true", L"01", L"1 ", L" 1", L"11"}) {
                        const auto plan = startup_scale(settings, remix, cheap);
                        const bool enabled = valid && std::wstring_view(remix) == L"1" && std::wstring_view(cheap) == L"1";
                        assert(plan.remix_override == enabled);
                        assert(plan.scale == (enabled ? 0.5f : (mode == Mode::Native ? 1.0f : 0.75f)));
                        assert(settings.mode == mode && settings.valid == valid && settings.defaulted == defaulted);
                        ++checks;
                    }
                }
            }
        }
    }
    const auto missing = select(ReadState::Missing, L"");
    assert(missing.valid && missing.defaulted && missing.mode == Mode::Custom75);
    assert(startup_scale(missing, L"1", L"1").scale == 0.5f);
    for (auto state : {ReadState::Value, ReadState::Unreadable}) {
        const auto invalid = select(state, L"bad");
        const auto p = startup_scale(invalid, L"1", L"1");
        assert(!invalid.valid && !p.remix_override && p.scale == 1.0f);
    }
    assert(scale(Mode::Native) == 1.0f && scale(Mode::Custom75) == 0.75f);
    assert(name(Mode::Native) == L"Native" && name(Mode::Custom75) == L"Custom75");
    assert(!select(ReadState::Value, L"Remix50").valid); // override is never a persisted preset
    std::printf("{\"passed\":true,\"matrix_cases\":%u}\n", checks);
}
'''


def run(candidate):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'render_settings.h').write_bytes(Path(candidate).read_bytes())
        (root / 'gate.cpp').write_text(HARNESS)
        cmd = ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
               '-fno-sanitize-recover=all', str(root / 'gate.cpp'), '-o', str(root / 'gate')]
        built = subprocess.run(cmd, capture_output=True, text=True)
        assert built.returncode == 0, built.stderr[-2000:]
        result = subprocess.run([str(root / 'gate')], capture_output=True, text=True)
        assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]
        report = json.loads(result.stdout)
        assert report.get('passed') is True
        return report


if __name__ == '__main__':
    try:
        print(json.dumps(run(sys.argv[1])))
    except Exception as exc:
        print(json.dumps({'passed': False, 'error': str(exc)}))
        sys.exit(1)
