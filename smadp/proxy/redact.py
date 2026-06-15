"""Secret redaction for recorded MCP messages.

Reuses the existing real-secret detection rules from
``smadp.sandbox.policy`` (``_REAL_SECRET_PATTERNS``) so the proxy and the
sandbox share one canonical secret vocabulary — patterns never drift apart.
This transformer is additive: ``policy`` detects; we rewrite matches to
``***REDACTED***`` so a recording can be content-addressed and stored as
evidence without persisting live credentials.
"""

from __future__ import annotations

from typing import Any

from smadp.sandbox.policy import _REAL_SECRET_PATTERNS

_PLACEHOLDER = "***REDACTED***"


def _redact_str(value: str) -> str:
    out = value
    for pat in _REAL_SECRET_PATTERNS:
        out = pat.sub(_PLACEHOLDER, out)
    return out


def redact_secrets(obj: Any) -> Any:
    """Return a deep copy of ``obj`` with any real-secret substrings rewritten.

    Recurses dicts/lists; leaves non-string scalars untouched. Never mutates
    the input.
    """
    if isinstance(obj, str):
        return _redact_str(obj)
    if isinstance(obj, dict):
        return {k: redact_secrets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_secrets(v) for v in obj]
    return obj


__all__ = ["redact_secrets"]
