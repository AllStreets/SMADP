"""Shared pytest fixtures for the SMADP test suite.

The catalog data shipped with the repo is treated as authoritative test
fixture material; tests load it directly. Tests that mutate state must use
``tmp_catalog`` (a per-test copy) so the seed catalog stays clean.

The Anthropic SDK is the only external dependency we mock — every other
component (catalog, schemas, scoring, sandbox queue) is exercised against
real on-disk data.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------- repo
@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the SMADP repository root."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def catalog_dir(repo_root: Path) -> Path:
    """Absolute path to the seed catalog directory."""
    return repo_root / "catalog"


# --------------------------------------------------------------- seed loaders
@pytest.fixture(scope="session")
def profiles_dir(catalog_dir: Path) -> Path:
    return catalog_dir / "profiles"


@pytest.fixture(scope="session")
def verdicts_dir(catalog_dir: Path) -> Path:
    return catalog_dir / "verdicts"


@pytest.fixture(scope="session")
def evidence_dir(catalog_dir: Path) -> Path:
    return catalog_dir / "_evidence"


@pytest.fixture(scope="session")
def chronicle_dir(catalog_dir: Path) -> Path:
    return catalog_dir / "_chronicle"


@pytest.fixture(scope="session")
def schema_dir(catalog_dir: Path) -> Path:
    return catalog_dir / "_meta" / "schema" / "1.0"


@pytest.fixture(scope="session")
def all_profile_paths(profiles_dir: Path) -> list[Path]:
    return sorted(p for p in profiles_dir.glob("*.json") if p.is_file())


@pytest.fixture(scope="session")
def all_verdict_paths(verdicts_dir: Path) -> list[Path]:
    return sorted(p for p in verdicts_dir.glob("*__*.json") if p.is_file())


@pytest.fixture(scope="session")
def all_evidence_paths(evidence_dir: Path) -> list[Path]:
    return sorted(p for p in evidence_dir.glob("sha256-*.json") if p.is_file())


@pytest.fixture(scope="session")
def all_chronicle_paths(chronicle_dir: Path) -> list[Path]:
    return sorted(p for p in chronicle_dir.glob("*.jsonl") if p.is_file())


@pytest.fixture(scope="session")
def sample_profile(profiles_dir: Path) -> dict[str, Any]:
    """Loaded JSON for `claude-code.json` — a known-good seed profile."""
    with (profiles_dir / "claude-code.json").open("r", encoding="utf-8") as fh:
        data: Any = json.load(fh)
    assert isinstance(data, dict), "sample profile is not a JSON object"
    return data


@pytest.fixture(scope="session")
def sample_verdict(all_verdict_paths: list[Path]) -> dict[str, Any]:
    """Loaded JSON for the first verdict on disk (alphabetical order)."""
    assert all_verdict_paths, "no verdicts in catalog"
    with all_verdict_paths[0].open("r", encoding="utf-8") as fh:
        data: Any = json.load(fh)
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="session")
def sample_evidence(all_evidence_paths: list[Path]) -> dict[str, Any]:
    """Loaded JSON for the first evidence file (alphabetical)."""
    assert all_evidence_paths, "no evidence in catalog"
    with all_evidence_paths[0].open("r", encoding="utf-8") as fh:
        data: Any = json.load(fh)
    assert isinstance(data, dict)
    return data


# ----------------------------------------------------------- mutable catalog
@pytest.fixture()
def tmp_catalog(tmp_path: Path, catalog_dir: Path) -> Path:
    """A per-test copy of the seed catalog under ``tmp_path/catalog``.

    Tests that mutate state should point ``$SMADP_CATALOG`` at this path
    (or pass a ``Config`` whose ``catalog_dir`` is set to it).
    """
    dest = tmp_path / "catalog"
    shutil.copytree(catalog_dir, dest)
    return dest


@pytest.fixture()
def tmp_catalog_env(tmp_catalog: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Same as ``tmp_catalog`` but also sets ``$SMADP_CATALOG`` in the env."""
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_catalog))
    return tmp_catalog


# --------------------------------------------------------- env hygiene shim
@pytest.fixture(autouse=True)
def _no_real_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure no test accidentally depends on a real Anthropic key."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# --------------------------------------------------------- LLM client mock
class FakeAsyncAnthropic:
    """Drop-in fake for ``anthropic.AsyncAnthropic`` used in unit tests.

    The fake does not perform any I/O. ``messages.create`` returns a
    deterministic ``Message``-shaped object whose single ``content`` block is
    a ``ToolUseBlock`` carrying a caller-supplied ``tool_input``.
    """

    def __init__(self, tool_input: dict[str, Any] | None = None) -> None:
        self._tool_input = tool_input or {}
        self.messages = _FakeMessages(self._tool_input)


class _FakeMessages:
    def __init__(self, tool_input: dict[str, Any]) -> None:
        self._tool_input = tool_input

    async def create(self, **kwargs: Any) -> Any:
        from anthropic.types import Message, ToolUseBlock, Usage  # late import

        # Pull out the tool_choice's tool name to label the response block.
        tool_choice = kwargs.get("tool_choice", {})
        tool_name = tool_choice.get("name", "emit_profile")
        block = ToolUseBlock(
            type="tool_use",
            id="toolu_fake_0001",
            name=tool_name,
            input=self._tool_input,
        )
        usage = Usage(input_tokens=1, output_tokens=1)
        return Message(
            id="msg_fake",
            type="message",
            role="assistant",
            content=[block],
            model=kwargs.get("model", "claude-sonnet-4-6"),
            stop_reason="tool_use",
            stop_sequence=None,
            usage=usage,
        )


@pytest.fixture()
def fake_anthropic() -> type[FakeAsyncAnthropic]:
    """Expose the fake so tests can build instances with custom tool_inputs."""
    return FakeAsyncAnthropic
