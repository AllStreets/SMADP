"""Vanta evidence-update adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping

from smadp.integrations.base import register_adapter
from smadp.schemas.webhooks import IntegrationKind, WebhookEnvelope


class VantaAdapter:
    kind = IntegrationKind.VANTA

    def _config(self, config: Mapping[str, object]) -> tuple[str, str]:
        token = config.get("token")
        request_id = config.get("evidence_request_id")
        if not isinstance(token, str) or not token:
            raise ValueError("vanta config missing 'token'")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("vanta config missing 'evidence_request_id'")
        return token, request_id

    def translate(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> bytes:
        _token, request_id = self._config(config)
        verdict_id = envelope.data.get("verdict_id", "n/a")
        passed_at = envelope.created_at.isoformat(timespec="seconds").replace("+00:00", "Z")
        payload = {
            "evidenceType": "smadp_passport",
            "evidenceRequestId": request_id,
            "evidenceId": verdict_id,
            "passedAt": passed_at,
            "metadata": dict(envelope.data),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def headers(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> dict[str, str]:
        token, _ = self._config(config)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


register_adapter(VantaAdapter())


__all__ = ["VantaAdapter"]
