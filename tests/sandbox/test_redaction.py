"""Argv redaction: real-secret env values must not be persisted to transcripts."""

from __future__ import annotations

from smadp.sandbox.runner import _redact_argv_for_log


def test_redacts_openai_api_key_value() -> None:
    argv = [
        "docker", "run", "--rm",
        "--env", "OPENAI_API_KEY=sk-proj-abc123-secret",
        "--env", "SMADP_AGENT_ROLE=calendar",
        "--env", "SMADP_TEST_CALENDAR_TOKEN=synthetic-test-only-aaa",
        "image@sha256:00", "aider",
    ]
    out = _redact_argv_for_log(argv)
    joined = " ".join(out)
    assert "sk-proj-abc123-secret" not in joined
    assert "OPENAI_API_KEY=***" in joined
    # Synthetic / non-allowlisted env values must pass through unchanged.
    assert "SMADP_AGENT_ROLE=calendar" in joined
    assert "SMADP_TEST_CALENDAR_TOKEN=synthetic-test-only-aaa" in joined
    # Structure is preserved.
    assert len(out) == len(argv)


def test_does_not_redact_non_allowlisted_keys() -> None:
    argv = ["docker", "run", "--env", "MY_OTHER_KEY=plaintext", "image", "cmd"]
    assert _redact_argv_for_log(argv) == argv


def test_handles_dangling_env_flag() -> None:
    argv = ["docker", "run", "--env"]
    assert _redact_argv_for_log(argv) == argv
