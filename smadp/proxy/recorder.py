"""Recording session: collect redacted MCP messages -> content-addressed evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from smadp.proxy.redact import redact_secrets
from smadp.utils.time import utcnow

KILL_SWITCH = "PROXY_DISABLED"


@dataclass
class RecordingRecord:
    sha256: str
    message_count: int
    path: Path


@dataclass
class RecordingSession:
    slug: str
    evidence_dir: Path
    messages: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def is_disabled(*, state_dir: Path) -> bool:
        return (state_dir / KILL_SWITCH).exists()

    @staticmethod
    def sha_for(messages: list[dict[str, Any]]) -> str:
        canonical = json.dumps(
            messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def observe(self, message: dict[str, Any], *, direction: str) -> None:
        self.messages.append({"direction": direction, "message": redact_secrets(message)})

    def finalize(self) -> RecordingRecord:
        sha = self.sha_for(self.messages)
        blob = {
            "kind": "mcp-recording",
            "slug": self.slug,
            "recorded_at": utcnow().isoformat(timespec="seconds").replace("+00:00", "Z"),
            "messages": self.messages,
        }
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"sha256-{sha}.json"
        if not path.exists():
            path.write_text(
                json.dumps(blob, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return RecordingRecord(sha256=sha, message_count=len(self.messages), path=path)


__all__ = ["KILL_SWITCH", "RecordingRecord", "RecordingSession"]
