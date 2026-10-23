#!/usr/bin/env python3
"""Check the fixed native/2x synthetic probe, rejecting older FSR providers."""
import json
import math
from pathlib import Path
import re
import struct
import sys


def verify(directory, width=640, height=360):
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError("output dimensions must be positive and even")
    results = (directory / "fsr-inference-results.txt").read_text()
    log = (directory / "NIER_FSR4.log").read_text()
    contexts = re.findall(
        r"FSR: context created, render (\d+x\d+) -> (\d+x\d+),.*?, provider (\S+)", log
    )
    native = f"{width}x{height}"
    reduced = f"{width // 2}x{height // 2}"
    expected = [(native, native, "4.1.1"), (reduced, native, "4.1.1")]
    checks = {
        "both contexts use FSR4.1.1": contexts == expected,
        "case dimensions match": all(
            f"CASE {name} render={render} output={native} frames=16" in results
            for name, render in (("native", native), ("upscale", reduced))
        ),
        "32 evaluations succeed": results.count(
            "api.EvaluateFeature(context, feature, parameters, nullptr): 0x00000001"
        ) == 32,
        "both readbacks pass": all(f"READBACK {name} PASS" in results for name in ("native", "upscale")),
        "probe completes": "RESULT exit=0" in results,
        "no readback failure": "FAIL" not in results,
        "no FSR validation error": "FSR error:" not in log,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("; ".join(failed) + f"; observed contexts={contexts}")
    images = {}
    for name in ("native", "upscale"):
        data = (directory / f"{name}-output.rgba16f").read_bytes()
        if len(data) != width * height * 8:
            raise ValueError(f"{name}: incorrect raw image size")
        minimum, maximum = math.inf, -math.inf
        first_rgb, varied = None, False
        for pixel in struct.iter_unpack("<4e", data):
            if not all(math.isfinite(value) for value in pixel[:3]) or pixel[:3] == (-2.0, -2.0, -2.0):
                raise ValueError(f"{name}: nonfinite or untouched pixel")
            if first_rgb is None:
                first_rgb = pixel[:3]
            elif pixel[:3] != first_rgb:
                varied = True
            minimum, maximum = min(minimum, *pixel[:3]), max(maximum, *pixel[:3])
        if not varied or not (-64 < minimum < maximum < 64 and maximum - minimum > 0.01):
            raise ValueError(f"{name}: implausible or uniform RGB output")
        images[name] = {"width": width, "height": height, "rgb_min": minimum, "rgb_max": maximum}
    return {"provider": "4.1.1", "evaluations": 32, "images": images, "passed": True}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: verify_fsr_inference.py <probe working directory>")
    try:
        print(json.dumps(verify(Path(sys.argv[1])), indent=2))
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
