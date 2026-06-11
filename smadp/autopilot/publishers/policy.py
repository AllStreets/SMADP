"""PolicyPublisher: route verdicts to verdicts/ or pending/ by evidence tier."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

# Capability/IO blocks the Profile schema expects to be objects (never null).
# An LLM extraction sometimes emits them as null or the wrong type; left as-is
# they fail `smadp lint` and redden CI on every autopilot push.
_OBJECT_BLOCKS = (
    "capabilities",
    "io_surfaces",
    "permissions_requested",
    "sandboxing",
    "concurrency_model",
)
_NETWORK_EGRESS_ENUM = {"none", "allowlisted", "vendor-only", "broad"}


def normalize_profile_blocks(profile: dict[str, Any]) -> dict[str, Any]:
    """Coerce the capability/IO blocks of an enriched profile to schema-valid
    shapes in place.

    - Any of the required object blocks that is null / missing / not a dict
      becomes ``{}`` so the schema defaults apply.
    - ``capabilities.network_egress`` emitted as a bool (a stale shape the LLM
      occasionally returns) maps to the enum: True -> "broad", False -> "none";
      any other off-vocabulary value falls back to "none".

    Deliberately does NOT strip null sub-values inside otherwise-valid blocks —
    the lint tolerates those, so touching them would only churn the catalog.
    Only enriched profiles routed through the publisher are affected; the
    partial ``unverified-profile`` stubs use a different path and are untouched.
    """
    for block in _OBJECT_BLOCKS:
        if not isinstance(profile.get(block), dict):
            profile[block] = {}

    egress = profile["capabilities"].get("network_egress")
    if isinstance(egress, bool):
        profile["capabilities"]["network_egress"] = "broad" if egress else "none"
    elif egress is not None and egress not in _NETWORK_EGRESS_ENUM:
        profile["capabilities"]["network_egress"] = "none"

    return profile


class PolicyPublisher:
    def __init__(self, *, catalog_root: Path, auto_publish: dict[str, bool]) -> None:
        self.catalog_root = catalog_root
        self.auto_publish = auto_publish

    def commit(self, verdict: dict[str, Any]) -> Path:
        tier = verdict.get("evidence_level", "docs-only")
        publish = self.auto_publish.get(tier, False)
        target_dir = self.catalog_root / ("verdicts" if publish else "pending")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{verdict['verdict_id']}.json"

        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", dir=target_dir)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(verdict, f, indent=2)
                f.write("\n")
            os.replace(tmp, target)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise
        return target

    def commit_profile(self, profile: dict[str, Any]) -> Path:
        # Guarantee schema-valid capability/IO blocks before writing so a
        # sparse or off-vocabulary LLM extraction can never redden the catalog.
        normalize_profile_blocks(profile)
        target_dir = self.catalog_root / "profiles"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{profile['slug']}.json"

        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", dir=target_dir)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2)
                f.write("\n")
            os.replace(tmp, target)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise
        return target
