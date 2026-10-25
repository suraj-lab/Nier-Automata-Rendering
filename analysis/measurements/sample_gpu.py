#!/usr/bin/env python3
"""Sample an AMD RX 9070 (PCI 0x1002:0x7550) from sysfs into a CSV.

Fail closed: wrong GPU, missing/malformed required sensors raise.
Optional sensors (temp/freq/VRAM) come back as None, never 0.
"""
import argparse
import csv
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_VENDOR = 0x1002
EXPECTED_DEVICE = 0x7550
FIELDS = ["utc", "elapsed_s", "pci", "vendor", "device",
          "gpu_busy_pct", "power_w", "clock_mhz", "edge_c", "vram_gib"]


def _read_int(path):
    try:
        return int(path.read_text().strip())
    except ValueError as exc:
        raise ValueError(f"malformed {path}") from exc


def _read_finite_nonnegative(path):
    try:
        value = float(path.read_text().strip())
    except ValueError as exc:
        raise ValueError(f"malformed {path}") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{path} out of range: {value!r}")
    return value


def _optional(path, divisor):
    try:
        value = float(path.read_text().strip()) / divisor
        return value if math.isfinite(value) else None
    except (OSError, ValueError):
        return None


def _amdgpu_hwmon(device):
    hwmon = device / "hwmon"
    try:
        for entry in sorted(hwmon.iterdir()):
            try:
                if entry.is_dir() and (entry / "name").read_text().strip() == "amdgpu":
                    return entry
            except OSError:
                continue
    except FileNotFoundError:
        pass
    raise FileNotFoundError(f"no hwmon with name 'amdgpu' under {hwmon}")


def _pci_id(path, expected):
    try:
        value = int(path.read_text().strip(), 16)
    except ValueError as exc:
        raise ValueError(f"malformed {path}") from exc
    if value != expected:
        raise ValueError(f"not the target GPU: {path.name}=0x{value:x} (expected 0x{expected:x})")


def sample(device):
    _pci_id(device / "vendor", EXPECTED_VENDOR)
    _pci_id(device / "device", EXPECTED_DEVICE)

    busy = _read_int(device / "gpu_busy_percent")
    if not 0 <= busy <= 100:
        raise ValueError(f"gpu_busy_percent out of range: {busy}")

    hwmon = _amdgpu_hwmon(device)
    try:
        power_uw = _read_finite_nonnegative(hwmon / "power1_average")
    except FileNotFoundError:
        power_uw = _read_finite_nonnegative(hwmon / "power1_input")

    return {
        "gpu_busy_pct": busy,
        "power_w": power_uw / 1e6,
        "edge_c": _optional(hwmon / "temp1_input", 1000.0),
        "clock_mhz": _optional(hwmon / "freq1_input", 1e6),
        "vram_gib": _optional(device / "mem_info_vram_used", 1024 ** 3),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sample RX 9070 GPU sensors into a CSV.")
    parser.add_argument("--device", type=Path, default=Path("/sys/bus/pci/devices/0000:03:00.0"))
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    for label, value in (("--seconds", args.seconds), ("--interval", args.interval)):
        if not math.isfinite(value) or value <= 0:
            print(f"error: {label} must be > 0 and finite, got {value!r}", file=sys.stderr)
            return 2

    try:
        sample(args.device)  # preflight: fail closed before creating the output file
        vendor = (args.device / "vendor").read_text().strip()
        pci_device = (args.device / "device").read_text().strip()
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        out = open(args.output, "x", newline="")  # refuse to overwrite an existing capture
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    writer = csv.DictWriter(out, fieldnames=FIELDS)
    start = time.monotonic()
    try:
        with out:
            writer.writeheader()
            out.flush()
            while True:
                s = sample(args.device)
                row = {"utc": datetime.now(timezone.utc).isoformat(),
                       "elapsed_s": time.monotonic() - start,
                       "pci": args.device.resolve().name,
                       "vendor": vendor, "device": pci_device, **s}
                writer.writerow(row)
                out.flush()
                if time.monotonic() - start >= args.seconds:
                    break
                time.sleep(min(args.interval, max(0.0, args.seconds - (time.monotonic() - start))))
    except KeyboardInterrupt:
        print("interrupted: partial CSV retained for diagnosis (not complete)", file=sys.stderr)
        return 130
    except (OSError, ValueError) as exc:
        print(f"error: {exc} (partial CSV retained for diagnosis, not complete)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
