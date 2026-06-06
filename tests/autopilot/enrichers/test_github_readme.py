"""Tests for GithubReadmeFetcher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from smadp.autopilot.enrichers.github_readme import (
    GithubReadmeFetcher,
    ReadmeFetchError,
)


@pytest.fixture
def fetcher(tmp_path: Path) -> GithubReadmeFetcher:
    return GithubReadmeFetcher(cache_dir=tmp_path / "cache", token=None)


def _fake_response(status: int, body: bytes):
    resp = MagicMock()
    resp.status_code = status
    resp.content = body
    resp.text = body.decode("utf-8", errors="replace")
    if 200 <= status < 300:
        resp.raise_for_status = MagicMock(return_value=None)
    else:
        resp.raise_for_status = MagicMock(side_effect=Exception(f"HTTP {status}"))
    return resp


def test_fetch_caches_first_call(fetcher: GithubReadmeFetcher) -> None:
    with patch("smadp.autopilot.enrichers.github_readme.httpx.get") as get:
        get.return_value = _fake_response(200, b"# Hello\n\nReadme body.")
        text1 = fetcher.fetch("paul-gauthier/aider")
        text2 = fetcher.fetch("paul-gauthier/aider")
        assert text1 == "# Hello\n\nReadme body."
        assert text2 == text1
        assert get.call_count == 1


def test_fetch_tries_master_when_head_404s(fetcher: GithubReadmeFetcher) -> None:
    responses = [_fake_response(404, b""), _fake_response(200, b"# master")]
    with patch("smadp.autopilot.enrichers.github_readme.httpx.get", side_effect=responses) as get:
        text = fetcher.fetch("owner/repo")
        assert text == "# master"
        assert get.call_count == 2


def test_fetch_raises_when_both_branches_404(fetcher: GithubReadmeFetcher) -> None:
    responses = [_fake_response(404, b""), _fake_response(404, b"")]
    with patch("smadp.autopilot.enrichers.github_readme.httpx.get", side_effect=responses):
        with pytest.raises(ReadmeFetchError):
            fetcher.fetch("owner/repo")


def test_fetch_uses_token_when_provided(tmp_path: Path) -> None:
    fetcher = GithubReadmeFetcher(cache_dir=tmp_path / "cache", token="ghp_TEST")
    with patch("smadp.autopilot.enrichers.github_readme.httpx.get") as get:
        get.return_value = _fake_response(200, b"# Authed")
        fetcher.fetch("owner/repo")
        kwargs = get.call_args.kwargs
        headers = kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer ghp_TEST"


def test_fetch_short_circuits_on_empty_github_source(fetcher: GithubReadmeFetcher) -> None:
    with pytest.raises(ReadmeFetchError):
        fetcher.fetch("")
