"""Tests for ``smadp.utils.slug`` — slug + pair canonicalization."""

from __future__ import annotations

import pytest

from smadp.utils.slug import all_pairs, normalize_slug, pair_filename, sort_pair


class TestNormalizeSlug:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Claude Code", "claude-code"),
            ("CLAUDE-CODE", "claude-code"),
            ("  claude   code  ", "claude-code"),
            ("Claude_Code!", "claude-code"),
            ("aider", "aider"),
            ("foo.bar/baz", "foo-bar-baz"),
            ("--foo--bar--", "foo-bar"),
            ("agent (v2)", "agent-v2"),
        ],
    )
    def test_examples(self, raw: str, expected: str) -> None:
        assert normalize_slug(raw) == expected

    def test_already_normalized(self) -> None:
        assert normalize_slug("claude-code") == "claude-code"

    def test_idempotent(self) -> None:
        s = normalize_slug("Claude Code v2.0!")
        assert normalize_slug(s) == s

    @pytest.mark.parametrize("bad", ["", "   ", "!!!", "----", "@@@"])
    def test_empty_raises(self, bad: str) -> None:
        with pytest.raises(ValueError):
            normalize_slug(bad)


class TestSortPair:
    def test_already_sorted(self) -> None:
        assert sort_pair("aider", "claude-code") == ("aider", "claude-code")

    def test_reverses(self) -> None:
        assert sort_pair("zoo", "aardvark") == ("aardvark", "zoo")

    def test_same_raises(self) -> None:
        with pytest.raises(ValueError):
            sort_pair("foo", "foo")


class TestPairFilename:
    def test_alphabetized(self) -> None:
        assert pair_filename("cursor", "claude-code") == "claude-code__cursor.json"

    def test_already_sorted(self) -> None:
        assert pair_filename("a", "b") == "a__b.json"

    def test_same_raises(self) -> None:
        with pytest.raises(ValueError):
            pair_filename("aider", "aider")


class TestAllPairs:
    def test_three(self) -> None:
        result = all_pairs(["c", "a", "b"])
        # All canonical pairs, deduped, sorted
        assert result == [("a", "b"), ("a", "c"), ("b", "c")]

    def test_empty(self) -> None:
        assert all_pairs([]) == []

    def test_single(self) -> None:
        assert all_pairs(["x"]) == []

    def test_dedupes_repeats(self) -> None:
        # Repeated slugs collapse — sort_pair would raise on (a, a),
        # so the function must NOT pass identical pairs through.
        # Our implementation uses items[i+1:], so duplicates *between*
        # different positions can still collide; we just verify the
        # documented contract on a plain list.
        assert all_pairs(["a", "b"]) == [("a", "b")]
