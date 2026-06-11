"""PolicyPublisher: route verdicts to verdicts/ or pending/ by evidence tier."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

# Allowed keys for each capability/IO block the Profile schema expects to be
# an object. The schema uses extra="forbid", so an off-vocabulary key (e.g.
# calls_apis under capabilities) is rejected. An LLM extraction emits these
# blocks as null, the wrong type, or with off-schema keys; left as-is they
# fail `smadp lint` and redden CI on every autopilot push. Mirrors the
# sub-models in smadp/schemas/profile.py.
_BLOCK_FIELDS: dict[str, frozenset[str]] = {
    "capabilities": frozenset(
        {
            "execute_shell",
            "read_filesystem",
            "write_filesystem",
            "network_egress",
            "spawn_subprocesses",
            "use_mcp",
            "modify_git_state",
            "install_packages",
            "run_browsers",
        }
    ),
    "io_surfaces": frozenset(
        {"stdin_stdout", "files", "clipboard", "screen_capture", "audio", "calls_apis"}
    ),
    "permissions_requested": frozenset({"oauth_scopes", "secrets_handled", "elevated_privileges"}),
    "sandboxing": frozenset({"self_isolation", "subagent_model", "tool_use_pattern"}),
    "concurrency_model": frozenset(
        {"session_scope", "shared_state_with_other_instances", "supports_multiple_instances"}
    ),
}
_NETWORK_EGRESS_ENUM = {"none", "allowlisted", "vendor-only", "broad"}


def normalize_profile_blocks(profile: dict[str, Any]) -> dict[str, Any]:
    """Coerce the capability/IO blocks of an enriched profile to schema-valid
    shapes in place.

    - Any required object block that is null / missing / not a dict becomes
      ``{}`` so the schema defaults apply.
    - Within each block, drop keys the schema doesn't define (the schema uses
      ``extra="forbid"``, so an off-vocabulary key like ``calls_apis`` under
      ``capabilities`` is rejected). Known keys — including null-valued ones the
      lint tolerates — are preserved, so valid profiles aren't churned.
    - ``capabilities.network_egress`` emitted as a bool maps to the enum
      (True -> "broad", False -> "none"); any other off-vocabulary value falls
      back to "none".

    Only enriched profiles routed through the publisher are affected; the
    partial ``unverified-profile`` stubs use a different path and are untouched.
    """
    for block, allowed in _BLOCK_FIELDS.items():
        value = profile.get(block)
        if isinstance(value, dict):
            profile[block] = {k: v for k, v in value.items() if k in allowed}
        elif block == "io_surfaces":
            # The only block the schema marks required-present; null/missing
            # would fail lint. Others may stay null (the lint tolerates it),
            # so we leave them to avoid churning valid profiles.
            profile[block] = {}

    caps = profile.get("capabilities")
    if isinstance(caps, dict):
        egress = caps.get("network_egress")
        if isinstance(egress, bool):
            caps["network_egress"] = "broad" if egress else "none"
        elif egress is not None and egress not in _NETWORK_EGRESS_ENUM:
            caps["network_egress"] = "none"

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
