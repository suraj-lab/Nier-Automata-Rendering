import struct
import tempfile
import unittest
from pathlib import Path
from verify_fsr_inference import verify


class VerifyInferenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.results = (
            "CASE native render=4x2 output=4x2 frames=16\n"
            "CASE upscale render=2x1 output=4x2 frames=16\n"
            + "api.EvaluateFeature(context, feature, parameters, nullptr): 0x00000001\n" * 32
            + "READBACK native PASS\nREADBACK upscale PASS\nRESULT exit=0\n"
        )
        self.log = (
            "FSR: context created, render 4x2 -> 4x2, flags 0xA1, provider 4.1.1\n"
            "FSR: context created, render 2x1 -> 4x2, flags 0xA1, provider 4.1.1\n"
        )
        self.write_logs()
        for name in ("native", "upscale"):
            (self.path / f"{name}-output.rgba16f").write_bytes(struct.pack("<8e", 0.5, 1, 2, 1, 1, 2, 0.5, 1) * 4)

    def write_logs(self):
        (self.path / "fsr-inference-results.txt").write_text(self.results)
        (self.path / "NIER_FSR4.log").write_text(self.log)

    def test_valid(self):
        self.assertTrue(verify(self.path, 4, 2)["passed"])

    def test_provider_fallback(self):
        self.log = self.log.replace("4.1.1", "3.1.5")
        self.write_logs()
        with self.assertRaisesRegex(ValueError, "FSR4"):
            verify(self.path, 4, 2)

    def test_truncated_output(self):
        (self.path / "upscale-output.rgba16f").write_bytes(b"short")
        with self.assertRaisesRegex(ValueError, "raw image size"):
            verify(self.path, 4, 2)

    def test_wrong_case_dimensions(self):
        self.results = self.results.replace("output=4x2", "output=8x4")
        self.write_logs()
        with self.assertRaisesRegex(ValueError, "case dimensions"):
            verify(self.path, 4, 2)

    def test_untouched_output(self):
        (self.path / "native-output.rgba16f").write_bytes(struct.pack("<4e", -2, -2, -2, -2) * 8)
        with self.assertRaisesRegex(ValueError, "untouched pixel"):
            verify(self.path, 4, 2)

    def test_spatially_uniform_output(self):
        (self.path / "native-output.rgba16f").write_bytes(struct.pack("<4e", 0.5, 1, 2, 1) * 8)
        with self.assertRaisesRegex(ValueError, "uniform RGB"):
            verify(self.path, 4, 2)

    def test_invalid_dimensions(self):
        with self.assertRaisesRegex(ValueError, "positive and even"):
            verify(self.path, 3, 2)


if __name__ == "__main__":
    unittest.main()
