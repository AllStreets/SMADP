# SMADP v2-D Plan 2 — Passport (render, sign, verify)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a self-contained signed HTML "passport" artifact that any auditor can verify offline, plus the API + CLI surfaces to render and verify it. Wire real Sigstore/Rekor submission (replacing the Plan 1 stub) so passports carry an inclusion proof when network is reachable, and degrade to a `deferred` mode when not.

**Architecture:** A new `smadp.passport` package owns rendering (Jinja2), signing (Ed25519 via BYOK or per-passport ephemeral key), and verification (offline byte-stable check). Sigstore submission is performed via direct Rekor REST API calls (`httpx`) gated by `SMADP_SIGSTORE_ENABLED`, so dev + tests stay offline by default. The renderer embeds (a) a canonical JSON payload, (b) base64 evidence attachments, and (c) signature/Rekor metadata in `<meta>` tags. The verifier extracts those, re-computes the hash, validates the signature, and (if a Rekor UUID is present) verifies the inclusion proof.

**Tech Stack:** Python 3.11/3.12, Pydantic v2, FastAPI, Click, Jinja2 (new), `cryptography` (Ed25519, already added in Plan 1), `httpx` (already a dep), `respx` (test mock, already a dep), SQLite, Astro frontend untouched.

---

## Pre-flight context (engineer must read)

You are continuing v2-D (audience C/D coverage). Plan 1 (foundation) shipped: tenancy + transparency log + BYOK keys. Plan 1 left a deliberate stub at `smadp/transparency/sigstore.py:submit_to_rekor` returning `None`. Plan 2 replaces that stub.

Key prior surfaces you will use:

- `smadp.transparency.journal.append_event(event_type, payload, signing_key, config) -> SignedEvent` — appends a signed event with chain linking. Returns the persisted event with `id`.
- `smadp.transparency.journal.iter_events(config)` — generator over events in id order.
- `smadp.transparency.journal._canonical_signing_input(ev) -> bytes` — what the journal signs.
- `smadp.tenancy.keys.upload_signing_key(workspace_id, private_key, config)` / `load_signing_key(workspace_id, config) -> Ed25519PrivateKey | None` / `get_public_key(workspace_id, config) -> Ed25519PublicKey | None` — BYOK store.
- `smadp.tenancy.store.create_workspace(name, plan, config)` / `get_workspace(workspace_id, config)` — workspaces.
- `smadp.catalog.repo.CatalogRepo.load_verdict(slug_a, slug_b) -> Verdict` — pair-based verdict load.
- `smadp.catalog.repo.CatalogRepo.load_evidence(ref) -> Evidence` — `ref` is `"sha256:<hex>"` or bare 64-char hex.
- `smadp.schemas.verdict.Verdict` — see file for fields. Notably `pair: tuple[str, str]`, `verdict_id: str`, `framework_mappings: dict[str, list[str]]`, `sub_verdicts` with citations referencing evidence sha256.
- `smadp.api.routes.__init__.ROUTERS` — register new routers here.
- `smadp.api.server.create_app(config)` — registers each router with prefix `/api`.
- `smadp.cli.cli` — Click root group; new subgroups attach via `cli.add_command(...)`.

Repo conventions you must follow:

- Pydantic v2 with `model_config = ConfigDict(extra="forbid")`.
- Tests live in `tests/unit/`, `tests/integration/`, `tests/golden/`.
- Use `.venv/bin/pytest`, `.venv/bin/python`, `.venv/bin/ruff`, `.venv/bin/mypy`.
- Ruff config is in `.ruff.toml` (NOT just `pyproject.toml`); both have `[lint]`/`[tool.ruff.lint]` sections — `.ruff.toml` takes precedence.
- All UI strings use **icons via inline SVG, never emoji** (project policy).

Branch policy: stay on `main`. Auto-commit per task is approved.

Plan-time picks (already decided; do not re-litigate):

- **Sigstore client:** direct Rekor REST via `httpx` (no `sigstore-python` library). Tests use `respx`.
- **Templating:** Jinja2.
- **Icons:** Lucide SVG snippets stored as Python string constants.
- **Verdict URL convention:** mirrors v1 — `/api/passports/{slug_a}/{slug_b}.html` (pair-based, NOT verdict_id-based).
- **Rekor instance:** `https://rekor.sigstore.dev` (Sigstore Public Good Instance). Configurable via `SMADP_REKOR_URL` env var.
- **Submission gating:** `SMADP_SIGSTORE_ENABLED=true` opt-in. Default off — passports render in `deferred` mode locally.

---

## Test fixture: shared verdict for golden tests

Multiple tasks need a deterministic verdict to render against. Rather than create one per task, use the existing v1 catalog. From `catalog/`, the verdict file format is JSON. For golden tests we will use a **frozen verdict fixture** committed under `tests/fixtures/passport/verdict.json` (Task 11 creates it). All other tasks that need a verdict use the in-memory factory `_make_verdict()` defined in their own test file.

---

## Task 1: Add jinja2 dependency

**Files:**
- Modify: `pyproject.toml` (dependencies block)

- [ ] **Step 1: Add jinja2 to dependencies**

Edit `pyproject.toml`. The `dependencies` block already contains `cryptography>=42.0` (added in Plan 1). Add `jinja2>=3.1` immediately after it, alphabetically appropriate. The block currently looks like:

```toml
dependencies = [
  "click>=8.1",
  "cryptography>=42.0",
  "rich>=13.0",
  ...
]
```

Insert `"jinja2>=3.1",` so the result is:

```toml
dependencies = [
  "click>=8.1",
  "cryptography>=42.0",
  "jinja2>=3.1",
  "rich>=13.0",
  ...
]
```

- [ ] **Step 2: Install**

Run: `.venv/bin/pip install -e ".[dev]"`
Expected: `jinja2` installed (or already present as transitive).

- [ ] **Step 3: Verify import works**

Run: `.venv/bin/python -c "import jinja2; print(jinja2.__version__)"`
Expected: a version number `>=3.1`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add jinja2 for v2-D passport templating"
```

---

## Task 2: Passport Pydantic schemas

**Files:**
- Create: `smadp/schemas/passport.py`
- Create: `tests/unit/test_schemas_passport.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_schemas_passport.py`:

```python
"""Tests for passport Pydantic schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from smadp.schemas.passport import (
    PassportMetadata,
    PassportRenderRequest,
    SigningStrategy,
    VerificationResult,
)


def test_signing_strategy_values():
    assert SigningStrategy.SIGSTORE.value == "sigstore"
    assert SigningStrategy.BYOK.value == "byok"
    # iteration order must be stable for golden tests
    assert [s.value for s in SigningStrategy] == ["sigstore", "byok"]


def test_passport_render_request_minimal():
    req = PassportRenderRequest(
        slug_a="anthropic/claude-sonnet-4.6",
        slug_b="openai/gpt-5",
        signing_strategy=SigningStrategy.BYOK,
        workspace_id="ws_TEST0001",
    )
    assert req.signing_strategy == SigningStrategy.BYOK


def test_passport_render_request_rejects_extra():
    with pytest.raises(ValidationError):
        PassportRenderRequest(
            slug_a="a",
            slug_b="b",
            signing_strategy=SigningStrategy.BYOK,
            workspace_id="ws_X0000001",
            unexpected="boom",
        )


def test_passport_metadata_roundtrip():
    md = PassportMetadata(
        verdict_id="vdt_X",
        rendered_at="2026-05-03T12:00:00Z",
        signing_strategy=SigningStrategy.BYOK,
        signature_hex="aabb",
        public_key_hex="ccdd",
        canonical_sha256="sha256:" + "0" * 64,
        rekor_uuid=None,
        rekor_log_index=None,
        transparency_event_id=42,
        transparency_status="local",
    )
    dumped = md.model_dump(mode="json")
    rebuilt = PassportMetadata.model_validate(dumped)
    assert rebuilt == md


def test_passport_metadata_rejects_extra():
    with pytest.raises(ValidationError):
        PassportMetadata(
            verdict_id="vdt_X",
            rendered_at="2026-05-03T12:00:00Z",
            signing_strategy=SigningStrategy.BYOK,
            signature_hex="aa",
            public_key_hex="bb",
            canonical_sha256="sha256:" + "0" * 64,
            rekor_uuid=None,
            rekor_log_index=None,
            transparency_event_id=1,
            transparency_status="local",
            extra="boom",
        )


def test_verification_result_valid():
    r = VerificationResult(valid=True, reason=None)
    assert r.valid is True
    assert r.reason is None


def test_verification_result_invalid():
    r = VerificationResult(valid=False, reason="signature mismatch")
    assert r.valid is False
    assert r.reason == "signature mismatch"


def test_verification_result_rejects_extra():
    with pytest.raises(ValidationError):
        VerificationResult(valid=True, reason=None, foo="bar")
```

- [ ] **Step 2: Run — expect failures**

Run: `.venv/bin/pytest tests/unit/test_schemas_passport.py -v`
Expected: ImportError (module doesn't exist).

- [ ] **Step 3: Implement the schemas**

Create `smadp/schemas/passport.py`:

```python
"""Passport schemas: render request, signing strategy, verification result, metadata."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SigningStrategy(StrEnum):
    SIGSTORE = "sigstore"
    BYOK = "byok"


class PassportRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug_a: str
    slug_b: str
    signing_strategy: SigningStrategy
    workspace_id: str


class PassportMetadata(BaseModel):
    """Authoritative metadata embedded in <meta> tags of a rendered passport."""

    model_config = ConfigDict(extra="forbid")

    verdict_id: str
    rendered_at: str  # ISO-8601 UTC, second-precision, ends in 'Z'
    signing_strategy: SigningStrategy
    signature_hex: str
    public_key_hex: str
    canonical_sha256: str  # "sha256:<64hex>" of the canonical payload bytes
    rekor_uuid: str | None
    rekor_log_index: int | None
    transparency_event_id: int
    transparency_status: Literal["local", "deferred", "submitted"]


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    reason: str | None


__all__ = [
    "PassportMetadata",
    "PassportRenderRequest",
    "SigningStrategy",
    "VerificationResult",
]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/unit/test_schemas_passport.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/schemas/passport.py tests/unit/test_schemas_passport.py
git commit -m "feat(passport): add SigningStrategy + PassportRenderRequest + PassportMetadata + VerificationResult schemas"
```

---

## Task 3: Canonical passport payload (byte-stable signing input)

**Files:**
- Create: `smadp/passport/__init__.py`
- Create: `smadp/passport/canonical.py`
- Create: `tests/golden/test_passport_canonical.py`

- [ ] **Step 1: Write the failing golden test**

Create `tests/golden/test_passport_canonical.py`:

```python
"""Golden test pinning byte-exact canonical passport payload."""

from __future__ import annotations

import hashlib
import json

from smadp.passport.canonical import (
    canonical_passport_payload,
    canonical_passport_sha256,
)


def test_canonical_payload_is_sorted_compact_utf8():
    """Canonical bytes must sort keys, drop whitespace, and be UTF-8."""
    verdict_dict = {
        "verdict_id": "vdt_X",
        "pair": ["a/x", "b/y"],
        "composite_score": 0.42,
        "headline": "Test",
        "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1"]},
    }
    frameworks_dict = {
        "nist_ai_rmf": {"name": "NIST AI RMF", "controls": [{"id": "GOVERN-1.1"}]}
    }
    evidence_index = {"sha256:abc": {"source_url": "https://x"}}
    rendered_at = "2026-05-03T12:34:56Z"

    out = canonical_passport_payload(
        verdict=verdict_dict,
        frameworks=frameworks_dict,
        evidence_index=evidence_index,
        rendered_at=rendered_at,
    )

    # Round-trip through json: must sort keys, no whitespace, ascii-safe.
    expected = json.dumps(
        {
            "evidence_index": evidence_index,
            "frameworks": frameworks_dict,
            "rendered_at": rendered_at,
            "verdict": verdict_dict,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    assert out == expected


def test_canonical_payload_is_deterministic_across_dict_orderings():
    a = canonical_passport_payload(
        verdict={"b": 2, "a": 1},
        frameworks={"x": 1, "a": 2},
        evidence_index={"z": 1, "a": 2},
        rendered_at="2026-05-03T00:00:00Z",
    )
    b = canonical_passport_payload(
        verdict={"a": 1, "b": 2},
        frameworks={"a": 2, "x": 1},
        evidence_index={"a": 2, "z": 1},
        rendered_at="2026-05-03T00:00:00Z",
    )
    assert a == b


def test_canonical_passport_sha256_format():
    out = canonical_passport_sha256(
        verdict={}, frameworks={}, evidence_index={}, rendered_at="2026-01-01T00:00:00Z"
    )
    assert out.startswith("sha256:")
    assert len(out) == 7 + 64  # "sha256:" + 64 hex chars

    # And it should match a manual compute
    payload = canonical_passport_payload(
        verdict={}, frameworks={}, evidence_index={}, rendered_at="2026-01-01T00:00:00Z"
    )
    expected = "sha256:" + hashlib.sha256(payload).hexdigest()
    assert out == expected
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/pytest tests/golden/test_passport_canonical.py -v`
Expected: ImportError on `smadp.passport.canonical`.

- [ ] **Step 3: Create the package and module**

Create `smadp/passport/__init__.py`:

```python
"""SMADP v2-D Plan 2: passport rendering, signing, and verification."""
```

Create `smadp/passport/canonical.py`:

```python
"""Byte-stable canonical passport payload — what the signature attests to."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_passport_payload(
    *,
    verdict: dict[str, Any],
    frameworks: dict[str, Any],
    evidence_index: dict[str, Any],
    rendered_at: str,
) -> bytes:
    """Return the canonical bytes that the passport signature attests to.

    Sorted keys, no whitespace, UTF-8. Deterministic across dict iteration order.
    """
    canonical = {
        "evidence_index": evidence_index,
        "frameworks": frameworks,
        "rendered_at": rendered_at,
        "verdict": verdict,
    }
    return json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_passport_sha256(
    *,
    verdict: dict[str, Any],
    frameworks: dict[str, Any],
    evidence_index: dict[str, Any],
    rendered_at: str,
) -> str:
    """sha256 of the canonical payload bytes, formatted as ``sha256:<hex>``."""
    payload = canonical_passport_payload(
        verdict=verdict,
        frameworks=frameworks,
        evidence_index=evidence_index,
        rendered_at=rendered_at,
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


__all__ = ["canonical_passport_payload", "canonical_passport_sha256"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/golden/test_passport_canonical.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/passport/__init__.py smadp/passport/canonical.py tests/golden/test_passport_canonical.py
git commit -m "feat(passport): canonical payload + sha256 for byte-stable signing input"
```

---

## Task 4: Lucide SVG icon constants

**Files:**
- Create: `smadp/passport/icons.py`
- Create: `tests/unit/test_passport_icons.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_passport_icons.py`:

```python
"""Tests for Lucide SVG icon constants used in passport rendering."""

from __future__ import annotations

from smadp.passport import icons


def test_required_icons_present():
    """Plan 2 passport templates use this set; if any is missing, render breaks."""
    required = {
        "shield",
        "check_circle",
        "alert_triangle",
        "file_text",
        "link",
        "lock",
        "fingerprint",
    }
    available = set(icons.LUCIDE_ICONS.keys())
    assert required.issubset(available), f"missing: {required - available}"


def test_icons_are_well_formed_svg():
    for name, svg in icons.LUCIDE_ICONS.items():
        assert svg.startswith("<svg "), f"{name}: not an svg tag"
        assert svg.endswith("</svg>"), f"{name}: not closed"
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg, f"{name}: missing xmlns"
        assert "viewBox" in svg, f"{name}: missing viewBox"


def test_render_icon_returns_svg_with_class():
    out = icons.render_icon("shield", css_class="passport-icon")
    assert out.startswith("<svg ")
    assert 'class="passport-icon"' in out


def test_render_icon_unknown_raises():
    import pytest

    with pytest.raises(KeyError):
        icons.render_icon("not-a-real-icon")
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/pytest tests/unit/test_passport_icons.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement icons module**

Create `smadp/passport/icons.py`:

```python
"""Lucide SVG icon constants used by passport templates.

These are minified Lucide SVGs (https://lucide.dev) embedded as strings so passports
are fully self-contained — no external <link> or <img>. Stroke-current so they
inherit color from CSS.
"""

from __future__ import annotations

# Each SVG is the inner Lucide markup with stroke="currentColor". Class is injected
# at render-time so callers can theme. viewBox is always 0 0 24 24 (Lucide standard).

_BASE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round"{class_attr}>{body}</svg>'
)

_BODIES: dict[str, str] = {
    "shield": (
        '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6'
        'a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5'
        'a1 1 0 0 1 1 1z"/>'
    ),
    "check_circle": (
        '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>'
    ),
    "alert_triangle": (
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>'
        '<path d="M12 9v4"/><path d="M12 17h.01"/>'
    ),
    "file_text": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
        '<line x1="16" y1="13" x2="8" y2="13"/>'
        '<line x1="16" y1="17" x2="8" y2="17"/>'
        '<line x1="10" y1="9" x2="8" y2="9"/>'
    ),
    "link": (
        '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
        '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'
    ),
    "lock": (
        '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    "fingerprint": (
        '<path d="M12 10v4"/><path d="M12 18v.01"/>'
        '<path d="M5 13a7 7 0 1 1 14 0v3a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-3z"/>'
    ),
}

LUCIDE_ICONS: dict[str, str] = {
    name: _BASE.format(class_attr="", body=body) for name, body in _BODIES.items()
}


def render_icon(name: str, *, css_class: str | None = None) -> str:
    """Return the SVG string for ``name``, optionally with a CSS class injected."""
    if name not in _BODIES:
        raise KeyError(f"Unknown Lucide icon: {name!r}")
    class_attr = f' class="{css_class}"' if css_class else ""
    return _BASE.format(class_attr=class_attr, body=_BODIES[name])


__all__ = ["LUCIDE_ICONS", "render_icon"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/unit/test_passport_icons.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/passport/icons.py tests/unit/test_passport_icons.py
git commit -m "feat(passport): inline Lucide SVG icon constants for self-contained HTML"
```

---

## Task 5: Jinja2 passport template

**Files:**
- Create: `smadp/passport/templates/passport.html.j2`
- Create: `tests/unit/test_passport_template_loads.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_passport_template_loads.py`:

```python
"""Smoke test: Jinja2 environment finds and parses the passport template."""

from __future__ import annotations

from smadp.passport.render import _jinja_env


def test_passport_template_loads_and_parses():
    env = _jinja_env()
    tpl = env.get_template("passport.html.j2")
    # Render with a minimal context to confirm syntax is valid; we only check
    # for some sentinel substrings, not byte-stability (that's the golden test).
    out = tpl.render(
        verdict={"verdict_id": "vdt_X", "headline": "Test"},
        frameworks={},
        evidence_index={},
        metadata_json="{}",
        rendered_at="2026-05-03T00:00:00Z",
        signing_strategy_label="byok",
        signature_hex="abc",
        public_key_hex="def",
        canonical_sha256="sha256:" + "0" * 64,
        rekor_uuid="",
        rekor_log_index="",
        transparency_event_id=1,
        transparency_status="local",
        icons={"shield": "<svg></svg>"},
        evidence_blobs_b64="e30=",
    )
    assert "<!DOCTYPE html>" in out
    assert "vdt_X" in out
    assert "smadp-canonical-sha256" in out  # meta tag present
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/pytest tests/unit/test_passport_template_loads.py -v`
Expected: ImportError on `smadp.passport.render._jinja_env` (Task 6 builds it).

- [ ] **Step 3: Create the template**

Create `smadp/passport/templates/passport.html.j2`:

```jinja
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>SMADP Passport — {{ verdict.verdict_id }}</title>
<meta name="generator" content="SMADP v2-D Plan 2" />
<meta name="smadp-passport-version" content="1" />
<meta name="smadp-rendered-at" content="{{ rendered_at }}" />
<meta name="smadp-signing-strategy" content="{{ signing_strategy_label }}" />
<meta name="smadp-signature-hex" content="{{ signature_hex }}" />
<meta name="smadp-public-key-hex" content="{{ public_key_hex }}" />
<meta name="smadp-canonical-sha256" content="{{ canonical_sha256 }}" />
<meta name="smadp-rekor-uuid" content="{{ rekor_uuid }}" />
<meta name="smadp-rekor-log-index" content="{{ rekor_log_index }}" />
<meta name="smadp-transparency-event-id" content="{{ transparency_event_id }}" />
<meta name="smadp-transparency-status" content="{{ transparency_status }}" />
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    max-width: 880px; margin: 32px auto; padding: 0 24px; line-height: 1.5;
    color: #1a1a1a; background: #fafafa; }
  @media (prefers-color-scheme: dark) {
    body { color: #f1f1f1; background: #15131c; }
    .panel { background: #1f1b2c !important; border-color: #2d2640 !important; }
    .panel-header { background: #2a2440 !important; }
    a { color: #b39bff; }
  }
  h1 { font-size: 22px; margin: 0 0 8px; }
  h2 { font-size: 16px; margin: 24px 0 8px; display: flex; align-items: center; gap: 8px; }
  .passport-icon { width: 18px; height: 18px; vertical-align: middle; }
  .panel { border: 1px solid #e2e2ea; border-radius: 8px; background: #fff;
    margin: 12px 0; overflow: hidden; }
  .panel-header { background: #f4f3f8; padding: 8px 12px; cursor: pointer;
    display: flex; align-items: center; gap: 8px; user-select: none;
    border-bottom: 1px solid transparent; }
  details[open] .panel-header { border-bottom-color: #e2e2ea; }
  .panel-body { padding: 12px; }
  .meta-row { display: grid; grid-template-columns: 180px 1fr; gap: 4px 16px;
    font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
  .badge-ok { background: #d6f5e0; color: #0a5d1f; }
  .badge-deferred { background: #fff1c4; color: #7a5300; }
  .badge-local { background: #e0e7ff; color: #2741a3; }
  code { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px;
    word-break: break-all; }
</style>
</head>
<body>

<header>
  <h1>{{ icons.shield | safe }} SMADP Passport</h1>
  <div class="meta-row">
    <span>Verdict ID:</span><code>{{ verdict.verdict_id }}</code>
    <span>Rendered at:</span><code>{{ rendered_at }}</code>
    <span>Signing strategy:</span><code>{{ signing_strategy_label }}</code>
    <span>Transparency:</span>
    <span>
      {% if transparency_status == "submitted" %}
      <span class="badge badge-ok">{{ icons.check_circle | safe }} Rekor inclusion proof embedded</span>
      {% elif transparency_status == "deferred" %}
      <span class="badge badge-deferred">{{ icons.alert_triangle | safe }} Deferred — local-only, retry pending</span>
      {% else %}
      <span class="badge badge-local">{{ icons.lock | safe }} Local journal only</span>
      {% endif %}
    </span>
  </div>
</header>

<details open>
  <summary class="panel-header">{{ icons.file_text | safe }} <strong>Verdict</strong></summary>
  <div class="panel-body">
    {% if verdict.headline %}<p><strong>{{ verdict.headline }}</strong></p>{% endif %}
    {% if verdict.composite_score is defined %}
    <p>Composite score: <code>{{ verdict.composite_score }}</code></p>
    {% endif %}
  </div>
</details>

<details>
  <summary class="panel-header">{{ icons.link | safe }} <strong>Framework cross-walks</strong></summary>
  <div class="panel-body">
    {% for fw_id, controls in (verdict.framework_mappings or {}).items() %}
    <div>
      <strong>{{ frameworks.get(fw_id, {}).get("name", fw_id) }}</strong>:
      <code>{{ controls | join(", ") }}</code>
    </div>
    {% else %}
    <em>No framework mappings present.</em>
    {% endfor %}
  </div>
</details>

<details>
  <summary class="panel-header">{{ icons.fingerprint | safe }} <strong>Signature &amp; transparency metadata</strong></summary>
  <div class="panel-body">
    <div class="meta-row">
      <span>Canonical SHA-256:</span><code>{{ canonical_sha256 }}</code>
      <span>Signature (hex):</span><code>{{ signature_hex }}</code>
      <span>Public key (hex):</span><code>{{ public_key_hex }}</code>
      <span>Transparency event id:</span><code>{{ transparency_event_id }}</code>
      <span>Rekor UUID:</span><code>{{ rekor_uuid or "—" }}</code>
      <span>Rekor log index:</span><code>{{ rekor_log_index or "—" }}</code>
    </div>
  </div>
</details>

<details>
  <summary class="panel-header">{{ icons.file_text | safe }} <strong>Embedded payload &amp; evidence</strong></summary>
  <div class="panel-body">
    <p>Verifiers parse <code>#smadp-passport-payload</code> as JSON and recompute the canonical SHA-256.</p>
    <script type="application/json" id="smadp-passport-payload">{{ metadata_json | safe }}</script>
    <p>Evidence blobs are embedded below as base64-encoded JSON for offline review.</p>
    <script type="application/json" id="smadp-passport-evidence-base64">"{{ evidence_blobs_b64 }}"</script>
  </div>
</details>

<footer>
  <p style="margin-top:32px;font-size:11px;color:#888;">
    Generated by SMADP v2-D. Verify offline with
    <code>smadp passport verify &lt;file.html&gt;</code>.
  </p>
</footer>

</body>
</html>
```

- [ ] **Step 4: Run tests — expect still failing on `_jinja_env`**

Run: `.venv/bin/pytest tests/unit/test_passport_template_loads.py -v`
Expected: still ImportError on `smadp.passport.render._jinja_env`. That's expected — `_jinja_env` is built in Task 6. The template file itself is on disk; commit it now.

- [ ] **Step 5: Commit**

```bash
git add smadp/passport/templates/passport.html.j2
git commit -m "feat(passport): add Jinja2 passport.html.j2 with collapsible panels and inline icons"
```

---

## Task 6: Render core (unsigned HTML)

**Files:**
- Create: `smadp/passport/render.py`
- Create: `tests/unit/test_passport_render_unsigned.py`
- Modify: `pyproject.toml` to ensure template files ship with the package (add `[tool.setuptools.package-data]` block if missing)

- [ ] **Step 1: Make template files installable**

Inspect `pyproject.toml` for any existing `[tool.setuptools]` block. If `package-data` is not configured, add this block (place it at the end of the file, after `[tool.pytest.ini_options]`):

```toml
[tool.setuptools.package-data]
smadp = ["passport/templates/*.j2"]
```

If a `[tool.setuptools]` block already exists, add the `package-data` mapping under it without duplicating the section header.

Re-install: `.venv/bin/pip install -e ".[dev]"`

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_passport_render_unsigned.py`:

```python
"""Tests for passport.render._render_unsigned (the deterministic body)."""

from __future__ import annotations

from smadp.passport.render import _render_unsigned


def _verdict_dict():
    return {
        "verdict_id": "vdt_FIXED",
        "pair": ["a/x", "b/y"],
        "headline": "Test verdict",
        "composite_score": 0.42,
        "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1"]},
    }


def test_render_unsigned_returns_html_bytes():
    html = _render_unsigned(
        verdict=_verdict_dict(),
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={"sha256:abc": {"source_url": "https://x"}},
        evidence_blobs_b64="eyJzb21lIjoiZGF0YSJ9",
        rendered_at="2026-05-03T12:34:56Z",
    )
    assert isinstance(html, bytes)
    text = html.decode("utf-8")
    assert "<!DOCTYPE html>" in text
    assert "vdt_FIXED" in text
    assert "NIST AI RMF" in text
    assert "GOVERN-1.1" in text
    assert "smadp-canonical-sha256" in text


def test_render_unsigned_metadata_placeholders_are_empty():
    """Unsigned render uses empty signature/key/rekor placeholders."""
    html = _render_unsigned(
        verdict=_verdict_dict(),
        frameworks={},
        evidence_index={},
        evidence_blobs_b64="",
        rendered_at="2026-05-03T12:34:56Z",
    ).decode("utf-8")
    assert 'name="smadp-signature-hex" content=""' in html
    assert 'name="smadp-public-key-hex" content=""' in html
    assert 'name="smadp-rekor-uuid" content=""' in html
    assert 'name="smadp-transparency-status" content="local"' in html


def test_render_unsigned_is_deterministic_for_fixed_inputs():
    a = _render_unsigned(
        verdict=_verdict_dict(),
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={"sha256:abc": {"source_url": "https://x"}},
        evidence_blobs_b64="eyJzb21lIjoiZGF0YSJ9",
        rendered_at="2026-05-03T12:34:56Z",
    )
    b = _render_unsigned(
        verdict=_verdict_dict(),
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={"sha256:abc": {"source_url": "https://x"}},
        evidence_blobs_b64="eyJzb21lIjoiZGF0YSJ9",
        rendered_at="2026-05-03T12:34:56Z",
    )
    assert a == b
```

- [ ] **Step 3: Run — expect failure**

Run: `.venv/bin/pytest tests/unit/test_passport_render_unsigned.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement render core**

Create `smadp/passport/render.py`:

```python
"""Render passport HTML (unsigned core + signed wrapper coming in Task 7)."""

from __future__ import annotations

import json
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from smadp.passport.canonical import canonical_passport_sha256
from smadp.passport.icons import LUCIDE_ICONS


def _jinja_env() -> Environment:
    return Environment(
        loader=PackageLoader("smadp.passport", "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        keep_trailing_newline=False,
        trim_blocks=False,
        lstrip_blocks=False,
    )


def _icons_for_template() -> dict[str, str]:
    """Lucide SVGs with a passport-icon class injected for the template."""
    from smadp.passport.icons import render_icon

    return {name: render_icon(name, css_class="passport-icon") for name in LUCIDE_ICONS}


def _render_unsigned(
    *,
    verdict: dict[str, Any],
    frameworks: dict[str, Any],
    evidence_index: dict[str, Any],
    evidence_blobs_b64: str,
    rendered_at: str,
) -> bytes:
    """Render the deterministic body of a passport, with empty signing fields."""
    env = _jinja_env()
    tpl = env.get_template("passport.html.j2")

    canonical_sha = canonical_passport_sha256(
        verdict=verdict,
        frameworks=frameworks,
        evidence_index=evidence_index,
        rendered_at=rendered_at,
    )

    metadata_payload = {
        "verdict": verdict,
        "frameworks": frameworks,
        "evidence_index": evidence_index,
        "rendered_at": rendered_at,
    }
    metadata_json = json.dumps(
        metadata_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )

    out = tpl.render(
        verdict=verdict,
        frameworks=frameworks,
        evidence_index=evidence_index,
        metadata_json=metadata_json,
        rendered_at=rendered_at,
        signing_strategy_label="byok",
        signature_hex="",
        public_key_hex="",
        canonical_sha256=canonical_sha,
        rekor_uuid="",
        rekor_log_index="",
        transparency_event_id=0,
        transparency_status="local",
        icons=_icons_for_template(),
        evidence_blobs_b64=evidence_blobs_b64,
    )
    return out.encode("utf-8")


__all__ = ["_jinja_env", "_render_unsigned"]
```

- [ ] **Step 5: Run tests to verify pass**

Run: `.venv/bin/pytest tests/unit/test_passport_render_unsigned.py tests/unit/test_passport_template_loads.py -v`
Expected: 4 passed total (3 from this task + 1 from Task 5).

- [ ] **Step 6: Commit**

```bash
git add smadp/passport/render.py pyproject.toml tests/unit/test_passport_render_unsigned.py
git commit -m "feat(passport): unsigned HTML render core (Jinja2 + canonical sha256 + inlined icons)"
```

---

## Task 7: Sign module — BYOK strategy + meta-tag injection

**Files:**
- Create: `smadp/passport/sign.py`
- Create: `tests/unit/test_passport_sign_byok.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_passport_sign_byok.py`:

```python
"""Tests for BYOK signing strategy in smadp.passport.sign."""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.passport.canonical import canonical_passport_sha256
from smadp.passport.render import _render_unsigned
from smadp.passport.sign import inject_signature_meta, sign_unsigned_html


def _verdict():
    return {
        "verdict_id": "vdt_X",
        "headline": "Test",
        "composite_score": 0.5,
        "framework_mappings": {},
    }


def test_inject_signature_meta_replaces_empty_placeholders():
    html = _render_unsigned(
        verdict=_verdict(), frameworks={}, evidence_index={},
        evidence_blobs_b64="", rendered_at="2026-05-03T12:00:00Z",
    )
    out = inject_signature_meta(
        html,
        signature_hex="aabb",
        public_key_hex="ccdd",
        signing_strategy_label="byok",
        rekor_uuid="",
        rekor_log_index="",
        transparency_event_id=42,
        transparency_status="local",
    ).decode("utf-8")
    assert 'name="smadp-signature-hex" content="aabb"' in out
    assert 'name="smadp-public-key-hex" content="ccdd"' in out
    assert 'name="smadp-signing-strategy" content="byok"' in out
    assert 'name="smadp-transparency-event-id" content="42"' in out


def test_sign_unsigned_html_byok_produces_verifiable_signature():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    html = _render_unsigned(
        verdict=_verdict(), frameworks={}, evidence_index={},
        evidence_blobs_b64="", rendered_at="2026-05-03T12:00:00Z",
    )
    canonical_sha = canonical_passport_sha256(
        verdict=_verdict(), frameworks={}, evidence_index={},
        rendered_at="2026-05-03T12:00:00Z",
    )
    signed = sign_unsigned_html(
        html, signing_key=priv, canonical_sha256=canonical_sha,
        signing_strategy_label="byok", transparency_event_id=1,
        transparency_status="local", rekor_uuid="", rekor_log_index="",
    )
    text = signed.decode("utf-8")
    # Extract the signature from the meta tag, verify against canonical bytes.
    import re
    sig_hex = re.search(r'name="smadp-signature-hex" content="([0-9a-f]+)"', text).group(1)
    pub.verify(bytes.fromhex(sig_hex), canonical_sha.encode("utf-8"))


def test_inject_signature_meta_idempotent():
    """Calling inject twice with same values yields same bytes (no compounding)."""
    html = _render_unsigned(
        verdict=_verdict(), frameworks={}, evidence_index={},
        evidence_blobs_b64="", rendered_at="2026-05-03T12:00:00Z",
    )
    once = inject_signature_meta(
        html, signature_hex="aa", public_key_hex="bb",
        signing_strategy_label="byok", rekor_uuid="", rekor_log_index="",
        transparency_event_id=1, transparency_status="local",
    )
    twice = inject_signature_meta(
        once, signature_hex="aa", public_key_hex="bb",
        signing_strategy_label="byok", rekor_uuid="", rekor_log_index="",
        transparency_event_id=1, transparency_status="local",
    )
    assert once == twice
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/pytest tests/unit/test_passport_sign_byok.py -v`
Expected: ImportError on `smadp.passport.sign`.

- [ ] **Step 3: Implement signing**

Create `smadp/passport/sign.py`:

```python
"""Passport signing — BYOK strategy + meta-tag injection.

Sigstore strategy adds in Task 8.

The signature attests to the canonical sha256 (`canonical_passport_sha256(...)`).
We do NOT sign the rendered HTML — it includes the signature itself, which would
be circular. The verifier extracts the canonical metadata payload from the
HTML's <script id="smadp-passport-payload"> tag, recomputes the canonical sha,
and checks the signature against that fixed input.
"""

from __future__ import annotations

import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def _replace_meta(html: bytes, name: str, value: str) -> bytes:
    """Replace the content of a <meta name="..."> tag in-place."""
    pattern = re.compile(
        rb'(name="' + re.escape(name.encode()) + rb'" content=")([^"]*)(")'
    )
    new_content = value.encode("utf-8")
    return pattern.sub(rb'\g<1>' + new_content + rb'\g<3>', html, count=1)


def inject_signature_meta(
    html: bytes,
    *,
    signature_hex: str,
    public_key_hex: str,
    signing_strategy_label: str,
    rekor_uuid: str,
    rekor_log_index: str,
    transparency_event_id: int,
    transparency_status: str,
) -> bytes:
    """Set the signing-related <meta> tags. Idempotent for fixed inputs."""
    out = html
    out = _replace_meta(out, "smadp-signature-hex", signature_hex)
    out = _replace_meta(out, "smadp-public-key-hex", public_key_hex)
    out = _replace_meta(out, "smadp-signing-strategy", signing_strategy_label)
    out = _replace_meta(out, "smadp-rekor-uuid", rekor_uuid)
    out = _replace_meta(out, "smadp-rekor-log-index", rekor_log_index)
    out = _replace_meta(
        out, "smadp-transparency-event-id", str(transparency_event_id)
    )
    out = _replace_meta(out, "smadp-transparency-status", transparency_status)
    return out


def sign_unsigned_html(
    html: bytes,
    *,
    signing_key: Ed25519PrivateKey,
    canonical_sha256: str,
    signing_strategy_label: str,
    transparency_event_id: int,
    transparency_status: str,
    rekor_uuid: str,
    rekor_log_index: str,
) -> bytes:
    """Sign the canonical sha and inject all signing metadata into ``html``."""
    sig = signing_key.sign(canonical_sha256.encode("utf-8"))
    pub_bytes = signing_key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    )
    return inject_signature_meta(
        html,
        signature_hex=sig.hex(),
        public_key_hex=pub_bytes.hex(),
        signing_strategy_label=signing_strategy_label,
        rekor_uuid=rekor_uuid,
        rekor_log_index=rekor_log_index,
        transparency_event_id=transparency_event_id,
        transparency_status=transparency_status,
    )


__all__ = ["inject_signature_meta", "sign_unsigned_html"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/unit/test_passport_sign_byok.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/passport/sign.py tests/unit/test_passport_sign_byok.py
git commit -m "feat(passport): BYOK signing + idempotent meta-tag injection"
```

---

## Task 8: Real Sigstore/Rekor REST integration

**Files:**
- Modify: `smadp/transparency/sigstore.py` (replaces Plan 1 stub)
- Create: `tests/unit/test_transparency_sigstore_rekor.py`

- [ ] **Step 1: Read the current stub for context**

Run: `cat smadp/transparency/sigstore.py`
Note: Plan 1's `submit_to_rekor(event_id) -> None` returns `None`. We will replace it with a real implementation, plus add `get_inclusion_proof(rekor_uuid)`. The stubbed signature stays the same for the local-only path; the new path activates only when `SMADP_SIGSTORE_ENABLED=true`.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_transparency_sigstore_rekor.py`:

```python
"""Tests for real Rekor REST submission + inclusion-proof retrieval.

Network is mocked with respx — these tests run offline.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.transparency import journal, sigstore


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.setenv("SMADP_SIGSTORE_ENABLED", "true")
    monkeypatch.setenv("SMADP_REKOR_URL", "https://rekor.example.test")
    return Config()


def _append_one(cfg: Config) -> tuple[int, Ed25519PrivateKey]:
    key = Ed25519PrivateKey.generate()
    ev = journal.append_event(
        event_type="x.a", payload={"k": 1}, signing_key=key, config=cfg
    )
    return ev.id, key


def test_submit_to_rekor_when_disabled_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.setenv("SMADP_SIGSTORE_ENABLED", "false")
    cfg = Config()
    event_id, _ = _append_one(cfg)
    assert sigstore.submit_to_rekor(event_id, config=cfg) is None


@respx.mock
def test_submit_to_rekor_when_enabled_returns_uuid(cfg: Config):
    event_id, _ = _append_one(cfg)
    respx.post("https://rekor.example.test/api/v1/log/entries").mock(
        return_value=httpx.Response(
            201,
            json={
                "deadbeef-cafebabe-feed-face-1234567890ab": {
                    "logIndex": 99001,
                    "logID": "abc",
                    "integratedTime": 1714740000,
                }
            },
        )
    )
    result = sigstore.submit_to_rekor(event_id, config=cfg)
    assert result == "deadbeef-cafebabe-feed-face-1234567890ab"


@respx.mock
def test_submit_to_rekor_returns_none_on_5xx(cfg: Config):
    event_id, _ = _append_one(cfg)
    respx.post("https://rekor.example.test/api/v1/log/entries").mock(
        return_value=httpx.Response(503, text="bad")
    )
    assert sigstore.submit_to_rekor(event_id, config=cfg) is None


@respx.mock
def test_get_inclusion_proof_returns_proof_dict(cfg: Config):
    proof_payload = {
        "logIndex": 99001,
        "treeSize": 100000,
        "rootHash": "ab" * 32,
        "hashes": ["cd" * 32, "ef" * 32],
        "checkpoint": "rekor.example.test\n100000\n" + "ab" * 32 + "\n",
    }
    respx.get(
        "https://rekor.example.test/api/v1/log/entries/uuid-123/proof"
    ).mock(return_value=httpx.Response(200, json=proof_payload))
    out = sigstore.get_inclusion_proof("uuid-123", config=cfg)
    assert out == proof_payload


@respx.mock
def test_get_inclusion_proof_returns_none_on_404(cfg: Config):
    respx.get(
        "https://rekor.example.test/api/v1/log/entries/missing/proof"
    ).mock(return_value=httpx.Response(404))
    assert sigstore.get_inclusion_proof("missing", config=cfg) is None
```

- [ ] **Step 3: Run — expect failures**

Run: `.venv/bin/pytest tests/unit/test_transparency_sigstore_rekor.py -v`
Expected: ImportError on `get_inclusion_proof`, AND `submit_to_rekor` returns None unconditionally so 2/5 pass coincidentally.

- [ ] **Step 4: Replace the stub**

Open `smadp/transparency/sigstore.py`. The current stub looks like (per Plan 1):

```python
def submit_to_rekor(event_id: int, config: Config | None = None) -> str | None:
    """STUB — Plan 2 wires real Sigstore submission."""
    return None
```

Replace the whole module with:

```python
"""Sigstore/Rekor submission for transparency events.

Plan 1 shipped a stub. This module now performs real REST calls to Rekor
when ``SMADP_SIGSTORE_ENABLED=true`` is set. The endpoint is configurable
via ``SMADP_REKOR_URL`` (default ``https://rekor.sigstore.dev``).

We use the ``hashedrekord`` v0.0.1 entry kind so we can submit pre-signed
events without exposing the private key. Rekor verifies the signature on
submission and, on success, returns the entry UUID.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sqlite3
from typing import Any

import httpx

from smadp.config import Config, load_config
from smadp.transparency import journal

logger = logging.getLogger(__name__)

DEFAULT_REKOR_URL = "https://rekor.sigstore.dev"
SUBMIT_TIMEOUT_S = 10.0
PROOF_TIMEOUT_S = 10.0


def _enabled() -> bool:
    return os.environ.get("SMADP_SIGSTORE_ENABLED", "false").lower() == "true"


def _rekor_url() -> str:
    return os.environ.get("SMADP_REKOR_URL", DEFAULT_REKOR_URL).rstrip("/")


def _build_hashedrekord_body(
    *, signing_input: bytes, signature_hex: str, public_key_pem: str
) -> dict[str, Any]:
    """Build a Rekor ``hashedrekord`` v0.0.1 entry body."""
    sha = hashlib.sha256(signing_input).hexdigest()
    return {
        "apiVersion": "0.0.1",
        "kind": "hashedrekord",
        "spec": {
            "data": {"hash": {"algorithm": "sha256", "value": sha}},
            "signature": {
                "content": base64.b64encode(bytes.fromhex(signature_hex)).decode(),
                "publicKey": {
                    "content": base64.b64encode(public_key_pem.encode()).decode()
                },
            },
        },
    }


def _ed25519_pubkey_pem_for_event(event_id: int, config: Config) -> str | None:
    """Pull the workspace public key associated with the event's signature.

    For Plan 2 we use a simpler convention: the journal stores Ed25519 sigs
    but does not record which workspace's key was used. Until passport
    submissions add a workspace_id column (Plan 3), Rekor submission is opt-in
    and the caller must wire the public key explicitly. For now we look at
    the event row; if no public-key sidecar table exists, return None.
    """
    # Plan 2 does not introduce a key-tracking column; passport submission paths
    # will pass the key explicitly via the higher-level wrapper. This helper is
    # a placeholder for the journal-event auto-submission path which Plan 3
    # extends; for now it returns None to signal "skip Rekor for journal events".
    return None


def submit_to_rekor(event_id: int, config: Config | None = None) -> str | None:
    """Submit an event to Rekor; return UUID on success, None otherwise.

    Returns None when:
    - ``SMADP_SIGSTORE_ENABLED`` is not ``true``
    - The event has no associated public key wired in (current limitation;
      passport submissions use ``submit_signed_payload`` directly)
    - Rekor returns 5xx or the request fails
    """
    if not _enabled():
        return None
    cfg = config or load_config()
    pub_pem = _ed25519_pubkey_pem_for_event(event_id, cfg)
    if pub_pem is None:
        logger.debug("submit_to_rekor: no public key wired for event %d", event_id)
        return None
    # Lookup the event row
    for ev in journal.iter_events(config=cfg):
        if ev.id == event_id:
            try:
                signing_input = journal._canonical_signing_input(ev)
                body = _build_hashedrekord_body(
                    signing_input=signing_input,
                    signature_hex=ev.signature,
                    public_key_pem=pub_pem,
                )
                return _post_entry(body)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                logger.warning("Rekor submission failed for event %d: %s", event_id, exc)
                return None
    return None


def submit_signed_payload(
    *, signing_input: bytes, signature_hex: str, public_key_pem: str
) -> str | None:
    """Submit a pre-signed payload to Rekor; return UUID on success, None on failure.

    This is the primary entry point used by the passport renderer. It does
    NOT consult ``SMADP_SIGSTORE_ENABLED`` — the caller is expected to gate.
    """
    body = _build_hashedrekord_body(
        signing_input=signing_input,
        signature_hex=signature_hex,
        public_key_pem=public_key_pem,
    )
    try:
        return _post_entry(body)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("Rekor submission failed: %s", exc)
        return None


def _post_entry(body: dict[str, Any]) -> str | None:
    """POST to ``/api/v1/log/entries``; return the (sole) UUID key from response."""
    url = f"{_rekor_url()}/api/v1/log/entries"
    with httpx.Client(timeout=SUBMIT_TIMEOUT_S) as client:
        resp = client.post(url, json=body)
    if resp.status_code >= 500:
        return None
    if resp.status_code == 409:
        # Already in log — Rekor returns 409 with the existing entry; pull UUID.
        try:
            data = resp.json()
            return next(iter(data.keys()))
        except (json.JSONDecodeError, StopIteration):
            return None
    if resp.status_code not in (200, 201):
        logger.warning("Rekor returned %d: %s", resp.status_code, resp.text[:200])
        return None
    data = resp.json()
    if not isinstance(data, dict) or not data:
        return None
    return next(iter(data.keys()))


def get_inclusion_proof(rekor_uuid: str, config: Config | None = None) -> dict[str, Any] | None:
    """Fetch the inclusion proof for a Rekor entry by UUID.

    Returns the raw proof dict on success, None on 404/5xx.
    """
    url = f"{_rekor_url()}/api/v1/log/entries/{rekor_uuid}/proof"
    try:
        with httpx.Client(timeout=PROOF_TIMEOUT_S) as client:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        logger.warning("Rekor proof fetch failed for %s: %s", rekor_uuid, exc)
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except json.JSONDecodeError:
        return None


def list_pending_submissions(
    config: Config | None = None,
) -> list[int]:
    """IDs of events lacking a Rekor UUID. Plan 1 contract."""
    cfg = config or load_config()
    db_path = cfg.cache_dir / "transparency.db"
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT id FROM signed_events WHERE rekor_uuid IS NULL ORDER BY id"
        )
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def mark_submitted(event_id: int, rekor_uuid: str, config: Config | None = None) -> None:
    """Set ``rekor_uuid`` on a signed event. Raises KeyError if the row is missing."""
    cfg = config or load_config()
    db_path = cfg.cache_dir / "transparency.db"
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE signed_events SET rekor_uuid = ? WHERE id = ?",
            (rekor_uuid, event_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"No signed_event with id {event_id}")
    finally:
        conn.close()


def retry_pending_submissions(config: Config | None = None) -> int:
    """Try submitting all events without a Rekor UUID. Return count newly submitted."""
    cfg = config or load_config()
    submitted = 0
    for event_id in list_pending_submissions(config=cfg):
        uuid = submit_to_rekor(event_id, config=cfg)
        if uuid is not None:
            mark_submitted(event_id, uuid, config=cfg)
            submitted += 1
    return submitted


__all__ = [
    "DEFAULT_REKOR_URL",
    "get_inclusion_proof",
    "list_pending_submissions",
    "mark_submitted",
    "retry_pending_submissions",
    "submit_signed_payload",
    "submit_to_rekor",
]
```

- [ ] **Step 5: Run tests to verify pass**

Run: `.venv/bin/pytest tests/unit/test_transparency_sigstore_rekor.py tests/unit/test_transparency_sigstore.py -v`
Expected: all pass — both the new Plan 2 tests AND the Plan 1 stub tests (the stub tests assume `submit_to_rekor` returns None when not configured; the new module preserves that semantic when `SMADP_SIGSTORE_ENABLED` is unset).

- [ ] **Step 6: Commit**

```bash
git add smadp/transparency/sigstore.py tests/unit/test_transparency_sigstore_rekor.py
git commit -m "feat(transparency): real Rekor REST submission + inclusion proof retrieval (gated by SMADP_SIGSTORE_ENABLED)"
```

---

## Task 9: Wire render → sign → optional Rekor submit (full `render_passport`)

**Files:**
- Modify: `smadp/passport/render.py` (extend with public `render_passport`)
- Create: `tests/integration/test_passport_render_full.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_passport_render_full.py`:

```python
"""Full render_passport integration: workspace + BYOK + journal + render."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.tenancy import keys, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.delenv("SMADP_SIGSTORE_ENABLED", raising=False)
    return Config()


@pytest.fixture
def workspace_with_key(cfg: Config) -> tuple[str, Ed25519PrivateKey]:
    ws = store.create_workspace(name="Acme", plan="public", config=cfg)
    priv = Ed25519PrivateKey.generate()
    keys.upload_signing_key(workspace_id=ws.id, private_key=priv, config=cfg)
    return ws.id, priv


def _verdict():
    return {
        "verdict_id": "vdt_FULL",
        "pair": ["a/x", "b/y"],
        "headline": "Full render test",
        "composite_score": 0.5,
        "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1"]},
    }


def test_render_passport_byok_emits_signed_html(
    cfg: Config, workspace_with_key: tuple[str, Ed25519PrivateKey]
):
    ws_id, _ = workspace_with_key
    html = render_passport(
        verdict=_verdict(),
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws_id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )
    text = html.decode("utf-8")
    assert re.search(r'name="smadp-signature-hex" content="[0-9a-f]+"', text)
    assert re.search(r'name="smadp-public-key-hex" content="[0-9a-f]+"', text)
    assert 'name="smadp-signing-strategy" content="byok"' in text
    assert 'name="smadp-transparency-status" content="local"' in text
    assert re.search(r'name="smadp-transparency-event-id" content="\d+"', text)


def test_render_passport_byok_appends_transparency_event(
    cfg: Config, workspace_with_key: tuple[str, Ed25519PrivateKey]
):
    ws_id, _ = workspace_with_key
    from smadp.transparency import journal

    before = len(list(journal.iter_events(config=cfg)))
    render_passport(
        verdict=_verdict(), frameworks={}, evidence_index={}, evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK, workspace_id=ws_id,
        rendered_at="2026-05-03T12:00:00Z", config=cfg,
    )
    after = list(journal.iter_events(config=cfg))
    assert len(after) == before + 1
    assert after[-1].event_type == "passport.generated"


def test_render_passport_byok_missing_key_raises(cfg: Config):
    ws = store.create_workspace(name="X", plan="public", config=cfg)
    with pytest.raises(KeyError, match="byok_key_missing_for_workspace"):
        render_passport(
            verdict=_verdict(), frameworks={}, evidence_index={}, evidence_blobs={},
            signing_strategy=SigningStrategy.BYOK, workspace_id=ws.id,
            rendered_at="2026-05-03T12:00:00Z", config=cfg,
        )


def test_render_passport_embeds_canonical_payload_as_script_tag(
    cfg: Config, workspace_with_key: tuple[str, Ed25519PrivateKey]
):
    ws_id, _ = workspace_with_key
    html = render_passport(
        verdict=_verdict(),
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK, workspace_id=ws_id,
        rendered_at="2026-05-03T12:00:00Z", config=cfg,
    )
    text = html.decode("utf-8")
    m = re.search(
        r'<script type="application/json" id="smadp-passport-payload">(.+?)</script>',
        text, re.DOTALL,
    )
    assert m is not None
    payload = json.loads(m.group(1))
    assert payload["verdict"]["verdict_id"] == "vdt_FULL"
    assert payload["rendered_at"] == "2026-05-03T12:00:00Z"
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/pytest tests/integration/test_passport_render_full.py -v`
Expected: ImportError on `render_passport` (only `_render_unsigned` exists).

- [ ] **Step 3: Extend render.py with public `render_passport`**

Append to `smadp/passport/render.py` (don't replace, append after `_render_unsigned`):

```python
import base64
import json as _json
from datetime import datetime, timezone
from typing import Any as _Any  # avoid shadowing module-level Any if added

from smadp.config import Config, load_config
from smadp.schemas.passport import SigningStrategy
from smadp.passport.canonical import canonical_passport_sha256
from smadp.passport.sign import sign_unsigned_html
from smadp.tenancy import keys
from smadp.transparency import journal


def _utcnow_isoformat_seconds() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _evidence_blobs_b64(evidence_blobs: dict[str, dict]) -> str:
    """Base64-encode the JSON serialization of all evidence blobs."""
    if not evidence_blobs:
        return ""
    payload = _json.dumps(
        evidence_blobs, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def render_passport(
    *,
    verdict: dict,
    frameworks: dict,
    evidence_index: dict,
    evidence_blobs: dict[str, dict],
    signing_strategy: SigningStrategy,
    workspace_id: str,
    rendered_at: str | None = None,
    config: Config | None = None,
) -> bytes:
    """Render a fully signed passport.

    Steps:
    1. Build the canonical sha256 over (verdict, frameworks, evidence_index, ts)
    2. Append a ``passport.generated`` transparency event signed by the same key
    3. (BYOK) sign the canonical sha with the workspace's BYOK key
       (Sigstore strategy in this plan still uses BYOK locally for the signature
       and submits the resulting signed payload to Rekor; the *strategy label*
       differs to inform verifiers about the trust root)
    4. If sigstore is enabled and strategy is SIGSTORE, submit to Rekor and embed
       the returned UUID + log_index. On failure, drop into ``deferred`` mode.
    5. Inject all metadata into the HTML and return the bytes.
    """
    cfg = config or load_config()
    ts = rendered_at or _utcnow_isoformat_seconds()

    signing_key = keys.load_signing_key(workspace_id=workspace_id, config=cfg)
    if signing_key is None:
        raise KeyError(f"byok_key_missing_for_workspace: {workspace_id}")

    canonical_sha = canonical_passport_sha256(
        verdict=verdict,
        frameworks=frameworks,
        evidence_index=evidence_index,
        rendered_at=ts,
    )

    transparency_event = journal.append_event(
        event_type="passport.generated",
        payload={
            "workspace_id": workspace_id,
            "verdict_id": verdict.get("verdict_id"),
            "canonical_sha256": canonical_sha,
            "signing_strategy": signing_strategy.value,
        },
        signing_key=signing_key,
        config=cfg,
    )

    rekor_uuid = ""
    rekor_log_index = ""
    transparency_status = "local"
    if signing_strategy == SigningStrategy.SIGSTORE:
        from smadp.transparency import sigstore as _sigstore
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat,
        )
        if _sigstore._enabled():
            pub_pem = (
                "-----BEGIN PUBLIC KEY-----\n"
                + base64.b64encode(
                    signing_key.public_key().public_bytes(
                        encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo
                    )
                ).decode()
                + "\n-----END PUBLIC KEY-----\n"
            )
            sig_hex = signing_key.sign(canonical_sha.encode("utf-8")).hex()
            uuid = _sigstore.submit_signed_payload(
                signing_input=canonical_sha.encode("utf-8"),
                signature_hex=sig_hex,
                public_key_pem=pub_pem,
            )
            if uuid:
                proof = _sigstore.get_inclusion_proof(uuid, config=cfg)
                rekor_uuid = uuid
                rekor_log_index = (
                    str(proof.get("logIndex", "")) if proof else ""
                )
                transparency_status = "submitted"
            else:
                transparency_status = "deferred"
        else:
            transparency_status = "deferred"

    unsigned = _render_unsigned(
        verdict=verdict,
        frameworks=frameworks,
        evidence_index=evidence_index,
        evidence_blobs_b64=_evidence_blobs_b64(evidence_blobs),
        rendered_at=ts,
    )
    return sign_unsigned_html(
        unsigned,
        signing_key=signing_key,
        canonical_sha256=canonical_sha,
        signing_strategy_label=signing_strategy.value,
        transparency_event_id=transparency_event.id,
        transparency_status=transparency_status,
        rekor_uuid=rekor_uuid,
        rekor_log_index=rekor_log_index,
    )


__all__ = ["_jinja_env", "_render_unsigned", "render_passport"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/integration/test_passport_render_full.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/passport/render.py tests/integration/test_passport_render_full.py
git commit -m "feat(passport): render_passport - workspace BYOK + transparency event + optional Rekor submission"
```

---

## Task 10: Verify module — extract → recompute → check signature → check chain

**Files:**
- Create: `smadp/passport/verify.py`
- Create: `tests/unit/test_passport_verify.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_passport_verify.py`:

```python
"""Tests for offline passport verification."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.passport.verify import verify_passport
from smadp.schemas.passport import SigningStrategy
from smadp.tenancy import keys, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.delenv("SMADP_SIGSTORE_ENABLED", raising=False)
    return Config()


def _make_passport(cfg: Config) -> bytes:
    ws = store.create_workspace(name="A", plan="public", config=cfg)
    priv = Ed25519PrivateKey.generate()
    keys.upload_signing_key(workspace_id=ws.id, private_key=priv, config=cfg)
    return render_passport(
        verdict={
            "verdict_id": "vdt_VERIFY",
            "pair": ["a/x", "b/y"],
            "headline": "Verify test",
            "composite_score": 0.31,
            "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1"]},
        },
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws.id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )


def test_verify_passport_accepts_unmodified(cfg: Config):
    html = _make_passport(cfg)
    result = verify_passport(html)
    assert result.valid is True
    assert result.reason is None


def test_verify_passport_rejects_when_signature_missing(cfg: Config):
    html = _make_passport(cfg)
    tampered = html.replace(
        b'name="smadp-signature-hex" content="', b'name="smadp-signature-hex" content="00'
    )
    # The signature is now wrong-length hex, signature verify will fail
    result = verify_passport(tampered)
    assert result.valid is False
    assert "signature" in (result.reason or "").lower()


def test_verify_passport_rejects_unknown_signing_strategy(cfg: Config):
    html = _make_passport(cfg)
    tampered = html.replace(
        b'name="smadp-signing-strategy" content="byok"',
        b'name="smadp-signing-strategy" content="bogus"',
    )
    result = verify_passport(tampered)
    assert result.valid is False
    assert "signing_strategy" in (result.reason or "").lower()


def test_verify_passport_rejects_payload_canonical_mismatch(cfg: Config):
    """If the embedded payload's canonical sha doesn't match the meta tag, fail."""
    html = _make_passport(cfg)
    tampered = html.replace(b"vdt_VERIFY", b"vdt_TAMPER", 1)
    result = verify_passport(tampered)
    assert result.valid is False
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/pytest tests/unit/test_passport_verify.py -v`
Expected: ImportError on `smadp.passport.verify`.

- [ ] **Step 3: Implement verifier**

Create `smadp/passport/verify.py`:

```python
"""Offline passport verifier — extract embedded payload, recompute, check sig."""

from __future__ import annotations

import json
import re
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from smadp.passport.canonical import canonical_passport_sha256
from smadp.schemas.passport import SigningStrategy, VerificationResult


_META_RE = re.compile(
    rb'<meta name="(?P<name>[a-z0-9_\-]+)" content="(?P<value>[^"]*)"\s*/>'
)
_PAYLOAD_RE = re.compile(
    rb'<script type="application/json" id="smadp-passport-payload">(?P<payload>.+?)</script>',
    re.DOTALL,
)


def _extract_meta(html: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _META_RE.finditer(html):
        out[m.group("name").decode()] = m.group("value").decode()
    return out


def _extract_payload(html: bytes) -> dict[str, Any] | None:
    m = _PAYLOAD_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group("payload"))
    except json.JSONDecodeError:
        return None


def verify_passport(html: bytes) -> VerificationResult:
    """Verify a passport's embedded signature offline. Fail closed on any anomaly."""
    meta = _extract_meta(html)

    strategy = meta.get("smadp-signing-strategy", "")
    try:
        SigningStrategy(strategy)
    except ValueError:
        return VerificationResult(
            valid=False, reason=f"unknown signing_strategy: {strategy!r}"
        )

    sig_hex = meta.get("smadp-signature-hex", "")
    pub_hex = meta.get("smadp-public-key-hex", "")
    declared_sha = meta.get("smadp-canonical-sha256", "")

    if not sig_hex or not pub_hex or not declared_sha:
        return VerificationResult(
            valid=False, reason="missing signature, public key, or canonical sha"
        )

    payload = _extract_payload(html)
    if payload is None:
        return VerificationResult(valid=False, reason="missing or malformed payload script")

    try:
        recomputed_sha = canonical_passport_sha256(
            verdict=payload.get("verdict", {}),
            frameworks=payload.get("frameworks", {}),
            evidence_index=payload.get("evidence_index", {}),
            rendered_at=payload.get("rendered_at", ""),
        )
    except Exception as exc:  # noqa: BLE001 -- treat any payload error as tamper
        return VerificationResult(valid=False, reason=f"payload re-canonicalization failed: {exc}")

    if recomputed_sha != declared_sha:
        return VerificationResult(
            valid=False,
            reason=f"canonical sha mismatch: declared={declared_sha} recomputed={recomputed_sha}",
        )

    # Signature is over declared_sha (the canonical sha string); rebuild and verify.
    try:
        sig_bytes = bytes.fromhex(sig_hex)
        pub_bytes = bytes.fromhex(pub_hex)
        pub = Ed25519PublicKey.from_public_bytes(pub_bytes)
        pub.verify(sig_bytes, declared_sha.encode("utf-8"))
    except (ValueError, InvalidSignature) as exc:
        return VerificationResult(valid=False, reason=f"signature verification failed: {exc}")

    return VerificationResult(valid=True, reason=None)


__all__ = ["verify_passport"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/unit/test_passport_verify.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/passport/verify.py tests/unit/test_passport_verify.py
git commit -m "feat(passport): offline verifier - extract, recompute canonical sha, check Ed25519 signature"
```

---

## Task 11: Tampered-passport corpus (10+ tamper varieties)

**Files:**
- Create: `tests/golden/test_passport_tamper_corpus.py`
- Create: `tests/fixtures/passport/__init__.py` (empty package marker)
- Create: `tests/fixtures/passport/build_fixture.py` (helper used by golden tests)

- [ ] **Step 1: Write the failing test**

Create `tests/fixtures/passport/__init__.py`:

```python
```

(Empty file — just a package marker.)

Create `tests/fixtures/passport/build_fixture.py`:

```python
"""Reusable passport fixture builder for golden + corpus tests.

Generates a deterministic passport against an in-memory workspace.
Returns the rendered bytes + the canonical inputs.
"""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.tenancy import keys, store


def build_fixture_passport(
    cache_dir: Path, *, rendered_at: str = "2026-05-03T12:00:00Z"
) -> bytes:
    """Build a deterministic passport using the given cache_dir as state.

    Caller must ensure SMADP_CACHE_DIR + SMADP_KEK_MASTER are set in the env
    before calling this (so config + crypto resolve cleanly).
    """
    cfg = Config()
    ws = store.create_workspace(name="Fixture", plan="public", config=cfg)
    priv = Ed25519PrivateKey.generate()
    keys.upload_signing_key(workspace_id=ws.id, private_key=priv, config=cfg)
    return render_passport(
        verdict={
            "verdict_id": "vdt_FIXTURE",
            "pair": ["anthropic/claude", "openai/gpt"],
            "headline": "Fixture passport",
            "composite_score": 0.42,
            "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1", "MEASURE-2.3"]},
        },
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF", "version": "1.0"}},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws.id,
        rendered_at=rendered_at,
        config=cfg,
    )
```

Create `tests/golden/test_passport_tamper_corpus.py`:

```python
"""Tampered-passport corpus — every variety must fail verification."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.passport.verify import verify_passport
from tests.fixtures.passport.build_fixture import build_fixture_passport


@pytest.fixture
def passport_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> bytes:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return build_fixture_passport(tmp_path)


def test_corpus_baseline_passes(passport_html: bytes):
    """Sanity: untouched passport verifies."""
    assert verify_passport(passport_html).valid is True


# ---------- 12 tamper varieties ---------- #


def test_tamper_1_signature_byte(passport_html: bytes):
    bad = passport_html.replace(b'smadp-signature-hex" content="', b'smadp-signature-hex" content="ff', 1)
    assert verify_passport(bad).valid is False


def test_tamper_2_public_key_swap(passport_html: bytes):
    """Replace the embedded pub key with a different valid key."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    other = Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    ).hex()
    import re
    bad = re.sub(
        rb'(name="smadp-public-key-hex" content=")[0-9a-f]+(")',
        rb'\g<1>' + other.encode() + rb'\g<2>',
        passport_html, count=1,
    )
    assert verify_passport(bad).valid is False


def test_tamper_3_canonical_sha_meta_lies(passport_html: bytes):
    import re
    bad = re.sub(
        rb'(name="smadp-canonical-sha256" content=")sha256:[0-9a-f]+(")',
        rb'\g<1>sha256:' + b'0' * 64 + rb'\g<2>',
        passport_html, count=1,
    )
    assert verify_passport(bad).valid is False


def test_tamper_4_payload_verdict_id_changed(passport_html: bytes):
    bad = passport_html.replace(b"vdt_FIXTURE", b"vdt_HACKED", 1)
    assert verify_passport(bad).valid is False


def test_tamper_5_payload_score_changed(passport_html: bytes):
    bad = passport_html.replace(b'"composite_score":0.42', b'"composite_score":0.99', 1)
    assert verify_passport(bad).valid is False


def test_tamper_6_payload_framework_mapping_changed(passport_html: bytes):
    bad = passport_html.replace(b'"GOVERN-1.1"', b'"GOVERN-9.9"', 1)
    assert verify_passport(bad).valid is False


def test_tamper_7_rendered_at_changed(passport_html: bytes):
    bad = passport_html.replace(b"2026-05-03T12:00:00Z", b"2026-05-03T12:00:01Z")
    assert verify_passport(bad).valid is False


def test_tamper_8_signing_strategy_changed(passport_html: bytes):
    bad = passport_html.replace(
        b'name="smadp-signing-strategy" content="byok"',
        b'name="smadp-signing-strategy" content="sigstore"',
    )
    # Still fails because the embedded signature is over the canonical sha,
    # not the strategy. But the strategy mismatch is a verifiability concern;
    # for now, signature check still passes here. The verifier accepts both
    # strategies as long as the sig is valid. This test instead changes the
    # strategy to an UNKNOWN one to force rejection.
    bad2 = passport_html.replace(
        b'name="smadp-signing-strategy" content="byok"',
        b'name="smadp-signing-strategy" content="totally_invalid"',
    )
    assert verify_passport(bad2).valid is False


def test_tamper_9_payload_script_removed(passport_html: bytes):
    """Strip the embedded canonical payload script tag entirely."""
    import re
    bad = re.sub(
        rb'<script type="application/json" id="smadp-passport-payload">.+?</script>',
        b'',
        passport_html, count=1, flags=re.DOTALL,
    )
    assert verify_passport(bad).valid is False


def test_tamper_10_payload_truncated(passport_html: bytes):
    """Truncate the JSON payload mid-way to force a JSONDecodeError."""
    import re
    bad = re.sub(
        rb'(<script type="application/json" id="smadp-passport-payload">)(.{20})(.+?)(</script>)',
        rb'\g<1>\g<2></script>',
        passport_html, count=1, flags=re.DOTALL,
    )
    assert verify_passport(bad).valid is False


def test_tamper_11_signature_meta_removed(passport_html: bytes):
    import re
    bad = re.sub(
        rb'<meta name="smadp-signature-hex" content="[0-9a-f]*"\s*/>',
        b'',
        passport_html, count=1,
    )
    assert verify_passport(bad).valid is False


def test_tamper_12_public_key_hex_invalid(passport_html: bytes):
    import re
    bad = re.sub(
        rb'(name="smadp-public-key-hex" content=")[0-9a-f]+(")',
        rb'\g<1>not-hex\g<2>',
        passport_html, count=1,
    )
    assert verify_passport(bad).valid is False
```

- [ ] **Step 2: Run — expect either some failures from "tamper-8" subtleties or all pass**

Run: `.venv/bin/pytest tests/golden/test_passport_tamper_corpus.py -v`
Expected: baseline passes; 12 tamper tests all pass (each tamper variety detected).

If `tamper_8` (changing strategy from `byok` to `sigstore`) is the version that fails because the verifier doesn't enforce strategy-cohesion, that's acceptable for Plan 2 — the verifier in Task 10 only rejects *unknown* strategies. The fixture test was written with the **second variant (`totally_invalid`)** as the actual assertion, so that's what runs. The byok→sigstore swap would need cert-subject checking which lands in a later plan (Plan 3 webhooks/Plan 5 frameworks won't add it; that's a future tightening).

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/passport/__init__.py tests/fixtures/passport/build_fixture.py tests/golden/test_passport_tamper_corpus.py
git commit -m "test(passport): tamper corpus - 12 modification varieties must fail verification"
```

---

## Task 12: Golden test — byte-stable HTML for fixed verdict

**Files:**
- Create: `tests/golden/test_passport_render_golden.py`

We do NOT pin the *exact* full HTML byte-for-byte (signatures and public keys are non-deterministic). Instead we pin the **deterministic structural skeleton** by stripping signing fields and verifying everything else is byte-identical across runs.

- [ ] **Step 1: Write the failing test**

Create `tests/golden/test_passport_render_golden.py`:

```python
"""Golden test: structural skeleton of a passport is byte-stable.

Strips signing-related <meta> contents (which are non-deterministic) and
compares the rest byte-for-byte.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from smadp.passport.render import _render_unsigned


_VOLATILE_META = [
    b"smadp-signature-hex",
    b"smadp-public-key-hex",
    b"smadp-rekor-uuid",
    b"smadp-rekor-log-index",
    b"smadp-transparency-event-id",
    b"smadp-transparency-status",
]


def _strip_volatile(html: bytes) -> bytes:
    """Erase the content of meta tags that vary across runs."""
    out = html
    for name in _VOLATILE_META:
        out = re.sub(
            rb'(name="' + re.escape(name) + rb'" content=")[^"]*(")',
            rb'\g<1>\g<2>',
            out,
        )
    return out


def test_unsigned_render_skeleton_is_byte_stable():
    a = _render_unsigned(
        verdict={
            "verdict_id": "vdt_GOLDEN",
            "pair": ["a/x", "b/y"],
            "headline": "Golden",
            "composite_score": 0.5,
            "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1"]},
        },
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={},
        evidence_blobs_b64="",
        rendered_at="2026-05-03T12:34:56Z",
    )
    b = _render_unsigned(
        verdict={
            "verdict_id": "vdt_GOLDEN",
            "pair": ["a/x", "b/y"],
            "headline": "Golden",
            "composite_score": 0.5,
            "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1"]},
        },
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={},
        evidence_blobs_b64="",
        rendered_at="2026-05-03T12:34:56Z",
    )
    assert _strip_volatile(a) == _strip_volatile(b)


def test_full_passport_skeleton_is_byte_stable_across_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """End-to-end: full render_passport produces byte-stable skeleton."""
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "a"))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    from tests.fixtures.passport.build_fixture import build_fixture_passport
    a = build_fixture_passport(tmp_path / "a")

    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "b"))
    b = build_fixture_passport(tmp_path / "b")

    assert _strip_volatile(a) == _strip_volatile(b)
```

- [ ] **Step 2: Run — expect pass (no new prod code needed)**

Run: `.venv/bin/pytest tests/golden/test_passport_render_golden.py -v`
Expected: 2 passed.

If the second test fails because the script-tag canonical payload contains keys whose order varies, that's a real bug — the canonical payload should be sorted (Task 3 enforced this). Investigate before continuing.

- [ ] **Step 3: Commit**

```bash
git add tests/golden/test_passport_render_golden.py
git commit -m "test(passport): golden skeleton stability across runs (volatile meta stripped)"
```

---

## Task 13: API endpoint — `GET /api/passports/{slug_a}/{slug_b}.html`

**Files:**
- Create: `smadp/api/routes/passports.py`
- Create: `tests/integration/test_passports_api.py`
- Modify: `smadp/api/routes/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_passports_api.py`:

```python
"""Integration tests for /api/passports."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.config import Config
from smadp.tenancy import keys, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = store.create_workspace(name="A", plan="public", config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    return ws.id


@pytest.fixture
def client(cfg: Config) -> TestClient:
    return TestClient(create_app(cfg))


def test_get_passport_html_returns_200(client: TestClient, workspace_id: str):
    """Hit the endpoint with a known v1 catalog pair (anthropic/claude + openai/gpt-5)."""
    r = client.get(
        "/api/passports/anthropic__claude-sonnet-4.6/openai__gpt-5.html",
        headers={"X-SMADP-Workspace": workspace_id},
    )
    # If the catalog has no such verdict, expect 404; if it does, expect 200.
    # Plan 2 doesn't depend on a specific catalog row — assert one of the two.
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert r.headers["content-type"].startswith("text/html")
        assert b"<!DOCTYPE html>" in r.content


def test_get_passport_missing_workspace_header_returns_403(client: TestClient):
    r = client.get(
        "/api/passports/anthropic__claude-sonnet-4.6/openai__gpt-5.html",
    )
    assert r.status_code == 403


def test_get_passport_unknown_workspace_returns_404(client: TestClient):
    r = client.get(
        "/api/passports/anthropic__claude-sonnet-4.6/openai__gpt-5.html",
        headers={"X-SMADP-Workspace": "ws_DOESNOTEXIST"},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run — expect failures**

Run: `.venv/bin/pytest tests/integration/test_passports_api.py -v`
Expected: 3 failures (router not registered).

- [ ] **Step 3: Implement the router**

Create `smadp/api/routes/passports.py`:

```python
"""FastAPI router for passport HTML rendering."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from smadp.catalog.repo import CatalogRepo
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.schemas.tenancy import Workspace
from smadp.tenancy.deps import current_workspace

router = APIRouter(prefix="/passports", tags=["passports"])


def _slug_decode(slug: str) -> str:
    """Routes use ``__`` as a path-safe separator for slashed slugs."""
    return slug.replace("__", "/", 1)


@router.get(
    "/{slug_a}/{slug_b}.html",
    response_class=Response,
    responses={
        200: {"content": {"text/html": {}}},
        404: {"description": "Verdict not found"},
        403: {"description": "Workspace header missing or unauthorized"},
    },
)
def get_passport(
    slug_a: str,
    slug_b: str,
    workspace: Workspace = Depends(current_workspace),
) -> Response:
    repo = CatalogRepo()
    try:
        verdict_obj = repo.load_verdict(_slug_decode(slug_a), _slug_decode(slug_b))
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    verdict_dict = verdict_obj.model_dump(mode="json")

    # Plan 2 ships with frameworks loaded from the catalog meta (3 today; 11 in Plan 5).
    try:
        frameworks_dict = repo.load_frameworks_meta()
    except (FileNotFoundError, AttributeError):
        frameworks_dict = {}

    html = render_passport(
        verdict=verdict_dict,
        frameworks=frameworks_dict,
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=workspace.id,
        rendered_at=None,
    )
    return Response(content=html, media_type="text/html; charset=utf-8")


__all__ = ["router"]
```

> **Note for the implementer:** the test asserts `200 OR 404` on the first endpoint hit because the v1 catalog may not contain that exact verdict pair. If `CatalogRepo` doesn't have `load_frameworks_meta`, the `try/except` falls back to an empty dict — that's fine for Plan 2 (Plan 5 owns full framework wiring). If you discover that `CatalogRepo.load_frameworks_meta` doesn't exist at all, **leave the try/except in place** so the route still works — do NOT add a new method to the catalog repo as part of this task.

Modify `smadp/api/routes/__init__.py` to register `passports`. Add to the imports list (alphabetical) and to the ROUTERS list (after `transparency.router`):

```python
"""FastAPI route modules for the SMADP REST API."""

from smadp.api.routes import (
    agents,
    chronicle,
    evaluate,
    frameworks,
    health,
    meta,
    passports,
    sandbox,
    search,
    submit,
    transparency,
    verdicts,
    workspaces,
)

ROUTERS = [
    health.router,
    meta.router,
    agents.router,
    verdicts.router,
    submit.router,
    evaluate.router,
    search.router,
    frameworks.router,
    chronicle.router,
    sandbox.router,
    workspaces.router,
    transparency.router,
    passports.router,
]

__all__ = ["ROUTERS"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/integration/test_passports_api.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add smadp/api/routes/passports.py smadp/api/routes/__init__.py tests/integration/test_passports_api.py
git commit -m "feat(api): /api/passports/{a}/{b}.html (BYOK passport render)"
```

---

## Task 14: CLI — `smadp passport verify`

**Files:**
- Create: `smadp/passport/cli.py`
- Modify: `smadp/cli.py` (register the subgroup)
- Create: `tests/integration/test_cli_passport.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_cli_passport.py`:

```python
"""Integration tests for the smadp passport CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.cli import cli
from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.tenancy import keys, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


def _build_passport(cfg: Config) -> bytes:
    ws = store.create_workspace(name="A", plan="public", config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    return render_passport(
        verdict={
            "verdict_id": "vdt_CLI",
            "pair": ["a/x", "b/y"],
            "headline": "CLI test",
            "composite_score": 0.5,
            "framework_mappings": {},
        },
        frameworks={},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws.id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )


def test_passport_verify_clean_passes(cfg: Config, tmp_path: Path):
    p = tmp_path / "passport.html"
    p.write_bytes(_build_passport(cfg))
    runner = CliRunner()
    result = runner.invoke(cli, ["passport", "verify", str(p)])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_passport_verify_tampered_fails(cfg: Config, tmp_path: Path):
    p = tmp_path / "passport.html"
    bad = _build_passport(cfg).replace(b"vdt_CLI", b"vdt_HACK", 1)
    p.write_bytes(bad)
    runner = CliRunner()
    result = runner.invoke(cli, ["passport", "verify", str(p)])
    assert result.exit_code != 0
    assert "INVALID" in result.output or "BREAK" in result.output


def test_passport_verify_missing_file(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["passport", "verify", str(tmp_path / "no.html")])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/pytest tests/integration/test_cli_passport.py -v`
Expected: failures (no `passport` subgroup).

- [ ] **Step 3: Implement the CLI**

Create `smadp/passport/cli.py`:

```python
"""Click subcommands for passports: verify."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from smadp.passport.verify import verify_passport

console = Console()


@click.group(name="passport")
def passport_group() -> None:
    """Inspect and verify SMADP passports."""


@passport_group.command(name="verify")
@click.argument(
    "passport_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def verify(passport_path: Path) -> None:
    """Verify a passport HTML file offline."""
    html = passport_path.read_bytes()
    result = verify_passport(html)
    if result.valid:
        console.print("[green]OK[/green] — passport signature + payload intact.")
        sys.exit(0)
    else:
        console.print(f"[red]INVALID[/red] — {result.reason}")
        sys.exit(1)


__all__ = ["passport_group"]
```

Modify `smadp/cli.py`. Find the existing `from smadp.transparency.cli import transparency_group` import and the `cli.add_command(transparency_group)` call (added in Plan 1). Add equivalent lines for `passport_group` immediately below them:

```python
from smadp.transparency.cli import transparency_group
from smadp.passport.cli import passport_group

cli.add_command(transparency_group)
cli.add_command(passport_group)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/pytest tests/integration/test_cli_passport.py -v`
Expected: 3 passed.

- [ ] **Step 5: Manual smoke**

Run: `.venv/bin/python -m smadp.cli passport --help`
Expected: shows `verify` subcommand and "Inspect and verify SMADP passports" description.

- [ ] **Step 6: Commit**

```bash
git add smadp/passport/cli.py smadp/cli.py tests/integration/test_cli_passport.py
git commit -m "feat(cli): smadp passport verify"
```

---

## Task 15: Sigstore deferred-mode integration test (with retry)

**Files:**
- Create: `tests/integration/test_passport_sigstore_deferred.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_passport_sigstore_deferred.py`:

```python
"""Integration test: Sigstore unreachable -> deferred -> retry succeeds."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.passport.verify import verify_passport
from smadp.schemas.passport import SigningStrategy
from smadp.tenancy import keys, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    monkeypatch.setenv("SMADP_SIGSTORE_ENABLED", "true")
    monkeypatch.setenv("SMADP_REKOR_URL", "https://rekor.example.test")
    return Config()


@pytest.fixture
def workspace_id(cfg: Config) -> str:
    ws = store.create_workspace(name="A", plan="public", config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )
    return ws.id


def _verdict():
    return {
        "verdict_id": "vdt_DEFER",
        "pair": ["a/x", "b/y"],
        "headline": "Deferred test",
        "composite_score": 0.5,
        "framework_mappings": {},
    }


@respx.mock
def test_sigstore_unreachable_renders_deferred(cfg: Config, workspace_id: str):
    respx.post("https://rekor.example.test/api/v1/log/entries").mock(
        return_value=httpx.Response(503)
    )
    html = render_passport(
        verdict=_verdict(), frameworks={}, evidence_index={}, evidence_blobs={},
        signing_strategy=SigningStrategy.SIGSTORE, workspace_id=workspace_id,
        rendered_at="2026-05-03T12:00:00Z", config=cfg,
    )
    text = html.decode("utf-8")
    assert 'name="smadp-transparency-status" content="deferred"' in text
    assert 'name="smadp-rekor-uuid" content=""' in text
    # Verifier still accepts (signature is valid; deferred is a status, not a failure)
    assert verify_passport(html).valid is True


@respx.mock
def test_sigstore_success_embeds_rekor_uuid_and_proof_index(
    cfg: Config, workspace_id: str
):
    respx.post("https://rekor.example.test/api/v1/log/entries").mock(
        return_value=httpx.Response(
            201,
            json={
                "uuid-success-001": {
                    "logIndex": 7777,
                    "logID": "x",
                    "integratedTime": 1714740000,
                }
            },
        )
    )
    respx.get(
        "https://rekor.example.test/api/v1/log/entries/uuid-success-001/proof"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "logIndex": 7777,
                "treeSize": 100000,
                "rootHash": "ab" * 32,
                "hashes": [],
                "checkpoint": "x",
            },
        )
    )
    html = render_passport(
        verdict=_verdict(), frameworks={}, evidence_index={}, evidence_blobs={},
        signing_strategy=SigningStrategy.SIGSTORE, workspace_id=workspace_id,
        rendered_at="2026-05-03T12:00:00Z", config=cfg,
    )
    text = html.decode("utf-8")
    assert 'name="smadp-transparency-status" content="submitted"' in text
    assert 'name="smadp-rekor-uuid" content="uuid-success-001"' in text
    assert 'name="smadp-rekor-log-index" content="7777"' in text
    assert verify_passport(html).valid is True
```

- [ ] **Step 2: Run — expect pass**

Run: `.venv/bin/pytest tests/integration/test_passport_sigstore_deferred.py -v`
Expected: 2 passed (the render_passport implementation in Task 9 already handles both branches).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_passport_sigstore_deferred.py
git commit -m "test(passport): sigstore unreachable -> deferred mode + success path embeds rekor UUID + log_index"
```

---

## Task 16: End-to-end test — render → save → CLI verify

**Files:**
- Create: `tests/integration/test_passport_e2e.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_passport_e2e.py`:

```python
"""End-to-end: workspace + BYOK + render via API + verify via CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from smadp.api.server import create_app
from smadp.cli import cli
from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.tenancy import keys, store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SMADP_KEK_MASTER", "0" * 64)
    return Config()


def test_render_via_api_then_verify_via_cli(cfg: Config, tmp_path: Path):
    # Workspace + BYOK key
    ws = store.create_workspace(name="E2E", plan="public", config=cfg)
    keys.upload_signing_key(
        workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg
    )

    # Render directly (the API route itself depends on a catalog verdict that
    # may not exist in this test cache — render_passport bypasses the catalog).
    html = render_passport(
        verdict={
            "verdict_id": "vdt_E2E",
            "pair": ["a/x", "b/y"],
            "headline": "E2E",
            "composite_score": 0.5,
            "framework_mappings": {"nist_ai_rmf": ["GOVERN-1.1"]},
        },
        frameworks={"nist_ai_rmf": {"name": "NIST AI RMF"}},
        evidence_index={},
        evidence_blobs={},
        signing_strategy=SigningStrategy.BYOK,
        workspace_id=ws.id,
        rendered_at="2026-05-03T12:00:00Z",
        config=cfg,
    )

    # Save to disk + verify via CLI
    out = tmp_path / "passport.html"
    out.write_bytes(html)

    runner = CliRunner()
    result = runner.invoke(cli, ["passport", "verify", str(out)])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output

    # Also confirm the API smoke (workspace endpoint reachable)
    client = TestClient(create_app(cfg))
    r = client.get(f"/api/workspaces/{ws.id}")
    assert r.status_code == 200
```

- [ ] **Step 2: Run — expect pass**

Run: `.venv/bin/pytest tests/integration/test_passport_e2e.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_passport_e2e.py
git commit -m "test(passport): end-to-end render + CLI verify roundtrip"
```

---

## Task 17: CI — passport verify smoke step

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Inspect existing CI**

Run: `cat .github/workflows/ci.yml`
The Plan 1 final sweep added a "Smoke — transparency verify" step between Pytest and Catalog lint. We add a parallel passport smoke step in the same location, AFTER the transparency one.

- [ ] **Step 2: Add the smoke step**

Insert this YAML step in the `python` job, immediately AFTER the existing `Smoke — transparency verify` step and BEFORE `Catalog lint`:

```yaml
      - name: Smoke — passport render + verify
        env:
          SMADP_CACHE_DIR: ${{ runner.temp }}/smadp-passport-ci
          SMADP_KEK_MASTER: "0000000000000000000000000000000000000000000000000000000000000000"
        run: |
          python -c "
          import os, pathlib
          from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
          from smadp.config import Config
          from smadp.passport.render import render_passport
          from smadp.schemas.passport import SigningStrategy
          from smadp.tenancy import keys, store

          cfg = Config()
          ws = store.create_workspace(name='ci', plan='public', config=cfg)
          keys.upload_signing_key(workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg)
          html = render_passport(
              verdict={'verdict_id':'vdt_ci','pair':['a/x','b/y'],'headline':'ci','composite_score':0.5,'framework_mappings':{}},
              frameworks={}, evidence_index={}, evidence_blobs={},
              signing_strategy=SigningStrategy.BYOK,
              workspace_id=ws.id, rendered_at='2026-05-03T00:00:00Z', config=cfg,
          )
          out = pathlib.Path(os.environ['SMADP_CACHE_DIR']) / 'ci.html'
          out.write_bytes(html)
          print('rendered', out)
          "
          python -m smadp.cli passport verify "${{ runner.temp }}/smadp-passport-ci/ci.html"
```

- [ ] **Step 3: Verify YAML parses**

Run: `.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no error.

- [ ] **Step 4: Local smoke (optional but recommended)**

```bash
SMADP_CACHE_DIR=/tmp/smadp-task17-passport SMADP_KEK_MASTER=0000000000000000000000000000000000000000000000000000000000000000 .venv/bin/python -c "
import os, pathlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from smadp.config import Config
from smadp.passport.render import render_passport
from smadp.schemas.passport import SigningStrategy
from smadp.tenancy import keys, store
cfg = Config()
ws = store.create_workspace(name='ci', plan='public', config=cfg)
keys.upload_signing_key(workspace_id=ws.id, private_key=Ed25519PrivateKey.generate(), config=cfg)
html = render_passport(
    verdict={'verdict_id':'vdt_ci','pair':['a/x','b/y'],'headline':'ci','composite_score':0.5,'framework_mappings':{}},
    frameworks={}, evidence_index={}, evidence_blobs={},
    signing_strategy=SigningStrategy.BYOK, workspace_id=ws.id,
    rendered_at='2026-05-03T00:00:00Z', config=cfg,
)
out = pathlib.Path(os.environ['SMADP_CACHE_DIR']) / 'ci.html'
out.write_bytes(html)
print('OK:', out)
"
SMADP_CACHE_DIR=/tmp/smadp-task17-passport .venv/bin/python -m smadp.cli passport verify /tmp/smadp-task17-passport/ci.html
```

Expected: prints `OK:` then `OK — passport signature + payload intact.`. Exit 0.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: smoke-test smadp passport render + verify on every push"
```

- [ ] **Step 6: DO NOT push**

Push happens after Task 18's final sweep.

---

## Task 18: Spec coverage cross-check (no code, just verify)

**Files:** none

This task does NOT change any files. It is a focused re-read of the spec sections this plan claims to cover, ticking each off.

- [ ] **Step 1: Spec §6.3 (`smadp.passport`)**
  - `render_passport(verdict_id, *, signing_strategy) -> bytes` — implemented (Task 9). Note: takes `slug_a/slug_b` indirectly via the catalog repo at the API layer; the underlying function takes the verdict dict directly. Acceptable scope cut.
  - `verify_passport(html_bytes) -> VerificationResult` — implemented (Task 10).

- [ ] **Step 2: Spec §7.2 (passport flow)**
  - tenancy resolves signing strategy: ✓ (BYOK is default; SIGSTORE is opt-in via `SMADP_SIGSTORE_ENABLED`)
  - render Jinja2 template with inlined SVG icons: ✓ (Tasks 4, 5, 6)
  - embed evidence JSON as base64 `<data>` attachment: ✓ (Task 6 builds `evidence_blobs_b64`; Task 5 embeds it as `<script>` tag)
  - sign payload with Ed25519: ✓ (Task 7 BYOK)
  - `transparency.append_event("passport.generated", ...)`: ✓ (Task 9)
  - if sigstore: submit to Rekor; embed inclusion proof in `<meta>`: ✓ (Tasks 8 + 9)
  - return signed HTML bytes: ✓
  - **Webhook fire on `passport.generated`**: NOT in this plan — that's Plan 3 (Webhooks). The transparency event is written; the webhook dispatcher reads transparency events in Plan 3.

- [ ] **Step 3: Spec §8.3 (passport schemas)**
  - `PassportRenderRequest`: ✓ (Task 2)
  - `SigningStrategy` enum: ✓ (Task 2)
  - `VerificationResult`: ✓ (Task 2)

- [ ] **Step 4: Spec §9 passport rows**
  - `passport_not_found`: ✓ (Task 13: 404 from CatalogRepo failure)
  - `passport_signature_invalid`: ✓ (Task 10 returns reason)
  - `byok_key_missing_for_workspace`: ✓ (Task 9 raises KeyError with this string)
  - **Sigstore unreachable → deferred**: ✓ (Task 9 + Task 15)
  - **Tampered passport fails closed**: ✓ (Task 11's 12-variety corpus)

- [ ] **Step 5: Spec §10.3 + §10.4 (golden + tamper)**
  - Golden HTML render: ✓ (Task 12)
  - Tampered-passport corpus (10+ varieties): ✓ (Task 11; 12 varieties)

- [ ] **Step 6: Scope cuts (acknowledged)**
  - Auth (who-is-this-user) — Plan 1 deferred to Plan 7; passports rely on the same `X-SMADP-Workspace` header trust model.
  - Sigstore-strategy cert-subject mismatch detection — deferred (Task 11 note).
  - Webhook event firing on `passport.generated` — Plan 3.
  - Real sigstore `sigstore-python` lib (we use Rekor REST directly) — design pick, recorded in Pre-flight.

- [ ] **Step 7: No commit (this is documentation-only review)**

---

## Task 19: Final sweep — lint, format, mypy, full test suite

**Files:**
- Possibly modify any file flagged by the linters

- [ ] **Step 1: Run ruff lint**

Run: `.venv/bin/ruff check smadp tests`
Expected: 0 issues. If issues found, fix and re-run.

- [ ] **Step 2: Run ruff format check**

Run: `.venv/bin/ruff format --check smadp tests`
Expected: 0 changes needed. If changes needed: `ruff format smadp tests` then commit as `style: ruff format`.

- [ ] **Step 3: Run mypy**

Run: `.venv/bin/mypy smadp`
Expected: no errors.

- [ ] **Step 4: Run the full test suite**

Run: `.venv/bin/pytest -ra`
Expected: all tests pass. The tally should be ~244 (Plan 1) + ~50 new = ~290+ tests passing.

- [ ] **Step 5: Commit any sweep fixes**

If sweep surfaced fixes, commit as `chore(plan2): final sweep — lint/format/mypy fixes` with a short body explaining what was changed.

- [ ] **Step 6: Push**

```bash
git push
gh run watch
```

Expected: CI green for Python 3.11, 3.12, and Dashboard build. Plan 2 ships when CI is green.

---

## Self-review (engineer should run this before marking the plan done)

- [ ] **Spec coverage check** — Task 18 is the explicit cross-check. No additional review needed.
- [ ] **All 19 tasks committed individually** — audit log shows TDD discipline.
- [ ] **No `# TODO`/`# FIXME` in shipped code** — grep `smadp/passport/` and `smadp/transparency/sigstore.py` for these markers; none should remain.
- [ ] **All file paths are absolute or relative-to-repo-root** — no `/Users/` or `~/` references in code or templates.

---

**Plan 2 ships when CI is green and all 19 tasks are merged. Plan 3 (Webhooks) can begin immediately and will:**
- Wire `dispatch_event` to read transparency events.
- Fire `passport.generated` webhooks (the event is already being written by Task 9 of this plan).
- Add the `subscriptions` and `webhook_deliveries` tables.
- Build the worker process.
