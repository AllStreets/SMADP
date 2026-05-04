"""Generate unverified Profile JSON files from the v2-E ontology.

Idempotent: skips files that already exist unless --force is passed.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from scripts.v2_e.ontology import CATEGORY_PRESETS, SEEDS, Seed

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "catalog" / "profiles" / "_unverified"
TIMESTAMP = "2026-05-04T00:00:00Z"


def build_profile(seed: Seed) -> dict:
    """Build a Profile dict from a Seed, validating against schema constraints."""
    preset = CATEGORY_PRESETS.get(seed["category"])
    if preset is None:
        raise SystemExit(f"No preset for category {seed['category']!r} (slug={seed['slug']})")

    body: dict = {
        "schema_version": "1.1",
        "slug": seed["slug"],
        "name": seed["name"],
        "tagline": seed["tagline"],
        "vendor": {"type": seed["vendor_type"], "handle": seed["vendor_handle"]},
        "source_type": seed["source_type"],
        "category": seed["category"],
        "verification": {
            "status": "unverified",
            "verified_by": None,
            "verified_at": TIMESTAMP,
            "method": "auto-only",
        },
        "capabilities": copy.deepcopy(preset["capabilities"]),
        "io_surfaces": copy.deepcopy(preset["io_surfaces"]),
        "permissions_requested": {
            "oauth_scopes": [],
            "secrets_handled": [],
            "elevated_privileges": [],
        },
        "data_classes_touched": list(preset["data_classes_touched"]),
        "sandboxing": copy.deepcopy(preset["sandboxing"]),
        "concurrency_model": copy.deepcopy(preset["concurrency_model"]),
        "evidence_refs": [],
        "first_seen_at": TIMESTAMP,
        "last_refreshed_at": TIMESTAMP,
        "pairings": [],
    }

    # Optionally include homepage/repo_url if present in seed.
    if seed["homepage"]:
        body["homepage"] = seed["homepage"]
    if seed["repo_url"]:
        body["repo_url"] = seed["repo_url"]

    return body


def write_all(out_dir: Path, *, force: bool) -> tuple[int, int]:
    """Write all 70 profile JSON files to out_dir. Return (written, skipped)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    for seed in SEEDS:
        path = out_dir / f"{seed['slug']}.json"
        if path.exists() and not force:
            skipped += 1
            continue
        body = build_profile(seed)
        path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written += 1
    return written, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    written, skipped = write_all(args.out, force=args.force)
    print(f"wrote {written} profile(s), skipped {skipped}")


if __name__ == "__main__":
    main()
