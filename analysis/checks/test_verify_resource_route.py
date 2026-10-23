import re
import unittest
from pathlib import Path
from verify_resource_route import verify

ROOT = Path(__file__).resolve().parents[1] / "offline-routing"
TRACE = (ROOT / "work/chain-checked/texture-map.log").read_text()
OUTPUT = (ROOT / "logs/chain-checked/steam-0.log").read_text()


def drop(trace, pattern):
    """Remove one matching line, then renumber so only the semantic check can fail."""
    lines = trace.splitlines()
    index = next(i for i, line in enumerate(lines) if re.search(pattern, line))
    del lines[index]
    return "\n".join(re.sub(r"event=\d+", f"event={i + 1}", line) for i, line in enumerate(lines))


class VerifyResourceRouteTest(unittest.TestCase):
    def test_retained_trace_passes(self):
        self.assertTrue(verify(TRACE, OUTPUT)["passed"])

    def test_trace_error_rejected(self):
        with self.assertRaisesRegex(ValueError, "trace error"):
            verify(TRACE + "\nERROR: CAPTURE_TRUNCATED event_limit=100000", OUTPUT)

    def test_reordered_events_rejected(self):
        lines = TRACE.splitlines()
        lines[3], lines[4] = lines[4], lines[3]
        with self.assertRaisesRegex(ValueError, "reordered"):
            verify("\n".join(lines), OUTPUT)

    def test_missing_draw_rejected(self):
        with self.assertRaisesRegex(ValueError, "DrawIndexed"):
            verify(drop(TRACE, r" DrawIndexed-entry "), OUTPUT)

    def test_missing_keep_observation_rejected(self):
        with self.assertRaisesRegex(ValueError, "KEEP"):
            verify(drop(TRACE, r"stage=OMUAV-observed slot=7"), OUTPUT)

    def test_missing_readback_rejected(self):
        with self.assertRaisesRegex(ValueError, "draw-instanced"):
            verify(TRACE, OUTPUT.replace("CHECK draw-instanced PASS", "CHECK draw-instanced FAIL"))

    def test_incompatible_copy_rejected(self):
        bad = re.sub(r"(CopyResource ctx=\S+ .*?dst_w=)32", r"\g<1>64", TRACE, count=1)
        with self.assertRaisesRegex(ValueError, "incompatible full copy"):
            verify(bad, OUTPUT)


if __name__ == "__main__":
    unittest.main()
