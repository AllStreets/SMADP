# S3 — Trust Infrastructure for SMADP (MCP Recording Proxy + Signed Publishes + Federated Submissions)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Pillar S3 of the Proving Ground: (S3.1) a stdio MCP recording proxy that observes a closed-source agent's real runtime behavior, redacts secrets with the existing rules, content-addresses the recording as evidence, synthesizes a *runtime behavior profile*, and lands it on a **new five-rung evidence ladder** with `behavior-observed` inserted between `docs-only` and `profile-verified`; (S3.2) wire the existing sigstore/BYOK passport signing into the `pending approve` publish path so published verdicts carry a verifiable signature, and add `POST /api/submit/profile` accepting third-party profiles signed by a registered key into the same `_unverified/` staging + caps + lint + operator-promotion path that ONEXUS-Agents sync uses.

**Architecture:** The riskiest change is inserting a rung into the evidence ladder, which is **duplicated** in ~12 sites across schemas, promote logic, pending/CLI/API/site, and the daily report. Task 1 establishes a single canonical ladder module (`smadp/schemas/evidence_level.py`) with exhaustive ordering tests, updates every literal/enum/ordering site to five rungs, and re-points the duplicated tuples/dicts at the canonical constant where mechanical. Tasks 2–4 build the proxy package (`smadp/proxy/`) as a pure stdio JSON-RPC passthrough (no `mcp` dependency — none is available) plus a recording layer reusing `smadp.sandbox.policy` redaction, plus behavior-profile synthesis writing `behavior-observed` evidence + profile stubs into `_unverified/`, all operator-gated. Tasks 5–6 wire BYOK verdict signing at `pending approve` (sidecar `.sig.json` + canonical sha over the verdict) and surface it on the site. Tasks 7–8 add the federated submit endpoint with a registered-key store and operator-token gate, landing signed profiles in `_unverified/`. Every new automated path has a file-based kill switch consistent with `AGENTS_SYNC_DISABLED`. Nothing writes to `catalog/verdicts/` or `catalog/chains/` except the operator gate.

**Tech Stack:** Python 3.11+, Pydantic v2, Click CLI, FastAPI, `cryptography` Ed25519 (already a dep), structlog, pytest (`.venv/bin/python -m pytest`), Astro/TypeScript site. No new runtime dependencies — the MCP proxy is a minimal stdio JSON-RPC passthrough using stdlib `asyncio`/`subprocess`/`json`.

## Spec deviations

1. **No `mcp` package available.** `pyproject.toml` carries no `mcp`/JSON-RPC library. As the spec's own NOTE anticipates, S3.1 implements a **minimal stdio JSON-RPC line-delimited passthrough** (`smadp/proxy/jsonrpc.py`) rather than depending on an MCP SDK. It frames messages by the MCP stdio convention (one JSON object per line); we support the newline-delimited stdio transport, the common case for catalog agents. Documented in Task 2.

2. **Redaction rules are secret-*detection* rules, not a redaction transformer.** The "existing redaction rules" the spec references are `smadp/sandbox/policy.looks_like_real_secret` / `_REAL_SECRET_PATTERNS`. There is no existing function that *rewrites* a payload. We reuse `_REAL_SECRET_PATTERNS` as the single source of truth and add a thin `redact_secrets()` transformer in the proxy package that substitutes matches with `***REDACTED***`, so the patterns stay centralized in `policy.py`. Documented in Task 3.

3. **Verdict signing is a sidecar, not an in-schema field.** Adding a signature *field* to the `Verdict` schema would change the canonical bytes the passport signs (circularity). Instead, `pending approve` writes a **detached signature sidecar** `catalog/verdicts/<key>.sig.json` (signature over the verdict's canonical sha), leaving the verdict JSON's canonical bytes untouched and the deterministic-composite contract preserved. The site reads the sidecar. Documented in Task 5.

4. **`pending approve` is `smadp pending approve` and `smadp autopilot approve`.** Both move pending→verdicts. We add signing to the shared `approve_one` in `smadp/autopilot/pending.py` so both CLI entrypoints sign identically; `smadp/autopilot/approve.py` is re-pointed at `approve_one`. Documented in Task 5.

5. **BYOK key is keyed by `workspace_id`.** `tenancy.keys.load_signing_key` requires a `workspace_id`. The publish signer uses a fixed operator workspace id (`"_smadp_publisher"`), provisioned by a new `smadp pending init-signing-key` command. If no key exists, signing is skipped (verdict still publishes, unsigned) with a logged warning — signing is additive evidence, never a publish blocker. Documented in Task 5.

## File Structure

| Path | New/Modified | Purpose |
|---|---|---|
| `smadp/schemas/evidence_level.py` | new | Canonical five-rung ladder: tuple + rank() + EvidenceLevel literal alias |
| `smadp/schemas/verdict.py` | mod | Import `EvidenceLevel` from canonical module |
| `smadp/schemas/profile.py` | mod | `evidence_level` literal → five rungs |
| `smadp/schemas/chain.py` | mod | `EvidenceLevel` literal → five rungs |
| `catalog/_meta/schema/1.0/verdict.schema.json` | mod | enum → five rungs |
| `catalog/_meta/schema/1.0/chain.schema.json` | mod | enum → five rungs |
| `smadp/sandbox/promote.py` | mod | `_EVIDENCE_LADDER` → canonical tuple |
| `smadp/autopilot/pending.py` | mod | `tier_rank` → canonical rank; add signing in `approve_one` |
| `smadp/autopilot/scaffolders/mcp_adapter.py` | mod | trust-floor dict gains `behavior-observed`; `_ENRICHED_TIERS` |
| `smadp/autopilot/daily_report.py` | mod | tier ordering tuple gains `behavior-observed` |
| `smadp/autopilot/bootstrap.py` | mod | `_ENRICHED_TIERS` gains `behavior-observed` |
| `smadp/autopilot/planners/pair_gate.py` | mod | `_ENRICHED_TIERS` gains `behavior-observed` |
| `smadp/analyzer/judge.py` | mod | valid-level set gains `behavior-observed` |
| `smadp/llm/prompts/pairwise_judge.py` | mod | json-schema enum gains `behavior-observed` |
| `smadp/cli.py` | mod | `_EVIDENCE_COLORS` gains `behavior-observed`; add `proxy` + `pending init-signing-key` |
| `site/src/data/types.ts` | mod | `EvidenceLevel` union gains `behavior-observed` |
| `site/src/data/catalog.ts` | mod | `evidenceLevelColor` gains `behavior-observed` |
| `site/src/components/EvidenceLevelBadge.astro` | mod | labels record gains `behavior-observed` |
| `smadp/proxy/__init__.py` | new | package marker |
| `smadp/proxy/jsonrpc.py` | new | minimal stdio JSON-RPC framing + passthrough pump |
| `smadp/proxy/redact.py` | new | `redact_secrets()` reusing `policy._REAL_SECRET_PATTERNS` |
| `smadp/proxy/recorder.py` | new | content-addressed recording session writer |
| `smadp/proxy/profile.py` | new | synthesize behavior profile + write `behavior-observed` evidence |
| `smadp/proxy/cli.py` | new | `smadp proxy record` / `proxy synthesize` |
| `smadp/passport/publish_sign.py` | new | sign a verdict's canonical sha → sidecar dict |
| `site/src/components/VerdictSignature.astro` | new | render signature + verify instructions |
| `smadp/api/routes/submit.py` | mod | add `POST /submit/profile` |
| `smadp/api/registered_keys.py` | new | registered-key store + signature check for federation |
| `config/registered_keys.json` | new | operator-curated federation key registry |
| `tests/schemas/test_evidence_level.py` | new | exhaustive ladder ordering tests |
| `tests/proxy/test_*.py` | new | passthrough fidelity, redaction, synthesis tests |
| `tests/passport/test_publish_sign.py` | new | sign/verify roundtrip |
| `tests/api/test_submit_profile.py` | new | federated submit tests |

> **Note on prose vs code:** Tasks 1, 2, 3 and the signing core (Task 5) carry complete code. Tasks 4, 6, 7, 8 give complete failing-test code plus precise prose implementation specs — author against the REAL API (read the surrounding files first; the planner enumerated exact line numbers but VERIFY them by content since the worktree has S1/S2 changes). If a signature differs from the prose, adapt minimally and preserve the test's behavior contract. NO emoji anywhere.

---

## Task 1 — Insert the `behavior-observed` rung everywhere (the five-rung ladder)

**Files:** `smadp/schemas/evidence_level.py` (new) + every duplicated ladder site (see File Structure) + `tests/schemas/test_evidence_level.py` (new)

This is the load-bearing, highest-risk task. The ladder is **duplicated** across the codebase; enumerate and fix every ordering/comparison/enum/color/label site so later tasks build on a correct five-rung ordering: `unverified-profile < docs-only < behavior-observed < profile-verified < sandbox-validated`. IMPORTANT: this worktree has S1 (and possibly S2) changes — grep for every literal containing `"sandbox-validated"`, `"profile-verified"`, `"docs-only"`, `"unverified-profile"` and the ordered tuples/dicts/enums to find ALL sites, do not trust line numbers blindly.

- [ ] Write the failing test `tests/schemas/test_evidence_level.py`:

```python
"""The five-rung evidence ladder is canonical and correctly ordered."""
from __future__ import annotations

import pytest

from smadp.schemas.evidence_level import EVIDENCE_LADDER, is_at_least, rank


def test_ladder_is_exactly_five_rungs_in_order() -> None:
    assert EVIDENCE_LADDER == (
        "unverified-profile",
        "docs-only",
        "behavior-observed",
        "profile-verified",
        "sandbox-validated",
    )


def test_behavior_observed_sits_between_docs_only_and_profile_verified() -> None:
    assert rank("docs-only") < rank("behavior-observed") < rank("profile-verified")


@pytest.mark.parametrize(
    "lower,higher",
    [
        ("unverified-profile", "docs-only"),
        ("docs-only", "behavior-observed"),
        ("behavior-observed", "profile-verified"),
        ("profile-verified", "sandbox-validated"),
    ],
)
def test_strict_monotonic_ranks(lower: str, higher: str) -> None:
    assert rank(lower) < rank(higher)


def test_rank_round_trips_index() -> None:
    for i, level in enumerate(EVIDENCE_LADDER):
        assert rank(level) == i


def test_is_at_least() -> None:
    assert is_at_least("profile-verified", "behavior-observed") is True
    assert is_at_least("behavior-observed", "profile-verified") is False
    assert is_at_least("sandbox-validated", "unverified-profile") is True


def test_rank_rejects_unknown_level() -> None:
    with pytest.raises(ValueError):
        rank("totally-made-up")
```

- [ ] Run `.venv/bin/python -m pytest tests/schemas/test_evidence_level.py` — expect **ImportError**.
- [ ] Create `smadp/schemas/evidence_level.py`:

```python
"""Canonical SMADP evidence ladder — single source of truth for ordering.

The ladder is intentionally five rungs, ordered weakest->strongest:

    unverified-profile < docs-only < behavior-observed < profile-verified
    < sandbox-validated

``behavior-observed`` (added by Pillar S3.1) is the first path for a
closed-source agent to climb past ``docs-only``: its observed runtime
behavior, captured by the MCP recording proxy, is evidence even when its
source is not. Every site that compares evidence levels MUST derive its
ordering from EVIDENCE_LADDER / rank here so a future rung insertion is a
one-line change rather than a codebase-wide hunt.
"""
from __future__ import annotations

from typing import Literal

EvidenceLevel = Literal[
    "unverified-profile",
    "docs-only",
    "behavior-observed",
    "profile-verified",
    "sandbox-validated",
]

EVIDENCE_LADDER: tuple[EvidenceLevel, ...] = (
    "unverified-profile",
    "docs-only",
    "behavior-observed",
    "profile-verified",
    "sandbox-validated",
)

_RANK: dict[str, int] = {level: i for i, level in enumerate(EVIDENCE_LADDER)}


def rank(level: str) -> int:
    """Return the ordinal rank of ``level`` (0 = weakest). Raises on unknown."""
    try:
        return _RANK[level]
    except KeyError as exc:
        raise ValueError(f"unknown evidence_level: {level!r}") from exc


def is_at_least(level: str, floor: str) -> bool:
    """True iff ``level`` is at or above ``floor`` on the ladder."""
    return rank(level) >= rank(floor)


__all__ = ["EVIDENCE_LADDER", "EvidenceLevel", "is_at_least", "rank"]
```

- [ ] Run `.venv/bin/python -m pytest tests/schemas/test_evidence_level.py` — expect **pass**.
- [ ] Commit: `feat(schemas): canonical five-rung evidence ladder with behavior-observed`

Now propagate to every duplicated site (grep first; the planner's line numbers are pre-S1/S2). After each cluster, run the relevant existing tests.

- [ ] `smadp/schemas/verdict.py`: replace the local `EvidenceLevel = Literal[...]` with `from smadp.schemas.evidence_level import EvidenceLevel` (keep the re-export so `from smadp.schemas.verdict import EvidenceLevel` still works).
- [ ] `smadp/schemas/chain.py`: replace the local `EvidenceLevel = Literal[...]` with the import.
- [ ] `smadp/schemas/profile.py`: change the inline `evidence_level: Literal[...] | None` to use the imported `EvidenceLevel | None`.
- [ ] `smadp/sandbox/promote.py`: replace the hand-written `_EVIDENCE_LADDER` tuple with `from smadp.schemas.evidence_level import EVIDENCE_LADDER as _EVIDENCE_LADDER` (`_maybe_promote` indexes via `.index()` so it stays correct). NOTE: S1 may have edited promote.py — verify the ladder tuple is still there and re-point it.
- [ ] `smadp/autopilot/pending.py`: replace the `tier_rank` dict-literal with `from smadp.schemas.evidence_level import EVIDENCE_LADDER, rank` and `return rank(self.evidence_level) if self.evidence_level in EVIDENCE_LADDER else -1` (preserve the `-1` for unknown).
- [ ] `smadp/analyzer/judge.py`: add `"behavior-observed"` to the valid-level tuple in the `evidence_level not in (...)` guard.
- [ ] `smadp/llm/prompts/pairwise_judge.py`: add `"behavior-observed"` to the JSON-schema `enum` array (between `"docs-only"` and `"profile-verified"`).
- [ ] `smadp/autopilot/scaffolders/mcp_adapter.py`: add `"behavior-observed": 0.4` to `_TRUST_FLOOR_BY_EVIDENCE` (between docs-only 0.3 and profile-verified 0.5); add `"behavior-observed"` to `_ENRICHED_TIERS`.
- [ ] `smadp/autopilot/bootstrap.py`: add `"behavior-observed"` to `_ENRICHED_TIERS`.
- [ ] `smadp/autopilot/planners/pair_gate.py`: add `"behavior-observed"` to `_ENRICHED_TIERS`. NOTE: S2 added a `triage` field here — preserve it.
- [ ] `smadp/autopilot/daily_report.py`: insert `"behavior-observed"` into the descending tier-order tuple (after `"profile-verified"`). NOTE: S2 added a capability-creep section — preserve it.
- [ ] `smadp/cli.py`: add `"behavior-observed": "#06B6D4",` to `_EVIDENCE_COLORS`.
- [ ] `catalog/_meta/schema/1.0/verdict.schema.json` and `chain.schema.json`: insert `"behavior-observed"` into the `evidence_level` enum array between `"docs-only"` and `"profile-verified"`.
- [ ] Site: `site/src/data/types.ts` — add `| 'behavior-observed'` to the `EvidenceLevel` union. `site/src/data/catalog.ts` `evidenceLevelColor` — add `'behavior-observed': '#06B6D4',`. `site/src/components/EvidenceLevelBadge.astro` `labels` — add `'behavior-observed': 'behavior-observed',`. If a ranked `evidence_levels[]` array is built in the data loader, the new rung's rank is 2 and later ranks shift.
- [ ] Run ladder-touching tests: `.venv/bin/python -m pytest tests/sandbox/test_promote.py tests/autopilot tests/golden tests/unit -q` — fix any test hard-coding a four-element ladder.
- [ ] Run `.venv/bin/python -m pytest -q` full regression — expect **pass**.
- [ ] Commit: `feat(ladder): insert behavior-observed rung across schemas, promote, pending, cli, api, site`

---

## Task 2 — Minimal stdio JSON-RPC passthrough core

**Files:** `smadp/proxy/__init__.py`, `smadp/proxy/jsonrpc.py`, `tests/proxy/__init__.py`, `tests/proxy/test_jsonrpc.py` (all new)

A stdio man-in-the-middle: spawn the agent's configured MCP server command, pump bytes both ways unmodified, while a tee callback observes every complete JSON-RPC message. Newline-delimited stdio transport. No `mcp` dependency.

- [ ] Write the failing test `tests/proxy/test_jsonrpc.py`:

```python
"""The stdio passthrough relays bytes unmodified and tees parsed messages."""
from __future__ import annotations

import asyncio
import json

import pytest

from smadp.proxy.jsonrpc import pump_stream


@pytest.mark.asyncio
async def test_pump_relays_unmodified_and_tees_each_message() -> None:
    src = asyncio.StreamReader()
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "read_file"}]}},
    ]
    raw = b"".join(
        (json.dumps(m, separators=(",", ":")) + "\n").encode("utf-8") for m in msgs
    )
    src.feed_data(raw)
    src.feed_eof()

    relayed = bytearray()
    teed: list[dict] = []

    class _Sink:
        def write(self, b: bytes) -> None:
            relayed.extend(b)

        async def drain(self) -> None:
            return None

    await pump_stream(src, _Sink(), tee=teed.append, direction="c2s")

    assert bytes(relayed) == raw
    assert teed == msgs


@pytest.mark.asyncio
async def test_pump_passes_through_unparseable_lines_without_crashing() -> None:
    src = asyncio.StreamReader()
    src.feed_data(b"not json\n")
    src.feed_eof()
    relayed = bytearray()
    teed: list[dict] = []

    class _Sink:
        def write(self, b: bytes) -> None:
            relayed.extend(b)

        async def drain(self) -> None:
            return None

    await pump_stream(src, _Sink(), tee=teed.append, direction="s2c")
    assert bytes(relayed) == b"not json\n"
    assert teed == []
```

- [ ] Run `.venv/bin/python -m pytest tests/proxy/test_jsonrpc.py` — expect **ModuleNotFoundError**.
- [ ] Create `smadp/proxy/__init__.py`:

```python
"""Operator-run, local, opt-in MCP recording proxy (Pillar S3.1).

A stdio man-in-the-middle that wraps an agent's configured MCP server
command, relaying every byte unmodified while recording each JSON-RPC
message (secrets redacted, content-addressed). Recordings synthesize a
``behavior-observed`` runtime profile that passes through the operator
gate before it can influence any published verdict.
"""
```

- [ ] Create `smadp/proxy/jsonrpc.py`:

```python
"""Minimal newline-delimited stdio JSON-RPC passthrough.

No ``mcp`` package is available (see plan Spec deviation 1), so this module
implements the common MCP stdio transport directly: one JSON object per line.
The proxy's contract is byte-for-byte passthrough — we never re-serialize a
relayed message, only parse a copy to tee for recording. A malformed line is
relayed unchanged and teed as nothing, so the wrapped server is never broken
by our observation.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

import structlog

log = structlog.get_logger(__name__)

Tee = Callable[[dict[str, Any]], None]


class _Writable(Protocol):
    def write(self, data: bytes) -> None: ...
    async def drain(self) -> None: ...


async def pump_stream(
    reader: Any,
    writer: _Writable,
    *,
    tee: Tee,
    direction: str,
) -> None:
    """Relay newline-framed messages from ``reader`` to ``writer`` unmodified.

    For every complete line that parses as a JSON object, call ``tee`` with the
    parsed dict (the original bytes are what gets relayed). EOF ends the pump.
    ``direction`` is a label ("c2s"/"s2c") for logs.
    """
    while True:
        line = await reader.readline()
        if not line:  # EOF
            return
        writer.write(line)  # passthrough fidelity: relay original bytes verbatim
        await writer.drain()
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            log.debug("proxy.jsonrpc.unparseable", direction=direction)
            continue
        if isinstance(parsed, dict):
            tee(parsed)


__all__ = ["Tee", "pump_stream"]
```

- [ ] Run `.venv/bin/python -m pytest tests/proxy/test_jsonrpc.py` — expect **pass**.
- [ ] Commit: `feat(proxy): minimal stdio JSON-RPC passthrough pump with tee`

---

## Task 3 — Redaction transformer reusing the existing secret patterns

**Files:** `smadp/proxy/redact.py` (new), `tests/proxy/test_redact.py` (new)

Reuse `smadp.sandbox.policy._REAL_SECRET_PATTERNS` as the single source of truth; add a transformer that rewrites matches to `***REDACTED***` recursively over a JSON-RPC message before it is recorded.

- [ ] Write the failing test `tests/proxy/test_redact.py`:

```python
"""Redaction rewrites real secrets in recorded messages, reusing policy patterns."""
from __future__ import annotations

from smadp.proxy.redact import redact_secrets
from smadp.sandbox.policy import looks_like_real_secret


def test_redacts_api_key_in_nested_params() -> None:
    msg = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "http_get",
            "arguments": {"headers": {"Authorization": "Bearer sk-ABCDEFGHIJKLMNOPQRSTUV"}},
        },
    }
    out = redact_secrets(msg)
    leaked = out["params"]["arguments"]["headers"]["Authorization"]
    assert "sk-ABCDEFGHIJKLMNOPQRSTUV" not in leaked
    assert "***REDACTED***" in leaked
    assert "sk-ABCDEFGHIJKLMNOPQRSTUV" in msg["params"]["arguments"]["headers"]["Authorization"]


def test_redacts_inside_lists_and_preserves_structure() -> None:
    msg = {"result": {"content": ["ghp_" + "a" * 36, "harmless text"]}}
    out = redact_secrets(msg)
    assert out["result"]["content"][0] == "***REDACTED***"
    assert out["result"]["content"][1] == "harmless text"


def test_no_secret_is_a_noop_equal_copy() -> None:
    msg = {"method": "tools/list", "params": {"x": 1, "y": ["a", "b"]}}
    assert redact_secrets(msg) == msg


def test_uses_same_detector_as_policy() -> None:
    assert looks_like_real_secret("AKIA" + "A" * 16) is True
    assert redact_secrets({"k": "AKIA" + "A" * 16})["k"] == "***REDACTED***"
```

- [ ] Run `.venv/bin/python -m pytest tests/proxy/test_redact.py` — expect **ModuleNotFoundError**.
- [ ] Create `smadp/proxy/redact.py`:

```python
"""Secret redaction for recorded MCP messages.

Reuses the existing real-secret detection rules from
``smadp.sandbox.policy`` (``_REAL_SECRET_PATTERNS``) so the proxy and the
sandbox share one canonical secret vocabulary — patterns never drift apart.
This transformer is additive: ``policy`` detects; we rewrite matches to
``***REDACTED***`` so a recording can be content-addressed and stored as
evidence without persisting live credentials.
"""
from __future__ import annotations

from typing import Any

from smadp.sandbox.policy import _REAL_SECRET_PATTERNS

_PLACEHOLDER = "***REDACTED***"


def _redact_str(value: str) -> str:
    out = value
    for pat in _REAL_SECRET_PATTERNS:
        out = pat.sub(_PLACEHOLDER, out)
    return out


def redact_secrets(obj: Any) -> Any:
    """Return a deep copy of ``obj`` with any real-secret substrings rewritten.

    Recurses dicts/lists; leaves non-string scalars untouched. Never mutates
    the input.
    """
    if isinstance(obj, str):
        return _redact_str(obj)
    if isinstance(obj, dict):
        return {k: redact_secrets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_secrets(v) for v in obj]
    return obj


__all__ = ["redact_secrets"]
```

  (VERIFY: `_REAL_SECRET_PATTERNS` are compiled `re.Pattern` objects supporting `.sub`. If they are raw strings, compile them or wrap. If S1 moved/renamed them, find the real location.)
- [ ] Run `.venv/bin/python -m pytest tests/proxy/test_redact.py` — expect **pass**.
- [ ] Commit: `feat(proxy): redaction transformer reusing sandbox secret patterns`

---

## Task 4 — Recording session + behavior-profile synthesis (behavior-observed evidence)

**Files:** `smadp/proxy/recorder.py` (new), `smadp/proxy/profile.py` (new), `smadp/proxy/cli.py` (new), `smadp/cli.py` (register `proxy` group), `tests/proxy/test_recorder.py` (new), `tests/proxy/test_profile.py` (new)

A recording session collects redacted messages and writes them as a content-addressed evidence record (same `sha256-<hash>.json` scheme as the docs evidence store). Synthesis reads a recording and produces a `behavior-observed` profile stub written to `catalog/profiles/_unverified/` — operator-gated. Kill switch: a `state/PROXY_DISABLED` file.

- [ ] Write `tests/proxy/test_recorder.py` (per the planner): a `RecordingSession.observe(...)` of two messages then `finalize()` writes `_evidence/sha256-<hash>.json` with secrets redacted, captures tool names, and is content-stable (`rec.sha256 == RecordingSession.sha_for(blob["messages"])`); `RecordingSession.is_disabled(state_dir=...)` True when `PROXY_DISABLED` present.
- [ ] Run → expect **ModuleNotFoundError**.
- [ ] Create `smadp/proxy/recorder.py`:

```python
"""Recording session: collect redacted MCP messages -> content-addressed evidence."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from smadp.proxy.redact import redact_secrets
from smadp.utils.time import utcnow

KILL_SWITCH = "PROXY_DISABLED"


@dataclass
class RecordingRecord:
    sha256: str
    message_count: int
    path: Path


@dataclass
class RecordingSession:
    slug: str
    evidence_dir: Path
    messages: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def is_disabled(*, state_dir: Path) -> bool:
        return (state_dir / KILL_SWITCH).exists()

    @staticmethod
    def sha_for(messages: list[dict[str, Any]]) -> str:
        canonical = json.dumps(
            messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def observe(self, message: dict[str, Any], *, direction: str) -> None:
        self.messages.append({"direction": direction, "message": redact_secrets(message)})

    def finalize(self) -> RecordingRecord:
        sha = self.sha_for(self.messages)
        blob = {
            "kind": "mcp-recording",
            "slug": self.slug,
            "recorded_at": utcnow().isoformat(timespec="seconds").replace("+00:00", "Z"),
            "messages": self.messages,
        }
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"sha256-{sha}.json"
        if not path.exists():
            path.write_text(
                json.dumps(blob, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return RecordingRecord(sha256=sha, message_count=len(self.messages), path=path)


__all__ = ["KILL_SWITCH", "RecordingRecord", "RecordingSession"]
```

- [ ] Run → expect **pass**.
- [ ] Write `tests/proxy/test_profile.py` (per the planner): `synthesize_behavior_profile(...)` over a recording with `tools/call` for `read_file` + `http_get(url=https://api.acme.com/v1)` yields `evidence_level == "behavior-observed"`, `onexus.behavior.observed_tools` includes both tools, `network_hosts` includes `api.acme.com`, `evidence_refs == [evidence_ref]`, and is deterministic.
- [ ] Run → expect **ModuleNotFoundError**.
- [ ] Create `smadp/proxy/profile.py`:

```python
"""Synthesize a runtime behavior-observed profile from an MCP recording.

Deterministic, pure-Python: reads the recorded (redacted) JSON-RPC messages and
derives the observed runtime surfaces — tools actually called, filesystem paths
touched, network hosts contacted. The result is a profile stub at
``evidence_level: "behavior-observed"`` that lands in
``catalog/profiles/_unverified/`` and passes through the operator gate exactly
like a docs-only or ONEXUS seed. No LLM, no numbers that rank.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from smadp.utils.time import utcnow

_FILE_ARG_KEYS = ("path", "file", "filename", "dir", "directory")
_URL_ARG_KEYS = ("url", "endpoint", "uri", "host")


def _iter_tool_calls(messages: list[dict[str, Any]]):
    for entry in messages:
        msg = entry.get("message", {})
        if msg.get("method") == "tools/call":
            params = msg.get("params", {})
            yield params.get("name"), params.get("arguments", {}) or {}


def synthesize_behavior_profile(
    *, slug: str, name: str, messages: list[dict[str, Any]], evidence_ref: str
) -> dict[str, Any]:
    observed_tools: list[str] = []
    file_paths: list[str] = []
    network_hosts: list[str] = []
    for tool_name, args in _iter_tool_calls(messages):
        if tool_name and tool_name not in observed_tools:
            observed_tools.append(tool_name)
        for k, v in args.items():
            if isinstance(v, str):
                if k in _FILE_ARG_KEYS and v not in file_paths:
                    file_paths.append(v)
                if k in _URL_ARG_KEYS:
                    host = urlparse(v).netloc or v
                    if host and host not in network_hosts:
                        network_hosts.append(host)

    now = utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")
    behavior = {
        "observed_tools": sorted(observed_tools),
        "file_paths": sorted(file_paths),
        "network_hosts": sorted(network_hosts),
        "source": "mcp-recording-proxy",
    }
    return {
        "schema_version": "1.1",
        "slug": slug,
        "name": name,
        "evidence_level": "behavior-observed",
        "evidence_refs": [evidence_ref],
        "first_seen_at": now,
        "last_refreshed_at": now,
        "onexus": {"behavior": behavior},
    }
```

  (VERIFY the profile stub validates against the real Profile schema's required fields — the planner's stub may be missing required keys like `vendor`/`category`/`verification`. If the schema requires them, add minimal placeholder values consistent with how `agents_sync` seeds stage `_unverified/` profiles, OR confirm `_unverified/` staging tolerates partial stubs as the sync path does.)
- [ ] Run → expect **pass**.
- [ ] Create `smadp/proxy/cli.py` with a Click group `proxy`: `record --slug SLUG -- <server cmd...>` (abort if `RecordingSession.is_disabled`; spawn via `asyncio.create_subprocess_exec`; two `pump_stream` tasks teeing `session.observe`; forward child stderr; `finalize()` + chronicle `proxy.recording.captured`) and `synthesize --slug --name --recording sha256:<hash>` (load recording, `synthesize_behavior_profile`, write to `_unverified/` via the bootstrap atomic writer, print staged path). Register in `smadp/cli.py` mirroring the existing `passport_group` registration.
- [ ] Run `.venv/bin/python -m pytest tests/proxy -q` — expect **pass**.
- [ ] Commit: `feat(proxy): recording sessions, behavior-observed synthesis, and proxy CLI`

---

## Task 5 — Sign verdicts at publish time (BYOK detached sidecar)

**Files:** `smadp/passport/publish_sign.py` (new), `smadp/autopilot/pending.py` (sign in `approve_one`), `smadp/autopilot/approve.py` (re-point), `smadp/cli.py` (`pending init-signing-key`), `tests/passport/__init__.py` (new), `tests/passport/test_publish_sign.py` (new)

Reuse the existing BYOK Ed25519 machinery to sign a verdict when promoted pending→verdicts, writing a detached `<key>.sig.json` sidecar. Best-effort: a missing key publishes unsigned (never blocks the operator gate).

- [ ] Write `tests/passport/test_publish_sign.py` (per the planner): `sign_verdict_dict(verdict, signing_key=Ed25519PrivateKey)` → sidecar with `signature_hex`, `canonical_sha256` (sha256: prefix), `public_key_hex`; `verify_verdict_signature` roundtrips True; a tampered verdict verifies False; `public_key_hex` matches the key's raw public bytes.
- [ ] Run → expect **ModuleNotFoundError**.
- [ ] Create `smadp/passport/publish_sign.py`:

```python
"""Detached Ed25519 signing of published verdicts (Pillar S3.2).

To sign a verdict at ``pending approve`` without changing the verdict's
canonical bytes (which the passport hashes — adding a signature field would be
circular), we emit a detached sidecar: a signature over the verdict's canonical
sha256. The sidecar lives at ``catalog/verdicts/<key>.sig.json`` and is rendered
on the site with verification instructions.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def _canonical_sha(verdict: dict[str, Any]) -> str:
    canonical = json.dumps(
        verdict, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def sign_verdict_dict(
    verdict: dict[str, Any], *, signing_key: Ed25519PrivateKey
) -> dict[str, Any]:
    sha = _canonical_sha(verdict)
    sig = signing_key.sign(sha.encode("utf-8"))
    pub = signing_key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    )
    return {
        "signing_strategy": "byok",
        "canonical_sha256": sha,
        "signature_hex": sig.hex(),
        "public_key_hex": pub.hex(),
    }


def verify_verdict_signature(verdict: dict[str, Any], sidecar: dict[str, Any]) -> bool:
    if _canonical_sha(verdict) != sidecar.get("canonical_sha256"):
        return False
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(sidecar["public_key_hex"]))
        pub.verify(bytes.fromhex(sidecar["signature_hex"]),
                   sidecar["canonical_sha256"].encode("utf-8"))
    except (KeyError, ValueError, InvalidSignature):
        return False
    return True


__all__ = ["sign_verdict_dict", "verify_verdict_signature"]
```

- [ ] Run → expect **pass**.
- [ ] Wire signing into `smadp/autopilot/pending.py` `approve_one`: after the pending→verdicts rename succeeds, load `keys.load_signing_key(workspace_id="_smadp_publisher")`; if None, log `pending.publish.unsigned` and skip; else read the moved verdict, `sign_verdict_dict`, write `<verdict>.sig.json` atomically, chronicle `pending.publish.signed`. Wrap in try/except logging `pending.publish.sign_failed` — never block publish. (VERIFY the real `tenancy.keys` API names.)
- [ ] Re-point `smadp/autopilot/approve.py::approve` to delegate to `approve_one` (keep `ApproveError` for back-compat). NOTE: S2 added `approve_chain` to this file — preserve it.
- [ ] Add `smadp pending init-signing-key` to `smadp/cli.py` (generate Ed25519, `keys.upload_signing_key(workspace_id="_smadp_publisher", ...)`, print public hex).
- [ ] Add `tests/autopilot/test_approve_signs.py`: approve with a provisioned `_smadp_publisher` key → `.sig.json` exists and verifies; with no key → file still moves, logs unsigned, no sidecar.
- [ ] Run `.venv/bin/python -m pytest tests/autopilot/test_approve.py tests/autopilot/test_approve_signs.py tests/passport -q` — expect **pass**.
- [ ] Commit: `feat(publish): sign verdicts at pending-approve with detached BYOK sidecar`

---

## Task 6 — Surface the verdict signature on the site

**Files:** `site/src/components/VerdictSignature.astro` (new), `site/src/pages/verdicts/[id].astro` (mod), `site/src/data/catalog.ts` (load sidecar)

- [ ] Add a loader in the verdict data layer: read `<key>.sig.json` alongside each verdict; attach `signature?` to the view model (mirror how the verdict JSON is loaded). NOTE: S1's causality work added to `[id].astro` — preserve it.
- [ ] Create `site/src/components/VerdictSignature.astro`: render strategy (`byok`), canonical sha, truncated public key, and copy-pasteable verification instructions (Ed25519 over the verdict canonical sha256). No emoji; markers consistent with `EvidenceLevelBadge.astro`.
- [ ] Embed `<VerdictSignature signature={verdict.signature} />` in `[id].astro`, conditional on presence.
- [ ] Run site tests (`cd site && npm test` or the configured vitest) — expect **pass**; add a smoke assertion that a signed verdict view-model carries `signature`.
- [ ] Commit: `feat(site): render verdict signature + verification instructions on verdict pages`

---

## Task 7 — Registered-key store for federated submissions

**Files:** `smadp/api/registered_keys.py` (new), `config/registered_keys.json` (new), `tests/api/test_registered_keys.py` (new)

- [ ] Write `tests/api/test_registered_keys.py` (per the planner): a valid signature from a registered+enabled key verifies True; unknown key id False; disabled key False; bad signature False.
- [ ] Run → expect **ModuleNotFoundError**.
- [ ] Create `smadp/api/registered_keys.py`:

```python
"""Operator-curated registry of third-party federation signing keys.

Federated profile submissions (Pillar S3.2) must be signed by a key the
operator has registered in ``config/registered_keys.json``. A key can be
disabled without deletion (audit trail). Disabled/unknown keys and any
signature mismatch fail closed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


@dataclass(frozen=True)
class RegisteredKeys:
    keys: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, path: Path) -> "RegisteredKeys":
        if not path.exists():
            return cls(keys={})
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(keys={})
        return cls(keys=data if isinstance(data, dict) else {})

    def verify(self, *, key_id: str, body: bytes, signature_hex: str) -> bool:
        entry = self.keys.get(key_id)
        if not entry or not entry.get("enabled", False):
            return False
        try:
            pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(entry["public_key_hex"]))
            pub.verify(bytes.fromhex(signature_hex), body)
        except (KeyError, ValueError, InvalidSignature):
            return False
        return True


__all__ = ["RegisteredKeys"]
```

- [ ] Create `config/registered_keys.json` with `{}`.
- [ ] Run → expect **pass**.
- [ ] Commit: `feat(api): registered-key store for federated submissions`

---

## Task 8 — `POST /api/submit/profile` federated submission endpoint

**Files:** `smadp/api/routes/submit.py` (add route), `tests/api/test_submit_profile.py` (new)

Accept a third-party profile signed with a registered key; on valid signature land it in `catalog/profiles/_unverified/` exactly like an ONEXUS sync seed. Operator-token-gated AND key-signature-gated; never writes outside `_unverified/`; `state/FEDERATION_DISABLED` kill switch.

- [ ] Write `tests/api/test_submit_profile.py` (per the planner, adapting to the repo's API-client + operator-token fixtures): a valid signed submission → 202 and a staged `_unverified/<slug>.json` (and NOT a published `profiles/<slug>.json`); an unregistered key → 403; missing operator token → 401/503.
- [ ] Run → expect **failure** (404/fixtures).
- [ ] Add the route to `smadp/api/routes/submit.py`: read raw body + `X-SMADP-Key-Id`/`X-SMADP-Signature` headers; `Depends(require_operator_token)` + `_rate_limit`; `RegisteredKeys.load(cfg.repo_root/"config"/"registered_keys.json").verify(...)` → 403 on fail; parse+validate the profile, force `evidence_level` to `"unverified-profile"` (never let a submitter self-assert a higher rung), stamp `onexus.federated` provenance; write to `cfg.unverified_profiles_dir/f"{slug}.json"` via the bootstrap atomic writer; 409 if the slug already exists in published `profiles/`; chronicle `profile.federated.submitted`; 202. `state/FEDERATION_DISABLED` → 503 before any work.
- [ ] Run `.venv/bin/python -m pytest tests/api/test_submit_profile.py` — expect **pass**.
- [ ] Run the full suite `.venv/bin/python -m pytest -q` — expect **pass**.
- [ ] Commit: `feat(api): POST /api/submit/profile federated signed submissions into _unverified/`

---

## Self-Review — S3.x requirement → task mapping

| Spec requirement | Task(s) |
|---|---|
| S3.1 `smadp/proxy/` stdio MCP man-in-the-middle wrapping the agent's MCP server | Task 2 (passthrough), Task 4 (`proxy record` spawns + pumps) |
| S3.1 record every JSON-RPC request/response, content-addressed (sha256) | Task 4 `RecordingSession` |
| S3.1 secrets redacted via existing rules; passed through unmodified | Task 3 (reuses `policy._REAL_SECRET_PATTERNS`), Task 2 (byte-verbatim relay) |
| S3.1 synthesize runtime behavior profile (observed tools, file/network surfaces) | Task 4 `synthesize_behavior_profile` |
| S3.1 stored as evidence with same sha256 content-addressing as docs evidence | Task 4 |
| S3.1 NEW rung `behavior-observed` between docs-only and profile-verified; five rungs ordered correctly EVERYWHERE | **Task 1** (canonical module + every site) |
| S3.1 operator-run, local, opt-in; recordings pass operator gate before influencing verdicts | Task 4 (writes only to `_unverified/`; `PROXY_DISABLED` kill switch) |
| S3.2 wire BYOK passport signing into publish: `pending approve` signs | Task 5 |
| S3.2 site verdict pages display signature + verification instructions | Task 6 |
| S3.2 `POST /api/submit/profile` accepts third-party profiles signed with a registered key | Task 7 (`registered_keys.py`), Task 8 (route) |
| S3.2 federated submissions land in `_unverified/` like ONEXUS seeds; caps/lint/promotion unchanged | Task 8 |
| Invariant: five-rung ordering respected everywhere `evidence_level` compared | Task 1 (exhaustive) |
| Invariant: nothing bypasses operator gate; autopilot can't write `verdicts/`/`chains/` | Tasks 4 & 8 write only `_unverified/`; Task 5 signs during operator-driven approve |
| Invariant: deterministic-composite contract preserved | Task 4 (observations only), Task 5 (detached sidecar) |
| Invariant: every new automated path has a kill switch | `PROXY_DISABLED` (T4), `FEDERATION_DISABLED` (T8), signing best-effort (T5) |
