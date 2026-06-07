"""Safety Profile schema (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
EVIDENCE_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

NetworkEgress = Literal["none", "allowlisted", "vendor-only", "broad"]
SourceType = Literal["open-source", "closed-source", "source-available"]
VerificationStatus = Literal["unverified", "draft", "verified", "stale", "invalid"]
VerificationMethod = Literal["manual-review-of-llm-extraction", "manual-authoring", "auto-only"]


class Vendor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["company", "org", "individual"]
    handle: str = Field(min_length=1)
    url: HttpUrl | None = None


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    verified_by: str | None = None
    verified_at: datetime
    method: VerificationMethod


class Capabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execute_shell: bool = False
    read_filesystem: bool = False
    write_filesystem: bool = False
    network_egress: NetworkEgress = "none"
    spawn_subprocesses: bool = False
    use_mcp: bool = False
    modify_git_state: bool = False
    install_packages: bool = False
    run_browsers: bool = False


class IOSurfaces(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stdin_stdout: bool = False
    files: list[str] = Field(default_factory=list)
    clipboard: bool = False
    screen_capture: bool = False
    audio: bool = False
    calls_apis: list[str] = Field(default_factory=list)


class PermissionsRequested(BaseModel):
    model_config = ConfigDict(extra="forbid")

    oauth_scopes: list[str] = Field(default_factory=list)
    secrets_handled: list[str] = Field(default_factory=list)
    elevated_privileges: list[str] = Field(default_factory=list)


class Sandboxing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_isolation: str = ""
    subagent_model: str = ""
    tool_use_pattern: str = ""


class ConcurrencyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_scope: str = ""
    shared_state_with_other_instances: str = ""
    supports_multiple_instances: bool = False


class Profile(BaseModel):
    """Authoritative model for `catalog/profiles/<slug>.json`."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "1.1"] = "1.1"
    slug: str
    name: str = Field(min_length=1, max_length=100)
    tagline: str | None = Field(default=None, max_length=200)
    vendor: Vendor
    source_type: SourceType
    category: str = Field(min_length=1)
    homepage: HttpUrl | None = None
    docs_urls: list[HttpUrl] = Field(default_factory=list)
    repo_url: HttpUrl | None = None
    verification: Verification
    capabilities: Capabilities = Field(default_factory=Capabilities)
    io_surfaces: IOSurfaces = Field(default_factory=IOSurfaces)
    permissions_requested: PermissionsRequested = Field(default_factory=PermissionsRequested)
    data_classes_touched: list[str] = Field(default_factory=list)
    sandboxing: Sandboxing = Field(default_factory=Sandboxing)
    concurrency_model: ConcurrencyModel = Field(default_factory=ConcurrencyModel)
    evidence_refs: list[str] = Field(default_factory=list)
    first_seen_at: datetime
    last_refreshed_at: datetime
    pairings: list[str] = Field(default_factory=list, max_length=20)

    # ---------------------------------------------------------------------
    # Autopilot-pipeline metadata. These fields ride along on the same JSON
    # but are managed by the autopilot (bootstrap, enrichment, pair gate)
    # rather than the original hand-authoring contract. They are Optional
    # so older hand-curated profiles without them still validate cleanly.
    # ---------------------------------------------------------------------
    manual: bool | None = None
    composite_score: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_level: (
        Literal["unverified-profile", "docs-only", "profile-verified", "sandbox-validated"] | None
    ) = None
    license: str | None = None
    onexus: dict[str, Any] | None = None

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError(f"Invalid slug: {v!r}")
        return v

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, v: list[str]) -> list[str]:
        for ref in v:
            if not EVIDENCE_REF_RE.match(ref):
                raise ValueError(f"Invalid evidence ref: {ref!r}")
        return v

    @field_validator("pairings")
    @classmethod
    def _validate_pairings(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("pairings must not contain duplicates")
        for slug in v:
            if not SLUG_RE.match(slug):
                raise ValueError(f"Invalid pairings slug: {slug!r}")
        return v
