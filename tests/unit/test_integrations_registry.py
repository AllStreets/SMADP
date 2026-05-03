"""Unit tests for integrations registry."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from smadp.integrations import base, get_adapter
from smadp.schemas.webhooks import EventType, IntegrationKind, WebhookEnvelope


def _envelope() -> WebhookEnvelope:
    return WebhookEnvelope(
        id="evt_20260503120000_abcdef",
        type=EventType.PASSPORT_GENERATED,
        created_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        workspace_id="ws_ABCD1234",
        data={"verdict_id": "vdt_X"},
        signature_meta={"transparency_log_id": 1},
    )


def test_registry_has_all_kinds():
    # Tasks 15-17 register vanta/drata/slack; this test re-runs after each.
    registered = {IntegrationKind.GENERIC, IntegrationKind.VANTA}
    for kind in registered:
        adapter = get_adapter(kind)
        assert adapter.kind == kind


def test_unknown_kind_raises():
    with pytest.raises(KeyError):
        base.get_adapter("nonsense")  # type: ignore[arg-type]


def test_generic_adapter_returns_canonical_envelope_bytes():
    adapter = get_adapter(IntegrationKind.GENERIC)
    body = adapter.translate(_envelope(), config={})
    assert body.startswith(b"{")
    assert b'"id":"evt_20260503120000_abcdef"' in body
    assert adapter.headers(_envelope(), config={}) == {}
