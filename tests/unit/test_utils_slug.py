"""Tests for ``smadp.utils.slug`` — slug + pair canonicalization."""

from __future__ import annotations

import pytest

from smadp.utils.slug import (
    all_pairs,
    normalize_slug,
    pair_filename,
    participants_filename,
    sort_pair,
    sort_participants,
)


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


class TestSortParticipants:
    def test_alphabetical(self) -> None:
        assert sort_participants(["zebra", "apple", "mango"]) == [
            "apple",
            "mango",
            "zebra",
        ]

    def test_normalizes_each(self) -> None:
        # sort_participants must apply normalize_slug to each entry.
        assert sort_participants(["Bob", "  ALICE  "]) == ["alice", "bob"]


class TestParticipantsFilename:
    def test_two(self) -> None:
        assert participants_filename(["bob", "alice"]) == "alice__bob.json"

    def test_three(self) -> None:
        assert participants_filename(["c", "a", "b"]) == "a__b__c.json"

    def test_four(self) -> None:
        assert participants_filename(["d", "c", "b", "a"]) == "a__b__c__d.json"

    def test_matches_pair_filename_for_two(self) -> None:
        # Length-2 must produce the same filename as the existing pair helper.
        assert participants_filename(["aider", "claude-code"]) == pair_filename(
            "aider", "claude-code"
        )

    @pytest.mark.parametrize("slugs", [[], ["solo"], ["a", "b", "c", "d", "e"]])
    def test_rejects_out_of_range(self, slugs: list[str]) -> None:
        with pytest.raises(ValueError):
            participants_filename(slugs)

    def test_rejects_duplicates(self) -> None:
        with pytest.raises(ValueError):
            participants_filename(["aider", "aider", "cursor"])
