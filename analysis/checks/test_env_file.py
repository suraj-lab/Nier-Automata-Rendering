#!/usr/bin/env python3
"""Gate for env_file.h: the NIER_ENV.ini parser that lets a Windows Steam launch carry NIER_* settings.

Pins: KEY=VALUE lines, trimmed; comments and blank lines skipped; CRLF and a UTF-8 BOM tolerated; only
NIER_[A-Z0-9_]+ keys accepted (a settings file must not be able to set PATH or anything else); values keep inner
spaces and '=' (Windows paths); oversize files ignored. Native build with sanitizers.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

C = Path(__file__).resolve().parent
SOURCE = r'''
#include "env_file.h"
#include <cstdio>
int failures = 0;
#define CHECK(x) do { if (!(x)) { std::printf("VIOLATION %s\n", #x); ++failures; } } while (0)
int main() {
    const auto v = env_file::parse(
        "\xEF\xBB\xBF# comment\r\n"
        "NIER_REMIX=1\r\n"
        "  NIER_REMIX_RUNTIME = C:\\Program Files\\NVIDIA Corporation\\x=y\\d3d9.dll  \r\n"
        "; another comment\n"
        "\n"
        "PATH=C:\\evil\n"
        "nier_lower=1\n"
        "NIER_=empty-suffix\n"
        "NIER_BAD-KEY=1\n"
        "NIER_NO_EQUALS\n"
        "NIER_EMPTY=\n"
        "NIER_LAST=end");
    CHECK(v.size() == 4);
    CHECK(v.size() > 0 && v[0].first == "NIER_REMIX" && v[0].second == "1");
    CHECK(v.size() > 1 && v[1].first == "NIER_REMIX_RUNTIME" &&
          v[1].second == "C:\\Program Files\\NVIDIA Corporation\\x=y\\d3d9.dll");
    CHECK(v.size() > 2 && v[2].first == "NIER_EMPTY" && v[2].second.empty());
    CHECK(v.size() > 3 && v[3].first == "NIER_LAST" && v[3].second == "end");
    CHECK(env_file::parse("").empty());
    CHECK(env_file::parse(std::string(env_file::kMaxBytes + 1, '#') + "\nNIER_REMIX=1").empty());
    std::printf("failures=%d\n", failures);
    return failures ? 1 : 0;
}
'''


def main():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / 'gate.cpp').write_text(SOURCE)
        r = subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                            '-fno-sanitize-recover=all', '-I', str(C), str(d / 'gate.cpp'), '-o', str(d / 'gate')],
                           capture_output=True, text=True)
        if r.returncode:
            print(json.dumps({'passed': False, 'error': 'build:\n' + r.stderr[-1500:]}, indent=2))
            sys.exit(1)
        r = subprocess.run([str(d / 'gate')], capture_output=True, text=True)
        ok = r.returncode == 0
        print(json.dumps({'passed': ok, 'observed': r.stdout.strip()[-800:]}, indent=2))
        sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
