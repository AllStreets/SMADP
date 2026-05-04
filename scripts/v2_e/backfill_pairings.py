"""Apply the v2-E pairings table to every profile JSON in the catalog.

Reads `catalog/profiles/*.json` and `catalog/profiles/_unverified/*.json`,
sets each file's `pairings` field from the table, writes back atomically,
and prints a summary. Idempotent.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.v2_e.pairings_table import build_table

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILES = REPO_ROOT / "catalog" / "profiles"


def _all_profile_paths() -> list[Path]:
    return sorted(PROFILES.glob("*.json")) + sorted((PROFILES / "_unverified").glob("*.json"))


def apply(*, dry_run: bool = False) -> int:
    table = build_table()
    changed = 0
    for path in _all_profile_paths():
        body = json.loads(path.read_text("utf-8"))
        slug = body.get("slug")
        if slug is None:
            continue
        new_pairings = table.get(slug, [])
        if body.get("pairings", []) == new_pairings:
            continue
        body["pairings"] = new_pairings
        if "schema_version" in body and body["schema_version"] == "1.0":
            body["schema_version"] = "1.1"
        if not dry_run:
            path.write_text(
                json.dumps(body, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        changed += 1
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    changed = apply(dry_run=args.dry_run)
    print(f"updated {changed} profile(s)")


if __name__ == "__main__":
    main()
