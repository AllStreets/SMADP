"""Reject malware-lure repos before they reach the catalog.

Bulk imports from ONEXUS-Agents pulled in GitHub repos that pose as
cracked or "activated" commercial software (Acrobat, AutoCAD, Copilot)
or as game cheats. Those repos are the usual way malware gets passed
around, and most had already been taken down by GitHub when they were
found here. A safety catalog must never list or link to them.

``lure_reason`` is checked in two places: the ONEXUS sync refuses to
promote a lure, and ``smadp lint`` fails on one, so a lure that arrives
by any other path still breaks CI.
"""

from __future__ import annotations

import re
from typing import Any

# Whole slug tokens only, so "delta-activations" and
# "leads-reactivation-..." stay legal.
_SLUG_TOKENS = re.compile(
    r"(?:^|-)(?:cracked|crack|keygen|activate|activator|warez|piracy|pirated)(?:-|$)"
)

# Phrases lure READMEs and repo descriptions use.
_TEXT_PHRASES = re.compile(
    r"(?i)\b(?:cracked version|full version free|free full version|premium unlocked|"
    r"license key generator|serial key|activation key|keygen|"
    r"unlocking advanced gameplay|pre-activated)\b"
)

# Lures caught by hand whose slugs carry no telltale word. Their GitHub
# accounts are throwaway names posing as paid software or cheat tools.
DENYLIST: frozenset[str] = frozenset(
    {
        "ableton-live-studio-engine-26",
        "ai-image-generator-2026",
        "comfyui-center",
        "davinchi-resolve-studio-v20-3-windows",
        "krisp-2026",
        "obsidian-claw-skill",
    }
)


def _text_fields(profile: dict[str, Any]) -> list[str]:
    onexus = profile.get("onexus") or {}
    fields = [profile.get("name"), profile.get("tagline"), profile.get("description")]
    fields += [onexus.get("source_github"), onexus.get("description")]
    return [f for f in fields if isinstance(f, str)]


def lure_reason(profile: dict[str, Any]) -> str | None:
    """Why this profile looks like a malware lure, or None if it doesn't."""
    slug = profile.get("slug")
    if isinstance(slug, str):
        if slug in DENYLIST:
            return f"slug {slug!r} is on the lure denylist"
        if _SLUG_TOKENS.search(slug):
            return f"slug {slug!r} names cracked or pirated software"
    for text in _text_fields(profile):
        match = _TEXT_PHRASES.search(text)
        if match:
            return f"text contains lure phrase {match.group(0)!r}"
    return None
