"""Drata evidence-update adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping

from smadp.integrations.base import register_adapter
from smadp.schemas.webhooks import IntegrationKind, WebhookEnvelope


class DrataAdapter:
    kind = IntegrationKind.DRATA

    def _config(self, config: Mapping[str, object]) -> tuple[str, str]:
        token = config.get("token")
        control_id = config.get("control_id")
        if not isinstance(token, str) or not token:
            raise ValueError("drata config missing 'token'")
        if not isinstance(control_id, str) or not control_id:
            raise ValueError("drata config missing 'control_id'")
        return token, control_id

    def translate(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> bytes:
        _token, control_id = self._config(config)
        occurred = envelope.created_at.isoformat(timespec="seconds").replace("+00:00", "Z")
        evidence = {
            "verdict_id": envelope.data.get("verdict_id", "n/a"),
            "score": envelope.data.get("composite_score"),
            "passport_url": envelope.data.get("passport_url"),
            "event_type": envelope.type.value,
        }
        payload = {
            "controlId": control_id,
            "occurredAt": occurred,
            "evidence": evidence,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def headers(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> dict[str, str]:
        token, _ = self._config(config)
        return {
            "Authorization": f"Bearer {token}",
            "X-Drata-Source": "smadp",
            "Content-Type": "application/json",
        }


register_adapter(DrataAdapter())


__all__ = ["DrataAdapter"]
