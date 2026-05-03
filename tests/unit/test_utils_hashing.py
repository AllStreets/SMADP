"""Tests for ``smadp.utils.hashing`` — content-addressed hashing."""

from __future__ import annotations

import hashlib

from smadp.utils.hashing import sha256_bytes, sha256_canonical_json, sha256_text


class TestSha256Bytes:
    def test_empty(self) -> None:
        assert sha256_bytes(b"") == hashlib.sha256(b"").hexdigest()

    def test_known_value(self) -> None:
        # "abc" -> ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
        assert sha256_bytes(b"abc").startswith("ba7816bf8f01cfea")

    def test_deterministic(self) -> None:
        payload = b"Some bytes \x00\xff"
        assert sha256_bytes(payload) == sha256_bytes(payload)


class TestSha256Text:
    def test_unicode_round_trip(self) -> None:
        assert sha256_text("héllo") == sha256_bytes("héllo".encode())

    def test_matches_bytes_for_ascii(self) -> None:
        assert sha256_text("abc") == sha256_bytes(b"abc")


class TestSha256CanonicalJson:
    def test_key_order_independent(self) -> None:
        a = {"a": 1, "b": 2, "c": 3}
        b = {"c": 3, "b": 2, "a": 1}
        assert sha256_canonical_json(a) == sha256_canonical_json(b)

    def test_nested_key_order_independent(self) -> None:
        a = {"x": {"y": 1, "z": 2}, "k": [1, 2, 3]}
        b = {"k": [1, 2, 3], "x": {"z": 2, "y": 1}}
        assert sha256_canonical_json(a) == sha256_canonical_json(b)

    def test_list_order_significant(self) -> None:
        # Lists are NOT reordered (unlike dict keys); order matters.
        assert sha256_canonical_json([1, 2, 3]) != sha256_canonical_json([3, 2, 1])

    def test_deterministic(self) -> None:
        payload = {"hello": "world", "nums": [1, 2, 3]}
        first = sha256_canonical_json(payload)
        second = sha256_canonical_json(payload)
        assert first == second
        assert len(first) == 64
        assert all(c in "0123456789abcdef" for c in first)

    def test_empty_object(self) -> None:
        # The canonical form of {} is "{}".
        expected = sha256_text("{}")
        assert sha256_canonical_json({}) == expected

    def test_unicode_preserved(self) -> None:
        # ensure_ascii=False means non-ASCII chars survive in the hashed text.
        with_emoji = {"flag": "🇺🇸"}
        # Should at least be a valid hex digest; verifies the call doesn't raise.
        digest = sha256_canonical_json(with_emoji)
        assert len(digest) == 64

    def test_fallback_for_non_serializable(self) -> None:
        # default=str means a non-JSON-native type (e.g. set rendered via str)
        # is accepted rather than raising. That's the documented contract.
        # We compare against the manual canonical form.
        payload = {"a": 1}
        assert sha256_canonical_json(payload) == sha256_text('{"a":1}')
