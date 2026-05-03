"""Lucide SVG icon constants used by passport templates.

These are minified Lucide SVGs (https://lucide.dev) embedded as strings so passports
are fully self-contained — no external <link> or <img>. Stroke-current so they
inherit color from CSS.
"""

from __future__ import annotations

# Each SVG is the inner Lucide markup with stroke="currentColor". Class is injected
# at render-time so callers can theme. viewBox is always 0 0 24 24 (Lucide standard).

_BASE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round"{class_attr}>{body}</svg>'
)

_BODIES: dict[str, str] = {
    "shield": (
        '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6'
        'a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5'
        'a1 1 0 0 1 1 1z"/>'
    ),
    "check_circle": (
        '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>'
    ),
    "alert_triangle": (
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>'
        '<path d="M12 9v4"/><path d="M12 17h.01"/>'
    ),
    "file_text": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
        '<line x1="16" y1="13" x2="8" y2="13"/>'
        '<line x1="16" y1="17" x2="8" y2="17"/>'
        '<line x1="10" y1="9" x2="8" y2="9"/>'
    ),
    "link": (
        '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
        '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'
    ),
    "lock": (
        '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    "fingerprint": (
        '<path d="M12 10v4"/><path d="M12 18v.01"/>'
        '<path d="M5 13a7 7 0 1 1 14 0v3a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-3z"/>'
    ),
}

LUCIDE_ICONS: dict[str, str] = {
    name: _BASE.format(class_attr="", body=body) for name, body in _BODIES.items()
}


def render_icon(name: str, *, css_class: str | None = None) -> str:
    """Return the SVG string for ``name``, optionally with a CSS class injected."""
    if name not in _BODIES:
        raise KeyError(f"Unknown Lucide icon: {name!r}")
    class_attr = f' class="{css_class}"' if css_class else ""
    return _BASE.format(class_attr=class_attr, body=_BODIES[name])


__all__ = ["LUCIDE_ICONS", "render_icon"]
