"""Adapter Protocol + registry for native webhook integrations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from smadp.schemas.webhooks import IntegrationKind, WebhookEnvelope


class Adapter(Protocol):
    kind: IntegrationKind

    def translate(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> bytes: ...

    def headers(
        self, envelope: WebhookEnvelope, *, config: Mapping[str, object]
    ) -> dict[str, str]: ...


_REGISTRY: dict[IntegrationKind, Adapter] = {}


def register_adapter(adapter: Adapter) -> None:
    if adapter.kind in _REGISTRY:
        raise ValueError(f"adapter for {adapter.kind!r} already registered")
    _REGISTRY[adapter.kind] = adapter


def get_adapter(kind: IntegrationKind) -> Adapter:
    if kind not in _REGISTRY:
        raise KeyError(f"no adapter registered for kind={kind!r}")
    return _REGISTRY[kind]


__all__ = ["Adapter", "get_adapter", "register_adapter"]
