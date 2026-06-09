"""Tests for GithubMetadataLanguageDetector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from smadp.autopilot.scaffolders.language_detector import (
    GithubMetadataLanguageDetector,
    Language,
)


def _fake_response(status: int, json_payload):
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=json_payload)
    return resp


def test_detects_python_from_pyproject_toml() -> None:
    det = GithubMetadataLanguageDetector(token=None)
    responses = [
        _fake_response(200, {"default_branch": "main"}),
        _fake_response(200, {"name": "pyproject.toml"}),
    ]
    with patch("smadp.autopilot.scaffolders.language_detector.httpx.get", side_effect=responses):
        assert det.detect(github_source="x/y") == Language.PYTHON


def test_detects_node_from_package_json() -> None:
    det = GithubMetadataLanguageDetector(token=None)
    responses = [
        _fake_response(200, {"default_branch": "main"}),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(200, {"name": "package.json"}),
    ]
    with patch("smadp.autopilot.scaffolders.language_detector.httpx.get", side_effect=responses):
        assert det.detect(github_source="x/y") == Language.NODE


def test_detects_go_from_go_mod() -> None:
    det = GithubMetadataLanguageDetector(token=None)
    responses = [
        _fake_response(200, {"default_branch": "main"}),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(200, {"name": "go.mod"}),
    ]
    with patch("smadp.autopilot.scaffolders.language_detector.httpx.get", side_effect=responses):
        assert det.detect(github_source="x/y") == Language.GO


def test_detects_rust_from_cargo_toml() -> None:
    det = GithubMetadataLanguageDetector(token=None)
    responses = [
        _fake_response(200, {"default_branch": "main"}),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(404, None),
        _fake_response(200, {"name": "Cargo.toml"}),
    ]
    with patch("smadp.autopilot.scaffolders.language_detector.httpx.get", side_effect=responses):
        assert det.detect(github_source="x/y") == Language.RUST


def test_returns_unsupported_when_no_manifest_matches() -> None:
    det = GithubMetadataLanguageDetector(token=None)
    call_count = {"n": 0}

    def _side_effect(*_args: object, **_kwargs: object):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _fake_response(200, {"default_branch": "main"})
        return _fake_response(404, None)

    with patch(
        "smadp.autopilot.scaffolders.language_detector.httpx.get",
        side_effect=_side_effect,
    ):
        assert det.detect(github_source="x/y") == Language.UNSUPPORTED


def test_detects_python_from_monorepo_classic_subdir() -> None:
    """AutoGPT-style: root has no manifest; classic/pyproject.toml does."""
    det = GithubMetadataLanguageDetector(token=None)

    def _side_effect(url: str, *_args: object, **kwargs: object):
        if url.endswith("/repos/Significant-Gravitas/AutoGPT"):
            return _fake_response(200, {"default_branch": "master"})
        params = kwargs.get("params") or {}
        if "/contents/classic/pyproject.toml" in url and params.get("ref") == "master":
            return _fake_response(200, {"name": "pyproject.toml"})
        return _fake_response(404, None)

    with patch(
        "smadp.autopilot.scaffolders.language_detector.httpx.get",
        side_effect=_side_effect,
    ):
        assert det.detect(github_source="Significant-Gravitas/AutoGPT") == Language.PYTHON


def test_detects_python_from_monorepo_libs_subdir() -> None:
    """langgraph-style: root has no manifest; libs/<repo>/pyproject.toml does."""
    det = GithubMetadataLanguageDetector(token=None)

    def _side_effect(url: str, *_args: object, **_kwargs: object):
        if url.endswith("/repos/langchain-ai/langgraph"):
            return _fake_response(200, {"default_branch": "main"})
        if "/contents/libs/langgraph/pyproject.toml" in url:
            return _fake_response(200, {"name": "pyproject.toml"})
        return _fake_response(404, None)

    with patch(
        "smadp.autopilot.scaffolders.language_detector.httpx.get",
        side_effect=_side_effect,
    ):
        assert det.detect(github_source="langchain-ai/langgraph") == Language.PYTHON


def test_invalid_github_source_raises() -> None:
    det = GithubMetadataLanguageDetector(token=None)
    with pytest.raises(ValueError):
        det.detect(github_source="")


def test_token_sent_in_authorization_header() -> None:
    det = GithubMetadataLanguageDetector(token="ghp_T")
    responses = [
        _fake_response(200, {"default_branch": "main"}),
        _fake_response(200, {"name": "pyproject.toml"}),
    ]
    with patch(
        "smadp.autopilot.scaffolders.language_detector.httpx.get", side_effect=responses
    ) as get:
        det.detect(github_source="x/y")
        for call in get.call_args_list:
            assert call.kwargs["headers"].get("Authorization") == "Bearer ghp_T"
