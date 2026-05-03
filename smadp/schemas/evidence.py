"""Evidence snippet schema (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ValidStatus = Literal["valid", "stale", "missing", "changed"]


class Evidence(BaseModel):
    """Authoritative model for `catalog/_evidence/sha256-<hash>.json`."""

    model_config = ConfigDict(extra="forbid")

    sha256: str
    source_url: HttpUrl
    fetched_at: datetime
    fetcher: str
    media_type: str
    quote: str = Field(min_length=1, max_length=8000)
    context: str | None = Field(default=None, max_length=500)
    fingerprint: str | None = None
    valid_at: datetime | None = None
    valid_status: ValidStatus | None = None

    @field_validator("sha256")
    @classmethod
    def _validate_sha(cls, v: str) -> str:
        if not SHA256_RE.match(v):
            raise ValueError(f"Invalid sha256: {v!r}")
        return v

    @property
    def evidence_ref(self) -> str:
        return f"sha256:{self.sha256}"
