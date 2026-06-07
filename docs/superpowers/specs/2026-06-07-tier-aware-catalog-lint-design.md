# Design: Tier-Aware Catalog Lint (DEFERRED)

**Date:** 2026-06-07
**Status:** Draft — deferred until after V3 work; written now to preserve context
**Spec ID:** `2026-06-07-tier-aware-catalog-lint-design`

## Summary

After the autopilot pivot, `catalog/profiles/` and `catalog/verdicts/` hold artifacts at three evidence tiers (curated / docs-only / unverified-profile) and the legacy `smadp.catalog.lint` + JSONSchema validators only accept the top tier. This spec captures the full refactor — kept separate so the immediate Ruff/format/index work can ship without taking on this multi-day rewrite.

## Failing tests this spec resolves

- `tests/unit/test_catalog_lint.py::test_seed_catalog_is_clean` — `smadp.catalog.lint.lint_catalog()` returns ≥1 violation when run against the post-bootstrap catalog because every stub fails strict-schema validation and every LLM-enriched profile fails because of extra fields the lint hasn't been taught about.
- `tests/integration/test_catalog_validates_against_jsonschema.py::test_every_profile_matches_schema` and `::test_every_verdict_matches_schema` — these are the JSONSchema (not Pydantic) versions of the same problem. The `catalog/_meta/schema/1.0/profile.schema.json` and `verdict.schema.json` files declare every required field and reject extras.
- `tests/integration/test_cli_smoke.py::test_lint_clean_on_seed_catalog` and `::test_validate_clean_on_seed_catalog` — CLI wrappers around the above.
- `tests/integration/test_api_smoke.py::test_search_returns_results` — possibly indirectly affected by the lint failure during fixture setup.

## Approach

Replace the single `Profile` model + single `profile.schema.json` with a tier-discriminated union, and rewrite `lint.py` to dispatch per tier.

### Tier schemas (Pydantic side)

```python
# smadp/schemas/profile.py — tier-aware refactor

class StubProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    name: str
    category: str
    docs_urls: list[HttpUrl] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_level: Literal["unverified-profile"]
    composite_score: float | None = None
    license: str | None = None
    onexus: dict[str, Any] | None = None
    capabilities: None = None
    concurrency_model: None = None
    data_classes_touched: list[str] = Field(default_factory=list)

class DocsOnlyProfile(BaseModel):
    """LLM-enriched: capabilities populated, vendor optional, no strict cite requirement."""
    model_config = ConfigDict(extra="forbid")
    slug: str
    name: str
    category: str
    evidence_level: Literal["docs-only", "profile-verified"]
    capabilities: Capabilities = Field(default_factory=Capabilities)
    io_surfaces: IOSurfaces = Field(default_factory=IOSurfaces)
    data_classes_touched: list[str] = Field(default_factory=list)
    sandboxing: Sandboxing = Field(default_factory=Sandboxing)
    concurrency_model: ConcurrencyModel | None = None
    vendor: Vendor | None = None
    permissions_requested: PermissionsRequested = Field(default_factory=PermissionsRequested)
    verification: Verification | None = None
    docs_urls: list[HttpUrl] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    first_seen_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    composite_score: float | None = None
    license: str | None = None
    onexus: dict[str, Any] | None = None
    pairings: list[str] = Field(default_factory=list)
    repo_url: HttpUrl | None = None
    homepage: HttpUrl | None = None
    tagline: str | None = None
    source_type: SourceType | None = None

class CuratedProfile(BaseModel):
    """The original strict schema, unchanged from pre-pivot, with manual: true."""
    # ... all the original required fields, manual: bool = True

ProfileUnion = Annotated[
    StubProfile | DocsOnlyProfile | CuratedProfile,
    Field(discriminator="evidence_level"),
]
```

The discriminator routes by `evidence_level`. Note that `CuratedProfile` doesn't have `evidence_level` today — it'd need to be added (with default `"profile-verified"` or similar) to participate in the union.

### JSONSchema side

Three new files under `catalog/_meta/schema/1.0/`:
- `profile.stub.schema.json` — required: slug, name, category, evidence_refs, evidence_level (must equal `"unverified-profile"`)
- `profile.docs-only.schema.json` — required: slug, name, category, capabilities, evidence_level (in {"docs-only", "profile-verified"})
- `profile.curated.schema.json` — current `profile.schema.json` content + `manual: true` required

Add `profile.schema.json` as a `oneOf` over the three, discriminated by `evidence_level`.

### Lint rewrite

```python
# smadp/catalog/lint.py
def lint_profile(path: Path, raw: dict) -> list[LintError]:
    tier = raw.get("evidence_level")
    if tier == "unverified-profile":
        return _lint_stub(path, raw)
    if tier in ("docs-only", "profile-verified"):
        return _lint_docs_only(path, raw)
    if raw.get("manual") is True:
        return _lint_curated(path, raw)
    return [LintError(path, "unknown profile tier; missing evidence_level or manual flag")]
```

Each `_lint_*` helper validates against its tier's schema + tier-specific business rules (e.g. stub must have onexus.source_github; docs-only must have at least one capability or be marked partial; curated must have verification.verified_by).

## Migration steps

1. Add `evidence_level` to `CuratedProfile` (defaulted) so the discriminator works.
2. Write the three new JSONSchema files; keep the top-level `profile.schema.json` as a `oneOf`.
3. Update `smadp.catalog.lint` to dispatch by tier.
4. Update `smadp.catalog.repo.list_profiles` to use the discriminated union.
5. Update `tests/conftest.py` fixtures: split `all_profile_paths` into `curated_profile_paths`, `docs_only_profile_paths`, `stub_profile_paths`.
6. Update all 6 failing tests to use the right fixture and right schema.
7. Hand-author one acceptance fixture per tier so the test suite has known-good inputs.

## Cost / time

~3–5 days of focused work. Touches Pydantic schemas, JSONSchema, lint, repo, conftest, 6 test files. Real schema migration, not lint sweeping.

## Why deferred (decided 2026-06-07)

User priorities, in order:
1. Get CI green on lint + format + autopilot tests (done by `ef3afdb` + S1–S3).
2. Wait until after the V3+ "claude-code-quality every-agent pages" arc lands before doing the full schema migration — that arc will expand the schema surface anyway (multi-source enrichment, completion judge, etc.) so doing the lint refactor twice is wasteful.
3. Continue grinding the autopilot loop overnight on the existing schema (it works for autopilot's own consumers; only the legacy lint/JSONSchema tooling cares).

When this gets picked up: read this spec + the pivot spec + the V3+ spec together; the schema choices need to align.

## Acceptance criteria

- All 6 currently-failing tests pass without modifying real-world catalog data.
- Lint returns 0 violations against the live catalog (~6,030 profiles + ~120 verdicts).
- Adding a new profile at any tier (stub / docs-only / curated) lints cleanly via the right discriminator.
- The Pydantic union is exported as `Profile = ProfileUnion` so downstream callers don't break.

## Out of scope

- Multi-source enrichment / completion judge (separate V3+ spec)
- JSONSchema → Pydantic auto-sync tooling (nice to have, ignore for now)
- Per-tier rendering in the site (already handled by defensive loader in `f807bb6`)
