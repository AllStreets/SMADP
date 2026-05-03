"""Tests for Lucide SVG icon constants used in passport rendering."""

from __future__ import annotations

import pytest

from smadp.passport import icons


def test_required_icons_present():
    """Plan 2 passport templates use this set; if any is missing, render breaks."""
    required = {
        "shield",
        "check_circle",
        "alert_triangle",
        "file_text",
        "link",
        "lock",
        "fingerprint",
    }
    available = set(icons.LUCIDE_ICONS.keys())
    assert required.issubset(available), f"missing: {required - available}"


def test_icons_are_well_formed_svg():
    for name, svg in icons.LUCIDE_ICONS.items():
        assert svg.startswith("<svg "), f"{name}: not an svg tag"
        assert svg.endswith("</svg>"), f"{name}: not closed"
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg, f"{name}: missing xmlns"
        assert "viewBox" in svg, f"{name}: missing viewBox"


def test_render_icon_returns_svg_with_class():
    out = icons.render_icon("shield", css_class="passport-icon")
    assert out.startswith("<svg ")
    assert 'class="passport-icon"' in out


def test_render_icon_unknown_raises():
    with pytest.raises(KeyError):
        icons.render_icon("not-a-real-icon")
