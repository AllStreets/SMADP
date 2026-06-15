"""Redaction rewrites real secrets in recorded messages, reusing policy patterns."""
from __future__ import annotations

from smadp.proxy.redact import redact_secrets
from smadp.sandbox.policy import looks_like_real_secret


def test_redacts_api_key_in_nested_params() -> None:
    msg = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "http_get",
            "arguments": {"headers": {"Authorization": "Bearer sk-ABCDEFGHIJKLMNOPQRSTUV"}},
        },
    }
    out = redact_secrets(msg)
    leaked = out["params"]["arguments"]["headers"]["Authorization"]
    assert "sk-ABCDEFGHIJKLMNOPQRSTUV" not in leaked
    assert "***REDACTED***" in leaked
    assert "sk-ABCDEFGHIJKLMNOPQRSTUV" in msg["params"]["arguments"]["headers"]["Authorization"]


def test_redacts_inside_lists_and_preserves_structure() -> None:
    msg = {"result": {"content": ["ghp_" + "a" * 36, "harmless text"]}}
    out = redact_secrets(msg)
    assert out["result"]["content"][0] == "***REDACTED***"
    assert out["result"]["content"][1] == "harmless text"


def test_no_secret_is_a_noop_equal_copy() -> None:
    msg = {"method": "tools/list", "params": {"x": 1, "y": ["a", "b"]}}
    assert redact_secrets(msg) == msg


def test_uses_same_detector_as_policy() -> None:
    assert looks_like_real_secret("AKIA" + "A" * 16) is True
    assert redact_secrets({"k": "AKIA" + "A" * 16})["k"] == "***REDACTED***"
