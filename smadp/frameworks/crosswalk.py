"""Deterministic supplemental framework coverage cross-walk.

Inputs: a verdict's flagged risk taxonomy entries + the frameworks fixture.
Output: ``{framework_id: [control_id, ...]}`` — every control whose
``applies_to_risks`` set intersects the verdict's risks.

Pure / deterministic / sorted: identical inputs always produce identical bytes.
The judge-emitted ``verdict.framework_mappings`` is independent and not modified.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_FRAMEWORKS_JSON: Final[Path] = REPO_ROOT / "catalog" / "_meta" / "frameworks.json"


def load_frameworks_meta() -> dict[str, dict[str, Any]]:
    raw = json.loads(_FRAMEWORKS_JSON.read_text("utf-8"))
    if isinstance(raw, dict) and "frameworks" in raw:
        items = raw["frameworks"]
    elif isinstance(raw, list):
        items = raw
    else:
        assert isinstance(raw, dict)
        return {str(k): dict(v) for k, v in raw.items()}
    return {fw["id"]: fw for fw in items}


def compute_framework_coverage(
    *,
    verdict_risks: list[str],
    frameworks_meta: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    risks_set = set(verdict_risks)
    out: dict[str, list[str]] = {}
    if not risks_set:
        return out
    for fw_id in sorted(frameworks_meta.keys()):
        fw = frameworks_meta[fw_id]
        hits: list[str] = []
        for control in fw.get("controls", []):
            applies = set(control.get("applies_to_risks", []))
            if applies & risks_set:
                hits.append(control["id"])
        if hits:
            out[fw_id] = sorted(hits)
    return out


def framework_coverage_delta(
    *,
    old: dict[str, list[str]],
    new: dict[str, list[str]],
) -> dict[str, dict[str, list[str]]]:
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    all_fw = set(old) | set(new)
    for fw_id in sorted(all_fw):
        old_set = set(old.get(fw_id, []))
        new_set = set(new.get(fw_id, []))
        added_ids = sorted(new_set - old_set)
        removed_ids = sorted(old_set - new_set)
        if added_ids:
            added[fw_id] = added_ids
        if removed_ids:
            removed[fw_id] = removed_ids
    return {"added": added, "removed": removed}


__all__ = [
    "compute_framework_coverage",
    "framework_coverage_delta",
    "load_frameworks_meta",
]
