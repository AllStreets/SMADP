"""API-key passthrough: load `~/.smadp/keys.env`, intersect with allowlist."""

from __future__ import annotations

from pathlib import Path

import pytest

from smadp.sandbox import keys


def _write_keys(p: Path, content: str) -> Path:
    p.write_text(content, encoding="utf-8")
    p.chmod(0o600)
    return p


def test_parses_simple_key_value(tmp_path: Path) -> None:
    f = _write_keys(tmp_path / "k.env", "OPENAI_API_KEY=sk-abc\nMY_PERSONAL_TOKEN=ignored\n")
    loaded = keys.load_keys_file(f)
    assert loaded == {"OPENAI_API_KEY": "sk-abc", "MY_PERSONAL_TOKEN": "ignored"}


def test_strips_quotes_and_comments(tmp_path: Path) -> None:
    f = _write_keys(
        tmp_path / "k.env",
        "# top comment\nOPENAI_API_KEY=\"sk-abc\"\n\nAIDER_MODEL='gpt-5.4-mini'\n# trailing\n",
    )
    loaded = keys.load_keys_file(f)
    assert loaded == {"OPENAI_API_KEY": "sk-abc", "AIDER_MODEL": "gpt-5.4-mini"}


def test_filter_to_allowlist_drops_unknown_keys(tmp_path: Path) -> None:
    raw = {"OPENAI_API_KEY": "x", "MY_PERSONAL_TOKEN": "y", "ANTHROPIC_API_KEY": "z"}
    out = keys.filter_to_allowlist(raw)
    assert out == {"OPENAI_API_KEY": "x"}


def test_allowlist_is_openai_only() -> None:
    assert keys.KEY_ALLOWLIST == frozenset({"OPENAI_API_KEY"})


def test_compute_env_for_adapter_passes_only_required_and_optional(tmp_path: Path) -> None:
    loaded = {"OPENAI_API_KEY": "sk-x", "ANTHROPIC_API_KEY": "sk-ant-y", "DEEPSEEK_API_KEY": "sk-d"}
    env, missing = keys.compute_env_for_adapter(
        loaded,
        env_required=["OPENAI_API_KEY"],
        env_optional=["AIDER_MODEL"],
    )
    assert env == {"OPENAI_API_KEY": "sk-x"}
    assert missing == []


def test_missing_required_returns_missing_list(tmp_path: Path) -> None:
    loaded = {"ANTHROPIC_API_KEY": "sk-ant-y"}
    env, missing = keys.compute_env_for_adapter(
        loaded,
        env_required=["OPENAI_API_KEY"],
        env_optional=[],
    )
    assert env == {}
    assert missing == ["OPENAI_API_KEY"]


def test_warns_on_loose_mode(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    f = tmp_path / "k.env"
    f.write_text("OPENAI_API_KEY=sk-abc\n")
    f.chmod(0o644)
    with caplog.at_level("WARNING"):
        keys.load_keys_file(f)
    assert any("permissive" in r.message.lower() or "0644" in r.message for r in caplog.records)


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    assert keys.load_keys_file(tmp_path / "absent.env") == {}
