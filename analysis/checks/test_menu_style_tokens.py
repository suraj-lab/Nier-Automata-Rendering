"""Frozen handoff extraction gate; run by the lead, not the laptop helper."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "analysis/menu-design/design_handoff_nier_render_panel/README.md"
TARGET = ROOT / "analysis/menu-design/claude_style_tokens.json"
SOURCE_SHA256 = "450dc1568c9eb1c65461f2bd9459f31653a3adcbf8588d8acd518243c0db5e63"

EXPECTED = {
    "source": "design_handoff_nier_render_panel/README.md",
    "source_sha256": SOURCE_SHA256,
    "colors": {
        "surface": "#E8E3D3", "field": "#F3F0E6", "neutral": "#DCD7C6",
        "chip": "#D9D3C1", "rule": "#C9C2AE", "panel_border": "#B8B19C",
        "field_border": "#9C9580", "text": "#26272A", "secondary_text": "#55554C",
        "disabled_text": "#8E8A7C", "primary": "#48523C", "primary_hover": "#3A4330",
        "on_primary": "#F3F0E6", "pending_bg": "#E6D3A3", "pending_text": "#3A2E12",
        "error_bg": "#EBCFC4", "error_text": "#5A1E14", "error_badge": "#8E2F1E",
        "reason_text": "#6E2416",
    },
    "layout": {
        "width": 552, "nominal_height": 516, "corner_radius": 2, "viewport_inset": 32,
        "panel_padding": 24, "section_padding": 18, "row_gap": 10, "footer_gap": 12,
        "rule_thickness": 1, "button_height": 44, "combo_height": 46,
    },
    "typography": {
        "sans_family": "IBM Plex Sans", "mono_family": "IBM Plex Mono",
        "sans_weights": [400, 500, 600, 700], "mono_weights": [400, 500],
        "title_size": 20, "mode_size": 28, "startup_headline_size": 22,
        "control_size": 16, "body_size": 15, "secondary_size": 14, "label_size": 13,
        "runtime_hint_size": 13, "dimension_size": 19, "badge_size": 12,
        "title_tracking_em": 0.12, "label_tracking_em": 0.14,
    },
    "dpi_scales": [1, 1.5, 2],
    "glyphs": ["✕", "△", "↻", "⊘", "●", "✓", "▾", "▴", "→", "—", "×", "·"],
}


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Non-finite JSON constant: {value}")


def validate_types(actual, expected):
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys()
        for key in expected:
            validate_types(actual[key], expected[key])
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected)
        for item, reference in zip(actual, expected):
            validate_types(item, reference)
    elif isinstance(expected, (int, float)):
        assert type(actual) in (int, float), "Numeric tokens cannot be booleans or strings"
    else:
        assert type(actual) is type(expected)


def main():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256, "Handoff changed"
    data = json.loads(TARGET.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates,
                      parse_constant=reject_constant)
    validate_types(data, EXPECTED)
    assert data == EXPECTED, "Extracted tokens differ from the frozen design handoff"
    print(json.dumps({"passed": True, "colors": len(data["colors"]),
                      "layout_tokens": len(data["layout"]),
                      "typography_tokens": len(data["typography"]),
                      "source_sha256": SOURCE_SHA256}))


if __name__ == "__main__":
    main()
