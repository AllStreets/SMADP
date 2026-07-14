#!/usr/bin/env python3
"""Regenerate hardcoded counts in README.md and .github/assets/smadp-banner.svg
from the current catalog state.

Run by the autopilot loop on each tick (and manually if needed). Idempotent:
if all numbers are already accurate, no file is rewritten and the autopilot's
git_sync step won't have anything to commit.

Surfaces updated:
  - README badges: profiles, verdicts, sandbox-validated, MCP_adapters
  - README inline catalog-layout table mentions (~N today)
  - README repo-layout code block ("# N Safety Profiles", etc.)
  - Banner SVG stats: profiles (round-down-to-250), verdicts
    (round-down-to-50), sandbox-validated (exact)
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
BANNER = REPO / ".github" / "assets" / "smadp-banner.svg"


def count_glob(rel: str) -> int:
    return len(list(REPO.glob(rel)))


def count_verdicts() -> int:
    """Published verdicts, excluding detached BYOK signature sidecars.

    Each verdict can have a sibling ``<key>.sig.json`` signature sidecar in
    catalog/verdicts/; those are not verdicts and must not be counted (a naive
    ``*.json`` glob double-counts to 2x the real total).
    """
    return sum(
        1
        for p in (REPO / "catalog" / "verdicts").glob("*.json")
        if not p.name.endswith(".sig.json")
    )


def count_profiles() -> int:
    """Total agents profiled: verified top-level + unverified seeds.

    Matches the homepage's "AGENTS PROFILED" tile, which renders
    getProfiles() in site/src/data/catalog.ts and walks both
    catalog/profiles/*.json and catalog/profiles/_unverified/*.json.
    Keeping the two counts in lockstep is the whole point of this
    script.
    """
    verified = count_glob("catalog/profiles/*.json")
    unverified = count_glob("catalog/profiles/_unverified/*.json")
    return verified + unverified


def count_sandbox_validated() -> int:
    needle = '"sandbox-validated"'
    n = 0
    for p in (REPO / "catalog" / "verdicts").glob("*.json"):
        if p.name.endswith(".sig.json"):
            continue  # detached BYOK signature sidecar, not a verdict
        try:
            if needle in p.read_text(encoding="utf-8"):
                n += 1
        except Exception:
            pass
    return n


def count_adapters() -> int:
    d = REPO / "adapters"
    if not d.exists():
        return 0
    return sum(1 for x in d.iterdir() if x.is_dir())


def fmt(n: int) -> str:
    return f"{n:,}"


def fmt_url(n: int) -> str:
    # shields.io URL-encodes a literal "," as %2C.
    return fmt(n).replace(",", "%2C")


def round_down(n: int, step: int) -> int:
    return (n // step) * step


def update_readme(
    profiles: int,
    verdicts: int,
    sandbox: int,
    adapters: int,
) -> bool:
    text = README.read_text(encoding="utf-8")
    new = text

    # Badge URLs
    new = re.sub(
        r"badge/profiles-[^\-]+-7C3AED",
        f"badge/profiles-{fmt_url(profiles)}-7C3AED",
        new,
    )
    new = re.sub(
        r"badge/verdicts-[^\-]+-A78BFA",
        f"badge/verdicts-{fmt_url(verdicts)}-A78BFA",
        new,
    )
    new = re.sub(
        r"badge/sandbox--validated-\d+-22C55E",
        f"badge/sandbox--validated-{sandbox}-22C55E",
        new,
    )
    new = re.sub(
        r"badge/MCP_adapters-[^\-]+-06B6D4",
        f"badge/MCP_adapters-{fmt_url(adapters)}-06B6D4",
        new,
    )

    # Inline catalog-layout mentions.
    new = re.sub(
        r"(One Safety Profile per agent\. ~)[\d,]+( today\.)",
        rf"\g<1>{fmt(profiles)}\g<2>",
        new,
    )
    new = re.sub(
        r"(verdicts that an operator has approved\. ~)[\d,]+( today\.)",
        rf"\g<1>{fmt(verdicts)}\g<2>",
        new,
    )

    # Repo-layout block.
    new = re.sub(
        r"(profiles/\s+#\s+)[\d,]+( Safety Profiles)",
        rf"\g<1>{fmt(profiles)}\g<2>",
        new,
    )
    new = re.sub(
        r"(verdicts/\s+#\s+)\d+( approved verdicts)",
        rf"\g<1>{verdicts}\g<2>",
        new,
    )

    if new == text:
        return False
    README.write_text(new, encoding="utf-8")
    return True


def update_banner(profiles: int, verdicts: int, sandbox: int) -> bool:
    if not BANNER.exists():
        return False
    text = BANNER.read_text(encoding="utf-8")
    new = text
    # The banner's "profiles" stat reads as a round display value with "+".
    # Round down to the nearest 250 so we under-promise rather than over.
    new = re.sub(
        r'fill="#e6dffa">[\d,]+\+</text>',
        f'fill="#e6dffa">{fmt(round_down(profiles, 250))}+</text>',
        new,
        count=1,
    )
    # Verdicts: same idea, nearest 50.
    new = re.sub(
        r'fill="#A78BFA">[\d,]+\+</text>',
        f'fill="#A78BFA">{fmt(round_down(verdicts, 50))}+</text>',
        new,
        count=1,
    )
    # Sandbox-validated stays exact — the meaningful number stays precise.
    new = re.sub(
        r'fill="url\(#tierGreen\)">\d+</text>',
        f'fill="url(#tierGreen)">{sandbox}</text>',
        new,
        count=1,
    )
    if new == text:
        return False
    BANNER.write_text(new, encoding="utf-8")
    return True


def main() -> int:
    profiles = count_profiles()
    verdicts = count_verdicts()
    sandbox = count_sandbox_validated()
    adapters = count_adapters()

    readme_changed = update_readme(profiles, verdicts, sandbox, adapters)
    banner_changed = update_banner(profiles, verdicts, sandbox)

    parts = [
        f"profiles={profiles}",
        f"verdicts={verdicts}",
        f"sandbox={sandbox}",
        f"adapters={adapters}",
    ]
    suffix = "updated" if (readme_changed or banner_changed) else "no change"
    print(f"stats: {' '.join(parts)} -> {suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
