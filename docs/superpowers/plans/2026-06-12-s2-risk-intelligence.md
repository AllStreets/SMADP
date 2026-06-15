# S2 — Risk Intelligence Engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Pillar S2 of The Proving Ground: (S2.1) deterministic N-agent chain composition over existing pairwise verdicts, (S2.2) capability-drift tracking that flags expansions and stales affected verdicts, and (S2.3) a dependency-light learned triage model that re-orders the autopilot judge queue without ever publishing a number. Every ranking/publishing number stays in Python; the LLM only confirms uncertain composed chains symbolically. Nothing bypasses the operator gate, and every new automated path has a config kill switch.

**Architecture:**
- **S2.1** `smadp/analyzer/chains.py` — pure functions that take the constituent pairwise `Verdict` objects of a chain's adjacent links plus the chain topology/edges, and compute composed sub-verdict severities, composite score, and confidence deterministically. A composer driver (`smadp/autopilot/chain_composer.py`) walks `catalog/chains/*.json` (authored topology + participants), pulls each adjacent link's published pairwise verdict, composes, and writes a *composed chain candidate* into `catalog/pending/chains/`. Candidates whose composed confidence falls below a publish threshold are flagged for the LLM judge (bounded batch via existing `LLMClient`) which may only supply narrative/severity *symbols* — Python still computes the composite. Operator promotes `catalog/pending/chains/<id>.json` → `catalog/chains/<id>.json`.
- **S2.2** Additive schema bump `Profile.schema_version 1.1 → 1.2` adding optional append-only `capability_history[]`. `smadp/analyzer/capability_drift.py` diffs an old vs new `Capabilities`/egress/oauth block and classifies each change as expansion / contraction / neutral. A refresh hook appends a history entry, and on any expansion: emits a `capability_drift` chronicle event, sets `stale_reason: capability_drift` on every verdict touching that slug (additive optional `Verdict.stale_reason`), and the daily report grows a "Capability creep" section.
- **S2.3** `smadp/analyzer/triage.py` — a pure-Python (stdlib `math` only, no numpy/sklearn) L2-regularized logistic-regression-per-band classifier. A checked-in training script (`scripts/train_triage.py`) reads published verdicts, featurizes the two profiles' capability vectors + category pair, fits, and writes a versioned JSON artifact (`catalog/_meta/triage/<version>.json`) carrying the training-set hash and learned weights. `triage.predict()` returns a predicted composite band + uncertainty. The autopilot tick / pair-gate planner consults triage to *deprioritize* high-confidence-safe pairs and *front-load* uncertain/risky pairs. Predictions are never written as verdicts.

**Tech Stack:** Python 3.11, Pydantic v2, Click CLI, FastAPI (existing `/api/chains` router extended read-only), pytest (`asyncio_mode=auto`, `filterwarnings=error`). **No new runtime dependencies** — `scikit-learn`/`numpy` are absent from `pyproject.toml` and `uv.lock`; triage is implemented with the stdlib `math` module to honor the spec's "dependency-light" clause. Determinism is guaranteed by a fixed seed and sorted iteration, not by a numeric library.

## Spec deviations

1. **Triage uses pure-Python logistic regression, not scikit-learn.** The spec text names "logistic regression / gradient boosting over scikit-learn" but the real `pyproject.toml`/`uv.lock` ship neither sklearn nor numpy, and the spec's own constraint is "dependency-light … model artifact versioned with its training-set hash." Adding sklearn (+numpy/scipy, ~80 MB) to a project whose entire dep set is intentionally minimal is disproportionate for a logistic classifier over ≤30 binary/ordinal features. We implement multinomial-ish one-vs-rest logistic regression in stdlib `math`, deterministic under a fixed seed, with the same versioned-artifact + training-set-hash contract the spec requires. If a future need for GBM accuracy appears, sklearn can be added then with justification. This is the only material deviation.
2. **Composed chain candidates land in `catalog/pending/chains/`, not the flat `catalog/pending/`.** The spec says "chain verdicts in `catalog/pending/` → operator gate → `catalog/chains/`." The existing `catalog/pending/` is typed for pairwise `Verdict` files (strict `verdict_id` regex, 2–4 participants) and is drained by `smadp.autopilot.pending`. A composed *chain* is a `Chain` model, not a `Verdict`. To reuse the operator-gate pattern without breaking the pending-verdict reader, composed chains go to a `pending/chains/` subdirectory with their own approve path (`smadp autopilot approve-chain`). Same gate semantics (human file-move/approve), different model. Noted so reviewers don't expect chain files in the pairwise pending queue.
3. **`Chain.schema_version` bumps `1.0 → 1.1`** (additive) to carry composition provenance (`composed_from[]`, `composition_method`, optional `stale_reason`). The spec only explicitly bumps the Profile schema, but composed chains need to record which pairwise verdicts they were derived from for reproducibility; this is additive and older fixtures still validate because the new fields are optional.
4. **Triage feeds the planner layer (`PairGatePlanner`/`TopNPlanner` ordering), not `tick.run_tick` directly.** The spec says "deprioritized in the autopilot tick planner." `run_tick` consumes a pre-built `catalog/priority.yaml`; the actual pair *selection/ordering* happens in the planners that emit `WorkItem`s. We inject triage there (where priorities are computed) which is the faithful realization of "judge spend concentrates where it matters." `run_tick` is unchanged.

## File Structure

| Path | New/Modified | Purpose |
|---|---|---|
| `smadp/analyzer/chains.py` | new | Deterministic chain composition (pure functions). |
| `smadp/autopilot/chain_composer.py` | new | Driver: walk authored chains, pull links, compose, write candidates, flag judge batch. |
| `smadp/analyzer/capability_drift.py` | new | Diff two capability blocks → classified expansions/contractions. |
| `smadp/analyzer/triage.py` | new | Featurize + load artifact + predict band/uncertainty (stdlib only). |
| `scripts/train_triage.py` | new | Checked-in training script → versioned artifact. |
| `smadp/schemas/profile.py` | modified | `schema_version 1.2`; add `CapabilityHistoryEntry` + `capability_history`. |
| `smadp/schemas/chain.py` | modified | `schema_version 1.1`; add `composed_from`, `composition_method`, `stale_reason`. |
| `smadp/schemas/verdict.py` | modified | add optional `stale_reason`. |
| `smadp/schemas/chronicle.py` | modified | add `capability_drift` event type. |
| `smadp/autopilot/config.py` | modified | load `chain_composition` + `triage` kill-switch / threshold keys. |
| `config/autopilot.yaml` | modified | declare new config keys. |
| `smadp/catalog/repo.py` | modified | `pending_chain_path`, `save_pending_chain`, `list_pending_chains`. |
| `smadp/autopilot/planners/pair_gate.py` | modified | optional triage re-ordering. |
| `smadp/autopilot/approve.py` | modified | `approve_chain` promotion path. |
| `smadp/autopilot/daily_report.py` | modified | "Capability creep" section. |
| `smadp/api/routes/chains.py` | modified | read-only `GET /chains/{id}/composition`. |
| `smadp/cli.py` | modified | `autopilot compose-chains`, `autopilot approve-chain`, `analyzer triage-train` wiring. |
| `tests/unit/test_chains_composition.py` | new | golden composition per topology. |
| `tests/unit/test_capability_drift.py` | new | drift-diff table tests. |
| `tests/unit/test_triage.py` | new | train/predict round-trip + determinism. |
| `tests/autopilot/test_chain_composer.py` | new | composer driver + candidate emission. |
| `tests/autopilot/test_triage_planner.py` | new | planner re-ordering with triage. |
| `tests/unit/test_schemas_profile_history.py` | new | capability_history schema. |
| `catalog/_meta/triage/` | new dir | model artifacts. |

> **Note on prose vs code:** Tasks 1, 2, 5, 11 carry complete code (the load-bearing/novel pieces). Tasks 3, 4, 6–10, 12–17 give complete failing-test code plus precise prose implementation specs — author the implementation against the REAL API (read the surrounding files first; if a signature differs from what the prose assumes, adapt minimally and preserve the test's behavior contract, documenting the adaptation). NO emoji anywhere (CLAUDE.md hard rule).

---

## Task 1 — Schema: additive capability_history on Profile (1.1 → 1.2)

**Files:** `smadp/schemas/profile.py`, `tests/unit/test_schemas_profile_history.py`

- [ ] Write failing test `tests/unit/test_schemas_profile_history.py`:
```python
from __future__ import annotations

import pytest

from smadp.schemas.profile import CapabilityHistoryEntry, Profile

BASE = {
    "slug": "demo-agent",
    "name": "Demo",
    "vendor": {"type": "company", "handle": "acme"},
    "source_type": "open-source",
    "category": "coding",
    "verification": {
        "status": "verified",
        "verified_at": "2026-01-01T00:00:00Z",
        "method": "manual-authoring",
    },
    "first_seen_at": "2026-01-01T00:00:00Z",
    "last_refreshed_at": "2026-01-01T00:00:00Z",
}


def test_capability_history_defaults_empty_and_validates():
    p = Profile.model_validate(BASE)
    assert p.schema_version == "1.2"
    assert p.capability_history == []


def test_capability_history_entry_roundtrip():
    entry = {
        "version": "v2.0.0",
        "observed_at": "2026-06-01T00:00:00Z",
        "capability_hash": "sha256:" + "a" * 64,
        "diff_summary": "added execute_shell",
    }
    p = Profile.model_validate({**BASE, "capability_history": [entry]})
    assert len(p.capability_history) == 1
    assert isinstance(p.capability_history[0], CapabilityHistoryEntry)
    assert p.capability_history[0].capability_hash.startswith("sha256:")


def test_capability_hash_must_be_sha256():
    bad = {
        "version": "v1",
        "observed_at": "2026-06-01T00:00:00Z",
        "capability_hash": "deadbeef",
        "diff_summary": "x",
    }
    with pytest.raises(ValueError):
        Profile.model_validate({**BASE, "capability_history": [bad]})


def test_pre_1_2_profile_still_validates():
    p = Profile.model_validate({**BASE, "schema_version": "1.1"})
    assert p.capability_history == []
```
- [ ] Run `.venv/bin/python -m pytest tests/unit/test_schemas_profile_history.py -q` → expect `ImportError: cannot import name 'CapabilityHistoryEntry'`.
- [ ] Implement in `smadp/schemas/profile.py`:
  - Add a model above `Profile`:
```python
class CapabilityHistoryEntry(BaseModel):
    """Append-only record of one observed capability snapshot."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=120)
    observed_at: datetime
    capability_hash: str
    diff_summary: str = Field(default="", max_length=600)

    @field_validator("capability_hash")
    @classmethod
    def _validate_hash(cls, v: str) -> str:
        if not EVIDENCE_REF_RE.match(v):
            raise ValueError(f"Invalid capability_hash: {v!r}")
        return v
```
  (`EVIDENCE_REF_RE` is the existing `sha256:[0-9a-f]{64}` pattern in this module — confirm its name; if different, reuse whatever the module already uses for evidence-ref hashes.)
  - Change `schema_version: Literal["1.0", "1.1"] = "1.1"` → `Literal["1.0", "1.1", "1.2"] = "1.2"`.
  - Add field on `Profile`: `capability_history: list[CapabilityHistoryEntry] = Field(default_factory=list)`.
  - Export `CapabilityHistoryEntry` from `smadp/schemas/__init__.py` (add to imports + `__all__`).
- [ ] Run `.venv/bin/python -m pytest tests/unit/test_schemas_profile_history.py tests/unit/test_schemas_profile.py -q` → pass (no regression on existing strict profiles).
- [ ] Commit: `feat(schema): additive capability_history on Profile, bump 1.1->1.2`

## Task 2 — Capability hashing + drift classifier

**Files:** `smadp/analyzer/capability_drift.py`, `tests/unit/test_capability_drift.py`

A capability vector is a canonical ordered representation of a profile's safety-relevant surface. Egress is ordinal (`none < allowlisted < vendor-only < broad`); booleans `False < True`; oauth scopes / secrets / data classes are sets (growth = expansion).

- [ ] Write failing test `tests/unit/test_capability_drift.py`:
```python
from __future__ import annotations

from smadp.analyzer.capability_drift import (
    EGRESS_ORDER,
    capability_hash,
    capability_vector,
    diff_capabilities,
)
from smadp.schemas.profile import Profile

BASE = {
    "slug": "a", "name": "A",
    "vendor": {"type": "company", "handle": "x"},
    "source_type": "open-source", "category": "coding",
    "verification": {"status": "verified", "verified_at": "2026-01-01T00:00:00Z",
                     "method": "manual-authoring"},
    "first_seen_at": "2026-01-01T00:00:00Z", "last_refreshed_at": "2026-01-01T00:00:00Z",
}


def _profile(**caps):
    return Profile.model_validate({**BASE, "capabilities": caps})


def test_egress_order_is_monotonic():
    assert EGRESS_ORDER["none"] < EGRESS_ORDER["allowlisted"]
    assert EGRESS_ORDER["allowlisted"] < EGRESS_ORDER["vendor-only"]
    assert EGRESS_ORDER["vendor-only"] < EGRESS_ORDER["broad"]


def test_hash_is_stable_and_order_independent():
    p1 = _profile(execute_shell=True, read_filesystem=True)
    p2 = _profile(read_filesystem=True, execute_shell=True)
    assert capability_hash(p1) == capability_hash(p2)
    assert capability_hash(p1).startswith("sha256:")


def test_new_execute_shell_is_expansion():
    old = _profile(execute_shell=False)
    new = _profile(execute_shell=True)
    d = diff_capabilities(old, new)
    assert d.has_expansion
    assert any("execute_shell" in c.field for c in d.expansions)
    assert d.expansions[0].direction == "expansion"


def test_broader_egress_is_expansion():
    old = _profile(network_egress="allowlisted")
    new = _profile(network_egress="broad")
    d = diff_capabilities(old, new)
    assert d.has_expansion
    assert any("network_egress" in c.field for c in d.expansions)


def test_narrower_egress_is_contraction_not_expansion():
    old = _profile(network_egress="broad")
    new = _profile(network_egress="allowlisted")
    d = diff_capabilities(old, new)
    assert not d.has_expansion
    assert any(c.direction == "contraction" for c in d.contractions)


def test_new_oauth_scope_is_expansion():
    old = Profile.model_validate({**BASE})
    new = Profile.model_validate(
        {**BASE, "permissions_requested": {"oauth_scopes": ["repo:write"]}}
    )
    d = diff_capabilities(old, new)
    assert d.has_expansion
    assert any("oauth_scopes" in c.field for c in d.expansions)


def test_identical_profiles_no_drift():
    p = _profile(execute_shell=True)
    d = diff_capabilities(p, p)
    assert not d.has_expansion
    assert d.summary == "no capability change"
```
- [ ] Run `.venv/bin/python -m pytest tests/unit/test_capability_drift.py -q` → expect `ModuleNotFoundError`.
- [ ] Implement `smadp/analyzer/capability_drift.py`:
```python
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
            field=f, direction="expansion" if nv else "contraction",
            detail=f"{ov} -> {nv}",
        )
        (exp if nv else con).append(change)

    oe, ne = EGRESS_ORDER[o.network_egress], EGRESS_ORDER[n.network_egress]
    if ne > oe:
        exp.append(CapabilityChange("network_egress", "expansion",
                                    f"{o.network_egress} -> {n.network_egress}"))
    elif ne < oe:
        con.append(CapabilityChange("network_egress", "contraction",
                                    f"{o.network_egress} -> {n.network_egress}"))

    pairs = [
        (old.permissions_requested.oauth_scopes, new.permissions_requested.oauth_scopes,
         "permissions_requested.oauth_scopes"),
        (old.permissions_requested.secrets_handled, new.permissions_requested.secrets_handled,
         "permissions_requested.secrets_handled"),
        (old.permissions_requested.elevated_privileges,
         new.permissions_requested.elevated_privileges,
         "permissions_requested.elevated_privileges"),
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
```
  (Confirm `smadp.utils.hashing.sha256_canonical_json` exists; if the helper has a different name/module, use the project's canonical-JSON sha256 helper. Confirm `Capabilities` field names match `_BOOL_FIELDS` against the real `profile.py`.)
- [ ] Run `.venv/bin/python -m pytest tests/unit/test_capability_drift.py -q` → pass.
- [ ] Commit: `feat(analyzer): deterministic capability-vector diff + hash`

## Task 3 — stale_reason on Verdict + capability_drift chronicle event

**Files:** `smadp/schemas/verdict.py`, `smadp/schemas/chronicle.py`, `tests/unit/test_schemas_verdict.py` (extend), `tests/unit/test_schemas_chronicle.py` (extend)

- [ ] Add failing test cases to `tests/unit/test_schemas_verdict.py` (reuse the module's existing valid-verdict builder; if none, copy the smallest `catalog/verdicts/*.json` trimmed to required fields): a verdict's `stale_reason` defaults `None`, accepts `"capability_drift"`, and rejects unknown values.
- [ ] Add a failing test to `tests/unit/test_schemas_chronicle.py`: `ChronicleEvent(... event="capability_drift" ...)` is accepted.
- [ ] Run both files → expect failures (`extra fields`/invalid literal).
- [ ] Implement: `smadp/schemas/verdict.py` add `StaleReason = Literal["capability_drift"]` and field `stale_reason: StaleReason | None = None` on `Verdict`. `smadp/schemas/chronicle.py` append `"capability_drift"` to `ChronicleEventType`.
- [ ] Run both files → pass.
- [ ] Commit: `feat(schema): optional Verdict.stale_reason + capability_drift event`

## Task 4 — Chain schema provenance fields (1.0 → 1.1)

**Files:** `smadp/schemas/chain.py`, `tests/unit/test_chain_schema.py` (extend)

- [ ] Add failing tests (reuse the module's valid-chain builder, or load `catalog/chains/c_code-review-loop.json`): a `1.1` chain accepts `composition_method`, `composed_from`, `stale_reason`; an existing `1.0` chain (no new fields) still validates with `composed_from == []`, `composition_method is None`.
- [ ] Run → expect failure (extra fields forbidden / missing on model).
- [ ] Implement in `smadp/schemas/chain.py`: `schema_version: Literal["1.0", "1.1"] = "1.1"`; add `composition_method: str | None = Field(default=None, max_length=60)`, `composed_from: list[str] = Field(default_factory=list)`, `stale_reason: Literal["capability_drift"] | None = None`.
- [ ] Run `tests/unit/test_chain_schema.py` plus any chain-fixture/repo tests → pass (existing `1.0` fixtures unaffected; `save_chain` already uses `exclude_none=True`).
- [ ] Commit: `feat(schema): chain composition provenance fields, bump 1.0->1.1`

## Task 5 — Deterministic chain composition core

**Files:** `smadp/analyzer/chains.py`, `tests/unit/test_chains_composition.py`

Rules (documented in module docstring): link risk = adjacent pair's pairwise sub-severities; **D** compounds along path length (+1 band per hop beyond 2 nodes, capped `critical`); **B** = max over links sharing a carried data class (fallback: plain max); **A/C/E** = plain max; loops add one extra D band; confidence = `min(present link confidences) * (1 - 0.15 * missing_links)`, clamped.

- [ ] Write failing test `tests/unit/test_chains_composition.py`:
```python
from __future__ import annotations

from smadp.analyzer.chains import (
    SEVERITY_BANDS,
    LinkInput,
    bump_band,
    compose_chain,
)


def _link(a, b, *, D="low", B="none", A="none", C="none", E="none",
          conf=0.9, carries=None):
    return LinkInput(
        from_slug=a, to_slug=b,
        severities={"A_prompt_injection": A, "B_data_leakage": B,
                    "C_capability_conflict": C, "D_cascading_error": D,
                    "E_compliance": E},
        confidence=conf, present=True, carries=carries or [],
    )


def test_band_ordering_and_bump():
    assert SEVERITY_BANDS.index("none") < SEVERITY_BANDS.index("critical")
    assert bump_band("low", 1) == "medium"
    assert bump_band("high", 5) == "critical"  # capped
    assert bump_band("none", 0) == "none"


def test_linear_three_node_compounds_D_one_band():
    links = [_link("a", "b", D="low"), _link("b", "c", D="medium")]
    out = compose_chain(topology="linear", links=links, node_count=3)
    assert out.severities["D_cascading_error"] == "high"


def test_loop_amplifies_D_extra_band():
    links = [_link("a", "b", D="low"), _link("b", "a", D="low")]
    out = compose_chain(topology="loop", links=links, node_count=2)
    assert out.severities["D_cascading_error"] == "medium"


def test_B_takes_max_over_links_sharing_data_class():
    links = [
        _link("a", "b", B="low", carries=["pii"]),
        _link("b", "c", B="high", carries=["pii"]),
        _link("c", "d", B="critical", carries=["telemetry"]),
    ]
    out = compose_chain(topology="linear", links=links, node_count=4)
    assert out.severities["B_data_leakage"] == "critical"


def test_confidence_is_min_penalized_per_missing_link():
    present = _link("a", "b", conf=0.8)
    missing = LinkInput(from_slug="b", to_slug="c", severities={
        "A_prompt_injection": "none", "B_data_leakage": "none",
        "C_capability_conflict": "none", "D_cascading_error": "none",
        "E_compliance": "none"}, confidence=0.0, present=False, carries=[])
    out = compose_chain(topology="linear", links=[present, missing], node_count=3)
    assert abs(out.confidence - 0.8 * 0.85) < 1e-9
    assert out.missing_links == 1


def test_composite_uses_existing_weights_deterministically():
    links = [_link("a", "b", B="high", C="medium")]
    out = compose_chain(topology="linear", links=links, node_count=2)
    assert 0.0 <= out.composite <= 1.0
    assert abs(out.composite - 0.365) < 1e-9
```
- [ ] Run `.venv/bin/python -m pytest tests/unit/test_chains_composition.py -q` → expect `ModuleNotFoundError`.
- [ ] Implement `smadp/analyzer/chains.py`:
```python
"""Deterministic N-agent chain composition over pairwise verdicts.

The LLM judge never runs here. Given each adjacent link's published pairwise
sub-verdict severities plus the chain topology, this module computes the
composed per-risk severities, composite score, and confidence with fixed rules
(see plan). All numbers are produced here in Python, honoring the
deterministic-composite contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from smadp.analyzer.scoring import composite_score as _pairwise_composite
from smadp.schemas.verdict import SubVerdict, SubVerdicts

SEVERITY_BANDS: tuple[str, ...] = ("none", "low", "medium", "high", "critical")
_MISSING_LINK_PENALTY = 0.15


def bump_band(band: str, by: int) -> str:
    idx = min(SEVERITY_BANDS.index(band) + max(0, by), len(SEVERITY_BANDS) - 1)
    return SEVERITY_BANDS[idx]


def _max_band(bands: list[str]) -> str:
    if not bands:
        return "none"
    return max(bands, key=SEVERITY_BANDS.index)


@dataclass(frozen=True)
class LinkInput:
    from_slug: str
    to_slug: str
    severities: dict[str, str]  # risk key -> band
    confidence: float
    present: bool
    carries: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ComposedChain:
    severities: dict[str, str]
    composite: float
    confidence: float
    missing_links: int
    max_severity: str


def _compose_B(links: list[LinkInput]) -> str:
    classed = [link for link in links if link.carries]
    if not classed:
        return _max_band([link.severities["B_data_leakage"] for link in links])
    by_class: dict[str, list[str]] = {}
    for link in classed:
        for dc in link.carries:
            by_class.setdefault(dc, []).append(link.severities["B_data_leakage"])
    untagged = [link.severities["B_data_leakage"] for link in links if not link.carries]
    group_maxes = [_max_band(v) for v in by_class.values()] + (
        [_max_band(untagged)] if untagged else [])
    return _max_band(group_maxes)


def compose_chain(*, topology: str, links: list[LinkInput], node_count: int) -> ComposedChain:
    present = [link for link in links if link.present]
    missing = sum(1 for link in links if not link.present)

    sev: dict[str, str] = {}
    for key in ("A_prompt_injection", "C_capability_conflict", "E_compliance"):
        sev[key] = _max_band([link.severities[key] for link in present]) if present else "none"

    sev["B_data_leakage"] = _compose_B(present) if present else "none"

    base_d = _max_band([link.severities["D_cascading_error"] for link in present]) if present else "none"
    hops_beyond_two = max(0, node_count - 2)
    loop_bonus = 1 if topology == "loop" else 0
    sev["D_cascading_error"] = bump_band(base_d, hops_beyond_two + loop_bonus)

    confidences = [link.confidence for link in present]
    base_conf = min(confidences) if confidences else 0.0
    conf = max(0.0, min(1.0, base_conf * (1.0 - _MISSING_LINK_PENALTY * missing)))

    composite = _composite_from_bands(sev)
    return ComposedChain(
        severities=sev,
        composite=composite,
        confidence=round(conf, 4),
        missing_links=missing,
        max_severity=_max_band(list(sev.values())),
    )


def _composite_from_bands(sev: dict[str, str]) -> float:
    """Reuse the canonical pairwise weights via a synthetic SubVerdicts."""
    def _sv(band: str) -> SubVerdict:
        return SubVerdict(
            severity=band,  # type: ignore[arg-type]
            rationale="composed",
            citations=[{"quote": "composed"}],  # type: ignore[list-item]
        )

    sub = SubVerdicts(
        A_prompt_injection=_sv(sev["A_prompt_injection"]),
        B_data_leakage=_sv(sev["B_data_leakage"]),
        C_capability_conflict=_sv(sev["C_capability_conflict"]),
        D_cascading_error=_sv(sev["D_cascading_error"]),
        E_compliance=_sv(sev["E_compliance"]),
    )
    return _pairwise_composite(sub)
```
  (`SubVerdict` requires a non-empty `citations` list; confirm the `Citation` shape and adjust the synthetic citation if validation differs. Confirm `composite_score`'s signature accepts a `SubVerdicts`.)
- [ ] Run `.venv/bin/python -m pytest tests/unit/test_chains_composition.py -q` → pass.
- [ ] Commit: `feat(analyzer): deterministic chain composition core`

## Task 6 — Pending-chain repo paths

**Files:** `smadp/catalog/repo.py`, `tests/unit/test_chain_repo.py` (extend)

- [ ] Add a failing test: save a minimal valid `Chain` (built from the seed loop fixture, `chain_id="c_pending-demo"`) via `repo.save_pending_chain(chain)`; assert the path is under `pending/chains/` and `repo.list_pending_chains()` includes it.
- [ ] Run → expect `AttributeError: save_pending_chain`.
- [ ] Implement in `smadp/catalog/repo.py` (chains section): `pending_chains_dir()`, `pending_chain_path(chain_id)`, `save_pending_chain(chain)` (atomic JSON write, `model_dump(mode="json", by_alias=True, exclude_none=True)`), `list_pending_chains()` (sorted glob, skip invalid), `load_pending_chain(chain_id)` (NotFound if missing). Match the file's existing atomic-write/read helpers.
- [ ] Run `tests/unit/test_chain_repo.py` → pass.
- [ ] Commit: `feat(catalog): pending-chain repo paths (pending/chains/)`

## Task 7 — Autopilot config: kill switches + thresholds

**Files:** `smadp/autopilot/config.py`, `config/autopilot.yaml`, `tests/autopilot/test_autopilot_config.py`

- [ ] Write a failing test: defaults when keys absent (`chain_composition_enabled True`, `chain_publish_confidence_threshold 0.6`, `chain_judge_batch_max 10`, `triage_enabled True`); reading nested `chain_composition:`/`triage:` mappings sets each value.
- [ ] Run → expect `AttributeError`.
- [ ] Implement: extend `AutopilotConfig` with `chain_composition_enabled: bool = True`, `chain_publish_confidence_threshold: float = 0.6`, `chain_judge_batch_max: int = 10`, `triage_enabled: bool = True`; parse nested `chain_composition`/`triage` mappings with `.get` defaults in `load_autopilot_config`. Append the `chain_composition:` and `triage:` blocks to `config/autopilot.yaml` (with comments documenting the kill switches).
- [ ] Run config test → pass.
- [ ] Commit: `feat(autopilot): chain-composition + triage config kill switches`

## Task 8 — Chain composer driver (S2.1 integration)

**Files:** `smadp/autopilot/chain_composer.py`, `tests/autopilot/test_chain_composer.py`

The driver reads an authored chain (topology + participants + edges), resolves each edge to a published pairwise `Verdict` (`present=False` when missing), builds `LinkInput`s (`carries` from the edge), calls `compose_chain`, and writes a composed `Chain` candidate into `pending/chains/` (Python overrides every number: `composite_score`, `confidence`, `max_severity`; provenance `composed_from`, `composition_method="deterministic-v1"`). Confidence below threshold ⇒ `needs_judge`. Idempotent; honors the kill switch; chronicles `chain.created`.

- [ ] Write a failing test: seed the two pairwise verdicts an authored chain's edges reference (copy the smallest `catalog/verdicts/*.json`, rewrite `pair`/`participants`/`verdict_id`/`confidence`/severities, save via `CatalogRepo.save_verdict`); `compose_authored_chains(...)` writes ≥1 pending candidate with `composition_method == "deterministic-v1"`, non-empty `composed_from`, `0 <= confidence <= 1`; kill switch ⇒ `disabled True`, `composed 0`; low confidence ⇒ `needs_judge >= 1`.
- [ ] Run → expect `ModuleNotFoundError`.
- [ ] Implement `smadp/autopilot/chain_composer.py` with a `ComposeSummary(disabled, composed, needs_judge)` and `compose_authored_chains(*, repo_root, config, autopilot_cfg)`: early-return disabled when `not chain_composition_enabled`; for each `repo.list_chains()` with edges, resolve links via `repo.load_verdict(*sort_pair(...))`, compose, `repo.save_pending_chain(candidate)`, count `needs_judge` when `confidence < threshold`, chronicle each. Do NOT mutate the authored `sub_verdicts` severities (the operator/judge step reconciles narratives; the numbers carry the deterministic result). Match real `CatalogRepo`/`Chronicle`/`sort_pair`/`utcnow` APIs.
- [ ] Run `tests/autopilot/test_chain_composer.py` → pass.
- [ ] Commit: `feat(autopilot): chain composer driver -> pending/chains`

## Task 9 — LLM confirmation batch for low-confidence chains (symbols only)

**Files:** `smadp/autopilot/chain_composer.py` (extend), `tests/autopilot/test_chain_composer.py` (extend)

The judge may only return narrative + symbolic severities; Python keeps every number. Batch bounded by `chain_judge_batch_max`. Reuse the existing `LLMClient` (mock in tests, modeled on existing judge-mock patterns — grep `tests/` for how the pairwise judge is faked).

- [ ] Add a failing test: a mocked judge returns symbolic severities for a flagged chain; assert composite stays Python-computed and within `[0,1]`, judge called at most `judge_batch_max` times, and no judge calls when `needs_judge == 0` or the kill switch is off.
- [ ] Run → expect failure.
- [ ] Implement `confirm_low_confidence_chains(...)`: select pending candidates below threshold (worst-first), cap at `judge_batch_max`, obtain symbolic per-risk bands + headline from the judge, rebuild `LinkInput`s from those bands, re-run `_composite_from_bands`, write the updated candidate back, chronicle `judged=True`. Provide async + sync wrappers mirroring `refresh/evaluator.py`.
- [ ] Run extended test → pass.
- [ ] Commit: `feat(autopilot): bounded LLM confirmation batch for uncertain chains`

## Task 10 — Operator approve-chain promotion

**Files:** `smadp/autopilot/approve.py`, `tests/autopilot/test_approve_chain.py`

- [ ] Write a failing test: seed `pending/chains/c_x.json`; `approve_chain(repo_root, "c_x")` moves it to `catalog/chains/c_x.json`, removes the pending file, and writes a `chain.created` (by=`operator`) chronicle entry; a missing id raises `ApproveError`.
- [ ] Run → expect `AttributeError`/`ImportError`.
- [ ] Implement `approve_chain(*, repo_root, chain_id)` mirroring the existing pairwise `approve`: load the pending chain, `repo.save_chain(...)`, delete the pending file, chronicle by `operator`. Reuse the existing `ApproveError`.
- [ ] Run → pass.
- [ ] Commit: `feat(autopilot): operator approve-chain promotion (pending -> chains)`

## Task 11 — Triage featurization + artifact format + predict (S2.3 core)

**Files:** `smadp/analyzer/triage.py`, `tests/unit/test_triage.py`

Pure-Python logistic regression. Bands `("safe","low","medium","high")` thresholded at composite `0.2/0.4/0.6`. Feature vector for the slug-sorted pair: 8 boolean caps per side, ordinal egress scaled `/3`, set-size buckets, a category-pair hash one-hot among ~8 buckets. One-vs-rest logistic per band; predicted band = argmax; uncertainty = `1 - (top_prob - second_prob)`. Artifact JSON carries `{version, trained_at, training_set_hash, feature_names, classes, weights, bias, feature_count}`.

- [ ] Write failing test `tests/unit/test_triage.py`:
```python
from __future__ import annotations

from smadp.analyzer.triage import (
    FEATURE_NAMES,
    TriageModel,
    band_for_composite,
    featurize,
    train,
)
# fixtures profile_a, profile_b, tiny_corpus, all_safe_corpus defined in this module
# (build Profiles from a BASE dict like Task 1; corpus = list[(Profile, Profile, float)]).


def test_band_thresholds():
    assert band_for_composite(0.0) == "safe"
    assert band_for_composite(0.3) == "low"
    assert band_for_composite(0.5) == "medium"
    assert band_for_composite(0.9) == "high"


def test_featurize_is_deterministic_and_order_independent(profile_a, profile_b):
    f1 = featurize(profile_a, profile_b)
    f2 = featurize(profile_b, profile_a)
    assert f1 == f2
    assert len(f1) == len(FEATURE_NAMES)


def test_train_predict_roundtrip_is_deterministic(tiny_corpus):
    m1 = train(tiny_corpus, seed=1234)
    m2 = train(tiny_corpus, seed=1234)
    assert m1.weights == m2.weights
    pa, pb, _ = tiny_corpus[0]
    assert m1.predict(pa, pb).band == m2.predict(pa, pb).band
    assert 0.0 <= m1.predict(pa, pb).uncertainty <= 1.0


def test_safe_pairs_predicted_safe(all_safe_corpus):
    m = train(all_safe_corpus, seed=7)
    pa, pb, _ = all_safe_corpus[0]
    assert m.predict(pa, pb).band == "safe"


def test_artifact_roundtrip(tiny_corpus, tmp_path):
    m = train(tiny_corpus, seed=1)
    path = tmp_path / "v1.json"
    m.save(path, training_set_hash="sha256:" + "0" * 64)
    loaded = TriageModel.load(path)
    pa, pb, _ = tiny_corpus[0]
    assert loaded.predict(pa, pb).band == m.predict(pa, pb).band
    assert loaded.training_set_hash.startswith("sha256:")
```
  (Author the fixtures in the test module.)
- [ ] Run → expect `ModuleNotFoundError`.
- [ ] Implement `smadp/analyzer/triage.py` (stdlib `math` only): `BANDS`, `band_for_composite`, `FEATURE_NAMES`, `featurize(a,b)` (slug-sorted; egress via `EGRESS_ORDER` from `capability_drift` scaled `/3`; counts log-bucketed; category pair hashed via the project's text-sha256 helper modulo ~8 → one-hot), `train(corpus, *, seed, epochs=300, lr=0.1, l2=0.001)` (deterministic `random.Random(seed)` init + full-batch GD per OvR band), `TriageModel` (`weights`, `bias`, `predict` returning `Prediction(band, probabilities, uncertainty)`, `save`/`load`). Degenerate guard: empty/single-class corpus ⇒ majority band, `uncertainty=1.0`.
- [ ] Run `tests/unit/test_triage.py` → pass.
- [ ] Commit: `feat(analyzer): dependency-light logistic triage model`

## Task 12 — Triage training script + artifact dir

**Files:** `scripts/train_triage.py`, `catalog/_meta/triage/.gitkeep`, `tests/unit/test_train_triage_script.py`

- [ ] Write a failing test: `scripts.train_triage.build_corpus(...)` returns a non-empty `(Profile, Profile, float)` list from published verdicts whose both participants have profiles; `main(["--out", ..., "--catalog", ...])` writes a loadable artifact carrying a `training_set_hash`.
- [ ] Run → expect failure.
- [ ] Implement `scripts/train_triage.py`: `build_corpus` iterates `CatalogRepo.list_verdicts()` (2-participant), loads both profiles (skip missing), yields `(pa, pb, composite_score)`; `training_set_hash = sha256_canonical_json(sorted (participants, composite) tuples)`; argparse `--catalog/--out/--seed/--version`; default `--out = catalog/_meta/triage/<version>.json`. Add `catalog/_meta/triage/.gitkeep`. Ensure `scripts/` is importable (add `scripts/__init__.py` if needed).
- [ ] Run → pass.
- [ ] Commit: `feat(scripts): triage training script -> versioned artifact`

## Task 13 — Triage-aware planner re-ordering (S2.3 wiring)

**Files:** `smadp/autopilot/planners/pair_gate.py`, `tests/autopilot/test_triage_planner.py`

Inject an optional `TriageModel` into `PairGatePlanner`. When present, multiply each pair's `priority` by `urgency = band_weight + uncertainty` (`band_weight = {safe:0.0, low:0.3, medium:0.7, high:1.0}`). High-confidence-safe pairs sink; uncertain/risky float up. Triage NEVER writes a verdict and never changes eligibility — only order.

- [ ] Write a failing test: with a model that rates one pair safe+confident and another risky, the risky pair ranks above the safe pair; without a model, baseline ordering is preserved and nothing crashes.
- [ ] Run → expect failure (`unexpected keyword 'triage'`).
- [ ] Implement: add `triage: TriageModel | None = None` to `PairGatePlanner`; in `plan`, after the base `priority`, if `self.triage` is set, build `Profile`s for each pair, compute `urgency`, scale `priority`. Mirror into `TopNPlanner` if the autopilot uses it.
- [ ] Run → pass.
- [ ] Commit: `feat(autopilot): triage-aware pair prioritization (order only)`

## Task 14 — Capability-drift refresh hook (S2.2 integration)

**Files:** `smadp/autopilot/drift.py`, `tests/autopilot/test_drift_apply.py`

On re-profile: diff the new profile against the on-disk one; if `capability_hash` unchanged ⇒ no-op; else append a `CapabilityHistoryEntry` and save. On expansion: chronicle `capability_drift` (slug + expansions) and set `stale_reason="capability_drift"` on every published verdict touching the slug (surfaced, never re-scored).

- [ ] Write a failing test: seed profile `x` without `execute_shell` + a verdict touching `x`; `apply_capability_drift(config=..., new_profile=x_with_shell)` returns `expanded True`, the verdict gains `stale_reason == "capability_drift"`, and `x` gains `capability_history`; an unchanged profile is a no-op.
- [ ] Run → expect failure.
- [ ] Implement `smadp/autopilot/drift.py` `apply_capability_drift(*, config, new_profile) -> DriftSummary`: load on-disk (old); `diff_capabilities(old, new)`; `capability_hash` idempotency guard; append history entry + `repo.save_profile`; on expansion, chronicle `capability_drift` and stale every `repo.list_verdicts(slug=...)`. Version string = upstream version if present else `last_refreshed_at` date.
- [ ] Run → pass.
- [ ] Commit: `feat(autopilot): capability-drift refresh hook (stale flags + chronicle)`

## Task 15 — Daily report: Capability-creep section

**Files:** `smadp/autopilot/daily_report.py`, `tests/autopilot/test_daily_report_drift.py`

- [ ] Write a failing test: seed today's chronicle with a `capability_drift` event; `render_report(...)` output contains a `## Capability creep` heading listing the slug + expansion; the section is omitted with no drift events.
- [ ] Run → expect failure (section absent).
- [ ] Implement: after the severity section, filter today's chronicle for `event == "capability_drift"`; if any, emit a `## Capability creep` table (Agent | Expansion) pulling `slug` + `details` from each event.
- [ ] Run → pass; run full `tests/autopilot/` for no regressions.
- [ ] Commit: `feat(report): capability-creep section in daily report`

## Task 16 — Read-only chain composition API + CLI wiring

**Files:** `smadp/api/routes/chains.py`, `smadp/cli.py`, `tests/api/test_chains_composition_route.py`, `tests/cli/test_autopilot_s2_cli.py`

- [ ] Write a failing API test: `GET /api/chains/{id}/composition` for a seeded authored chain returns `{composite_score, confidence, max_severity, severities, composed_from}` computed on the fly (no token, read-only); 404 for unknown id.
- [ ] Write a failing CLI test: `smadp autopilot compose-chains` runs the composer; `smadp autopilot approve-chain <id>` promotes; `smadp analyzer triage-train --out ...` produces an artifact. Use `CliRunner` against the tmp-catalog env pattern.
- [ ] Run → expect failures.
- [ ] Implement: add `GET /{chain_id}/composition` to `chains.py` (factor the edge-resolution helper out of `chain_composer` or duplicate minimally; no write/token); add `compose-chains` and `approve-chain` under the `autopilot` CLI group, and `triage-train` under a new/extended `analyzer` group delegating to `scripts.train_triage.main`.
- [ ] Run both test files → pass.
- [ ] Commit: `feat(api,cli): chain composition endpoint + S2 autopilot commands`

## Task 17 — Full-suite green + lint/type gate

**Files:** none (verification)

- [ ] `.venv/bin/python -m pytest -q` → all pass.
- [ ] `.venv/bin/ruff check smadp scripts tests` and `.venv/bin/ruff format --check smadp scripts tests` → clean.
- [ ] `.venv/bin/mypy smadp` → no new errors in the S2 modules. Add precise types; do not widen the mypy override list for new code.
- [ ] Confirm kill switches: `chain_composition.enabled: false` + `triage.enabled: false` ⇒ `compose-chains` reports disabled and the planner falls back to composite-product ordering.
- [ ] Commit: `test(s2): full suite green; lint+type clean`

---

## Self-Review — requirement → task mapping

| Spec requirement | Tasks |
|---|---|
| **S2.1** deterministic composition for linear/star/loop | T5 (core), T8 (driver over authored chains) |
| S2.1 link risk = adjacent pairwise verdict | T5 `LinkInput`, T8 `_link_for_edge` |
| S2.1 D compounds along path length; loops amplify D one band | T5 (`hops_beyond_two` + `loop_bonus`), tested |
| S2.1 B = max over links touching same data class | T5 `_compose_B`, tested |
| S2.1 confidence = min over constituents, penalized per missing link | T5, tested |
| S2.1 uncertain chains → LLM judge, bounded batch, operator pending queue | T7 threshold/batch, T8 flagging, T9 bounded judge (symbols only) |
| S2.1 output → pending → operator gate → chains | T6 pending paths, T8 writes pending, T10 approve-chain |
| **S2.2** Profile `capability_history[]` append-only, schema 1.1→1.2 additive | T1 |
| S2.2 capability vector hash + diff summary | T2 |
| S2.2 expansion → `capability_drift` chronicle + flag page | T3 (event), T14 (hook) |
| S2.2 affected verdicts stale via `stale_reason`, never re-scored | T3 (field), T14 (sets stale) |
| S2.2 daily report capability-creep section | T15 |
| **S2.3** dependency-light classifier, training script + versioned artifact w/ training-set hash | T11 (model), T12 (script) |
| S2.3 maps capability vectors + category pair → band + uncertainty | T11 `featurize` + `predict` |
| S2.3 prioritization only; deprioritize safe, front-load risky; never publishes/skips judge | T13 (order only) |
| **Invariants:** LLM only symbols; Python all ranking/publishing numbers | T5/T8 (Python composite), T9 (judge symbols only) |
| Nothing bypasses operator gate | T6/T8/T10 |
| Every new automated path has a kill switch | T7, verified T17 |
| Testing strategy: golden per topology; drift-diff; triage round-trip + determinism | T5, T2/T14, T11 |
