"""Deterministic capability-vector diffing for drift detection.

A capability vector canonicalizes a profile's safety-relevant surface so two
versions can be diffed and hashed. Pure functions, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from smadp.schemas.profile import Profile
from smadp.utils.hashing import sha256_canonical_json

EGRESS_ORDER: dict[str, int] = {
    "none": 0,
    "allowlisted": 1,
    "vendor-only": 2,
    "broad": 3,
}

_BOOL_FIELDS: tuple[str, ...] = (
    "execute_shell",
    "read_filesystem",
    "write_filesystem",
    "spawn_subprocesses",
    "use_mcp",
    "modify_git_state",
    "install_packages",
    "run_browsers",
)


def capability_vector(profile: Profile) -> dict[str, object]:
    """Canonical, sorted, JSON-able capability surface for hashing/diffing."""
    caps = profile.capabilities
    perms = profile.permissions_requested
    return {
        "booleans": {f: bool(getattr(caps, f)) for f in _BOOL_FIELDS},
        "network_egress": caps.network_egress,
        "oauth_scopes": sorted(perms.oauth_scopes),
        "secrets_handled": sorted(perms.secrets_handled),
        "elevated_privileges": sorted(perms.elevated_privileges),
        "data_classes_touched": sorted(profile.data_classes_touched),
    }


def capability_hash(profile: Profile) -> str:
    return "sha256:" + sha256_canonical_json(capability_vector(profile))


@dataclass(frozen=True)
class CapabilityChange:
    field: str
    direction: str  # "expansion" | "contraction"
    detail: str


@dataclass(frozen=True)
class CapabilityDiff:
    expansions: list[CapabilityChange] = field(default_factory=list)
    contractions: list[CapabilityChange] = field(default_factory=list)

    @property
    def has_expansion(self) -> bool:
        return bool(self.expansions)

    @property
    def summary(self) -> str:
        if not self.expansions and not self.contractions:
            return "no capability change"
        parts: list[str] = []
        if self.expansions:
            parts.append("expanded: " + ", ".join(c.field for c in self.expansions))
        if self.contractions:
            parts.append("narrowed: " + ", ".join(c.field for c in self.contractions))
        return "; ".join(parts)


def diff_capabilities(old: Profile, new: Profile) -> CapabilityDiff:
    exp: list[CapabilityChange] = []
    con: list[CapabilityChange] = []

    o, n = old.capabilities, new.capabilities
    for f in _BOOL_FIELDS:
        ov, nv = bool(getattr(o, f)), bool(getattr(n, f))
        if ov == nv:
            continue
        change = CapabilityChange(
            field=f,
            direction="expansion" if nv else "contraction",
            detail=f"{ov} -> {nv}",
        )
        (exp if nv else con).append(change)

    oe, ne = EGRESS_ORDER[o.network_egress], EGRESS_ORDER[n.network_egress]
    if ne > oe:
        exp.append(
            CapabilityChange(
                "network_egress", "expansion", f"{o.network_egress} -> {n.network_egress}"
            )
        )
    elif ne < oe:
        con.append(
            CapabilityChange(
                "network_egress", "contraction", f"{o.network_egress} -> {n.network_egress}"
            )
        )

    pairs = [
        (
            old.permissions_requested.oauth_scopes,
            new.permissions_requested.oauth_scopes,
            "permissions_requested.oauth_scopes",
        ),
        (
            old.permissions_requested.secrets_handled,
            new.permissions_requested.secrets_handled,
            "permissions_requested.secrets_handled",
        ),
        (
            old.permissions_requested.elevated_privileges,
            new.permissions_requested.elevated_privileges,
            "permissions_requested.elevated_privileges",
        ),
        (old.data_classes_touched, new.data_classes_touched, "data_classes_touched"),
    ]
    for ov_list, nv_list, label in pairs:
        added = sorted(set(nv_list) - set(ov_list))
        removed = sorted(set(ov_list) - set(nv_list))
        if added:
            exp.append(CapabilityChange(label, "expansion", "added: " + ", ".join(added)))
        if removed:
            con.append(CapabilityChange(label, "contraction", "removed: " + ", ".join(removed)))

    exp.sort(key=lambda c: c.field)
    con.sort(key=lambda c: c.field)
    return CapabilityDiff(expansions=exp, contractions=con)
