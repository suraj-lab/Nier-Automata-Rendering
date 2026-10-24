#!/usr/bin/env python3
"""Frozen gate for analyze_framedump.py.

Runs the analyzer on two known dumps and asserts the exact scene/depth invariants.
This is the acceptance test for the analyzer implementation.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(path):
    p = subprocess.run([sys.executable, os.path.join(HERE, "analyze_framedump.py"), path],
                       capture_output=True, text=True)
    try:
        data = json.loads(p.stdout)
    except Exception:
        data = None
    return p.returncode, data


def main():
    # fixed dump: depth scaled to match scene AND 2D (array=1) -> exit 0
    rc, r = run(os.path.join(HERE, "fixtures", "fixed.txt"))
    assert rc == 0, f"fixed dump should exit 0, got {rc}: {r}"
    assert r["scene"]["w"] == 2580 and r["scene"]["h"] == 1080, r.get("scene")
    assert r["tone_map_rt"]["w"] == 3440 and r["tone_map_rt"]["h"] == 1440, r.get("tone_map_rt")
    assert r["depth_matches_scene"] is True, r

    # buggy dump: depth is the right SIZE but array=6 (cube) -> must NOT count as a match -> exit 1
    rc, r = run(os.path.join(HERE, "fixtures", "buggy.txt"))
    assert rc == 1, f"buggy dump should exit 1, got {rc}: {r}"
    assert r["depth_matches_scene"] is False, r

    print("test_analyze_framedump: all passed")


if __name__ == "__main__":
    main()
