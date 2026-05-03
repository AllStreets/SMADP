"""Webhook schemas (Pydantic v2): events, subscriptions, deliveries, envelopes."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

SUBSCRIPTION_ID_RE = re.compile(r"^sub_[A-Z0-9]{8,}$")
DELIVERY_ID_RE = re.compile(r"^wd_[0-9]{14}_[0-9a-f]{6}$")
EVENT_ID_RE = re.compile(r"^evt_[0-9]{14}_[0-9a-f]{6}$")
WORKSPACE_ID_RE = re.compile(r"^ws_[A-Z0-9]{8,}$")


class EventType(StrEnum):
    VERDICT_CREATED = "verdict.created"
    VERDICT_UPDATED = "verdict.updated"
    VERDICT_EXPIRED = "verdict.expired"
    FRAMEWORK_COVERAGE_CHANGED = "framework_coverage.changed"
    PASSPORT_GENERATED = "passport.generated"
    PASSPORT_REVOKED = "passport.revoked"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DELIVERED = "delivered"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


class Subscription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    url: str
    event_types: list[EventType]
    active: bool
    created_at: datetime

    @field_validator("id")
    @classmethod
    def _id_pattern(cls, v: str) -> str:
        if not SUBSCRIPTION_ID_RE.match(v):
            raise ValueError(f"Invalid subscription id: {v!r}")
        return v

    @field_validator("workspace_id")
    @classmethod
    def _ws_id(cls, v: str) -> str:
        if not WORKSPACE_ID_RE.match(v):
            raise ValueError(f"Invalid workspace id: {v!r}")
        return v

    @field_validator("url")
    @classmethod
    def _url_scheme(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme == "https":
            return v
        if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
            return v
        raise ValueError(
            f"Subscription URL must be https:// (or http://localhost for dev); got {v!r}"
        )

    @field_validator("event_types")
    @classmethod
    def _nonempty(cls, v: list[EventType]) -> list[EventType]:
        if not v:
            raise ValueError("event_types must not be empty")
        return v


class WebhookDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    subscription_id: str
    event_id: str
    event_type: EventType
    body: bytes
    status: DeliveryStatus
    attempts: int
    next_attempt_at: datetime
    last_error: str | None
    created_at: datetime
    delivered_at: datetime | None

    @field_validator("id")
    @classmethod
    def _id_pattern(cls, v: str) -> str:
        if not DELIVERY_ID_RE.match(v):
            raise ValueError(f"Invalid delivery id: {v!r}")
        return v

    @field_validator("subscription_id")
    @classmethod
    def _sub_id(cls, v: str) -> str:
        if not SUBSCRIPTION_ID_RE.match(v):
            raise ValueError(f"Invalid subscription id: {v!r}")
        return v

    @field_validator("event_id")
    @classmethod
    def _ev_id(cls, v: str) -> str:
        if not EVENT_ID_RE.match(v):
            raise ValueError(f"Invalid event id: {v!r}")
        return v


class WebhookEnvelope(BaseModel):
    """Stable on-the-wire JSON contract; never reorder keys after launch."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: EventType
    created_at: datetime
    workspace_id: str
    data: dict[str, Any]
    signature_meta: dict[str, Any]

    @field_validator("id")
    @classmethod
    def _ev_id(cls, v: str) -> str:
        if not EVENT_ID_RE.match(v):
            raise ValueError(f"Invalid envelope id: {v!r}")
        return v

    @field_validator("workspace_id")
    @classmethod
    def _ws_id(cls, v: str) -> str:
        if not WORKSPACE_ID_RE.match(v):
            raise ValueError(f"Invalid workspace id: {v!r}")
        return v

    @model_validator(mode="after")
    def _required_signature_meta(self) -> WebhookEnvelope:
        if "transparency_log_id" not in self.signature_meta:
            raise ValueError("signature_meta must include 'transparency_log_id'")
        return self


__all__ = [
    "DeliveryStatus",
    "EventType",
    "Subscription",
    "WebhookDelivery",
    "WebhookEnvelope",
]
