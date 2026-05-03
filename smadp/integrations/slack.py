"""Slack incoming-webhook adapter (Block Kit)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from smadp.integrations.base import register_adapter
from smadp.schemas.webhooks import EventType, IntegrationKind, WebhookEnvelope


class SlackAdapter:
    kind = IntegrationKind.SLACK

    def _build_text(self, envelope: WebhookEnvelope) -> str:
        verdict_id = envelope.data.get("verdict_id", "n/a")
        if envelope.type == EventType.PASSPORT_GENERATED:
            return f"Passport generated for {verdict_id}"
        if envelope.type in {EventType.VERDICT_CREATED, EventType.VERDICT_UPDATED}:
            pair = envelope.data.get("agent_pair") or ["?", "?"]
            return f"Verdict updated: {pair[0]} ↔ {pair[1]}"
        return f"{envelope.type.value} ({verdict_id})"

    def translate(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> bytes:
        text = self._build_text(envelope)
        verdict_id = envelope.data.get("verdict_id", "n/a")
        score = envelope.data.get("composite_score")
        pair = envelope.data.get("agent_pair") or ["n/a", "n/a"]
        passport_url = envelope.data.get("passport_url")

        blocks: list[dict[str, Any]] = [
            {"type": "header", "text": {"type": "plain_text", "text": text}},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Verdict ID:* `{verdict_id}`"},
                    {"type": "mrkdwn", "text": f"*Pair:* `{pair[0]}` ↔ `{pair[1]}`"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Score:* {score if score is not None else 'n/a'}",
                    },
                    {"type": "mrkdwn", "text": f"*Event:* `{envelope.type.value}`"},
                ],
            },
        ]
        if isinstance(passport_url, str) and passport_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open passport"},
                            "url": passport_url,
                        }
                    ],
                }
            )
        payload = {"text": text, "blocks": blocks}
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def headers(self, envelope: WebhookEnvelope, *, config: Mapping[str, object]) -> dict[str, str]:
        return {"Content-Type": "application/json"}


register_adapter(SlackAdapter())


__all__ = ["SlackAdapter"]
