"""Extend every verdict's framework_mappings to all 11 frameworks.

Reads `catalog/verdicts/*.json`, derives each verdict's "active" risks from its
sub-verdicts (severity >= medium), runs the deterministic crosswalk against
`catalog/_meta/frameworks.json`, and merges the result into the verdict's
existing `framework_mappings` (existing entries are preserved; only additions
are made). Writes back atomically. Idempotent.

Run:
  python -m scripts.v2_e.enrich_framework_mappings
  python -m scripts.v2_e.enrich_framework_mappings --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from smadp.frameworks.crosswalk import (
    compute_framework_coverage,
    load_frameworks_meta,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VERDICTS = REPO_ROOT / "catalog" / "verdicts"

ACTIVE_SEVERITIES = {"medium", "high"}


def active_risks(verdict: dict) -> list[str]:
    sub = verdict.get("sub_verdicts", {})
    return sorted(k for k, sv in sub.items() if sv.get("severity") in ACTIVE_SEVERITIES)


def merge_mappings(
    existing: dict[str, list[str]],
    derived: dict[str, list[str]],
) -> tuple[dict[str, list[str]], int]:
    out = {fw: list(ids) for fw, ids in existing.items()}
    added = 0
    for fw, ids in derived.items():
        current = set(out.get(fw, []))
        for cid in ids:
            if cid not in current:
                current.add(cid)
                added += 1
        out[fw] = sorted(current)
    return out, added


def apply(*, dry_run: bool = False) -> int:
    meta = load_frameworks_meta()
    paths = sorted(VERDICTS.glob("*.json"))
    total_changed = 0
    total_added = 0
    for path in paths:
        body = json.loads(path.read_text("utf-8"))
        risks = active_risks(body)
        derived = compute_framework_coverage(verdict_risks=risks, frameworks_meta=meta)
        existing = body.get("framework_mappings", {}) or {}
        merged, added = merge_mappings(existing, derived)
        if added == 0:
            continue
        total_changed += 1
        total_added += added
        body["framework_mappings"] = merged
        if not dry_run:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(body, indent=2) + "\n", "utf-8")
            tmp.replace(path)
    print(
        f"verdicts touched={total_changed}/{len(paths)}, control_ids added={total_added}"
        + (" (dry-run)" if dry_run else "")
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()
    return apply(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
