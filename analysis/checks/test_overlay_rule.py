#!/usr/bin/env python3
"""Gate for L7's overlay rule (checks/overlay_rule.h): the blend-state classes measured on the two reference captures."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

C = Path(__file__).resolve().parent
SRC = r'''
#include "overlay_rule.h"
#include <cstdio>
int main() {
    int f = 0;
    auto t = [&](const char* what, bool got, bool want) { if (got != want) { ++f; std::printf("FAIL %s\n", what); } };
    t("opaque draw", overlay_rule::is_overlay(false, 2, 1, true, false), false);
    t("lit alpha-blended decal with depth write (cd8687d6, f5be3a42)", overlay_rule::is_overlay(true, 5, 6, true, true), false);
    t("alpha-blended with depth write but untraced is still kept", overlay_rule::is_overlay(true, 5, 6, true, false), false);
    t("unlit alpha sheet without depth write (3fefc02f, 483f6bd1)", overlay_rule::is_overlay(true, 5, 6, false, false), true);
    t("lit alpha surface without depth write (glass) kept", overlay_rule::is_overlay(true, 5, 6, false, true), false);
    t("multiplicative DEST_COLOR x ZERO (33856d1d)", overlay_rule::is_overlay(true, 9, 1, true, false), true);
    t("multiplicative ZERO x SRC_COLOR", overlay_rule::is_overlay(true, 1, 3, true, true), true);
    t("additive SRC_ALPHA x ONE", overlay_rule::is_overlay(true, 5, 2, false, true), true);
    std::printf("failures=%d\n", f);
    return f ? 1 : 0;
}
'''


def main():
    work = Path(tempfile.mkdtemp(prefix='overlay-rule-'))
    (work / 't.cpp').write_text(SRC)
    subprocess.run(['g++', '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-I', str(C),
                    str(work / 't.cpp'), '-o', str(work / 't')], check=True)
    r = subprocess.run([str(work / 't')], capture_output=True, text=True)
    ok = r.returncode == 0
    print(json.dumps({'passed': ok, 'output': r.stdout.strip()}))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
