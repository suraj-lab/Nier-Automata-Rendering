#!/usr/bin/env python3
"""Frozen gate for measurements/sample_gpu.py; stdlib, fake sysfs, no GPU/game needed."""
import contextlib
import csv
import importlib.util
import io
import math
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "measurements" / "sample_gpu.py"
spec = importlib.util.spec_from_file_location("sample_gpu", SCRIPT)
gpu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gpu)


class SamplerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dev = Path(self.tmp.name) / "0000:03:00.0"
        self.dev.mkdir()
        self.put("vendor", "0x1002")
        self.put("device", "0x7550")
        self.put("gpu_busy_percent", "37")
        self.put("mem_info_vram_used", str(6 * 1024**3))
        self.put("hwmon/hwmon99/name", "amdgpu")
        self.put("hwmon/hwmon99/power1_average", "123456789")
        self.put("hwmon/hwmon99/temp1_input", "51000")
        self.put("hwmon/hwmon99/freq1_input", "2200000000")
        # An unrelated monitor must not be selected, even if it sorts first.
        self.put("hwmon/hwmon0/name", "unrelated")
        self.put("hwmon/hwmon0/power1_average", "999000000")

    def put(self, p, value):
        path = self.dev / p
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n")

    def test_units(self):
        s = gpu.sample(self.dev)
        self.assertEqual(s["gpu_busy_pct"], 37)
        self.assertAlmostEqual(s["power_w"], 123.456789)
        self.assertEqual(s["edge_c"], 51)
        self.assertEqual(s["clock_mhz"], 2200)
        self.assertEqual(s["vram_gib"], 6)

    def test_missing_optional_is_none_not_zero(self):
        for name in ("temp1_input", "freq1_input"):
            (self.dev / "hwmon/hwmon99" / name).unlink()
        (self.dev / "mem_info_vram_used").unlink()
        s = gpu.sample(self.dev)
        self.assertIsNone(s["edge_c"])
        self.assertIsNone(s["clock_mhz"])
        self.assertIsNone(s["vram_gib"])

    def test_nonfinite_optional_is_none_and_blank_csv(self):
        fields = ("edge_c", "clock_mhz", "vram_gib")
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value):
                self.put("hwmon/hwmon99/temp1_input", value)
                self.put("hwmon/hwmon99/freq1_input", value)
                self.put("mem_info_vram_used", value)
                sample = gpu.sample(self.dev)
                for field in fields:
                    self.assertIsNone(sample[field])
                out = Path(self.tmp.name) / f"{value}.csv"
                self.assertEqual(self.cli(["--device", str(self.dev), "--output", str(out),
                                           "--seconds", "0.001", "--interval", "0.001"]), 0)
                rows = list(csv.DictReader(io.StringIO(out.read_text())))
                self.assertTrue(rows)
                for row in rows:
                    for field in fields:
                        self.assertEqual(row[field], "")

    def test_missing_power_fallback(self):
        (self.dev / "hwmon/hwmon99/power1_average").unlink()
        self.put("hwmon/hwmon99/power1_input", "12000000")
        self.assertEqual(gpu.sample(self.dev)["power_w"], 12)
        (self.dev / "hwmon/hwmon99/power1_input").unlink()
        with self.assertRaises((OSError, ValueError)):
            gpu.sample(self.dev)

    def test_fail_closed_on_identity_and_required_sensors(self):
        for name, value in (("vendor", "0x10de"), ("device", "0x73bf"),
                            ("gpu_busy_percent", "garbage"), ("gpu_busy_percent", "101"),
                            ("gpu_busy_percent", "-1"), ("hwmon/hwmon99/power1_average", "nan"),
                            ("hwmon/hwmon99/power1_average", "-1")):
            with self.subTest(name=name, value=value):
                p = self.dev / name
                old = p.read_text()
                p.write_text(value)
                with self.assertRaises((OSError, ValueError)):
                    gpu.sample(self.dev)
                p.write_text(old)
        (self.dev / "gpu_busy_percent").unlink()
        with self.assertRaises((OSError, ValueError)):
            gpu.sample(self.dev)

    def cli(self, args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                return gpu.main(args)
            except SystemExit as e:
                return e.code

    def test_cli_csv_and_exclusive_output(self):
        out = Path(self.tmp.name) / "capture.csv"
        args = ["--device", str(self.dev), "--seconds", "0.03", "--interval", "0.01", "--output", str(out)]
        self.assertEqual(self.cli(args), 0)
        original = out.read_bytes()
        rows = list(csv.DictReader(io.StringIO(original.decode())))
        self.assertGreaterEqual(len(rows), 1)
        self.assertTrue({"utc", "elapsed_s", "pci", "vendor", "device", "gpu_busy_pct", "power_w",
                         "clock_mhz", "edge_c", "vram_gib"} <= set(rows[0]))
        elapsed = [float(r["elapsed_s"]) for r in rows]
        self.assertTrue(all(a <= b for a, b in zip(elapsed, elapsed[1:])))
        for r in rows:
            self.assertEqual(r["pci"], "0000:03:00.0")
            self.assertEqual(r["vendor"], "0x1002")
            self.assertEqual(r["device"], "0x7550")
            self.assertEqual(float(r["power_w"]), 123.456789)
            self.assertTrue(r["utc"].endswith(("Z", "+00:00")))
        self.assertNotEqual(self.cli(args), 0)
        self.assertEqual(out.read_bytes(), original)

    def test_invalid_durations_do_not_create_output(self):
        for option in ("--seconds", "--interval"):
            for value in ("0", "-1", "nan", "inf"):
                with self.subTest(option=option, value=value):
                    out = Path(self.tmp.name) / "invalid.csv"
                    self.assertNotEqual(self.cli(["--device", str(self.dev), "--output", str(out), option, value]), 0)
                    self.assertFalse(out.exists())

    def test_bad_device_does_not_create_output(self):
        self.put("device", "0x73bf")
        out = Path(self.tmp.name) / "wrong_gpu.csv"
        self.assertNotEqual(self.cli(["--device", str(self.dev), "--output", str(out), "--seconds", "0.02"]), 0)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
