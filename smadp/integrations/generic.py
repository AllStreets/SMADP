"""Generic adapter — passes the canonical envelope bytes through unchanged."""

from __future__ import annotations

from collections.abc import Mapping

from smadp.integrations.base import register_adapter
from smadp.schemas.webhooks import IntegrationKind, WebhookEnvelope
from smadp.webhooks.envelope import canonical_envelope_bytes


class GenericAdapter:
    kind = IntegrationKind.GENERIC

    def translate(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> bytes:
        return canonical_envelope_bytes(envelope)

    def headers(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> dict[str, str]:
        return {}


register_adapter(GenericAdapter())


__all__ = ["GenericAdapter"]
