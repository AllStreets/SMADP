"""Tests for the malware-lure filter (smadp.catalog.lures)."""

from __future__ import annotations

import pytest

from smadp.catalog.lures import lure_reason


@pytest.mark.parametrize(
    "slug",
    [
        "github-copilot-cracked",
        "acrobat-pro-2026-activate",
        "awesome-piracy",
        "some-tool-keygen",
        "krisp-2026",
    ],
)
def test_lure_slugs_are_caught(slug: str) -> None:
    assert lure_reason({"slug": slug}) is not None


@pytest.mark.parametrize(
    "slug",
    [
        "delta-activations",
        "leads-reactivation-with-ai-voice-agent",
        "awesome-serialization",
        "aider",
    ],
)
def test_legitimate_slugs_pass(slug: str) -> None:
    assert lure_reason({"slug": slug}) is None


def test_lure_phrase_in_description_is_caught() -> None:
    profile = {
        "slug": "harmless-name",
        "onexus": {"description": "The premier utility for unlocking advanced gameplay mechanics."},
    }
    assert lure_reason(profile) is not None


def test_hd_wallet_keygen_tag_alone_does_not_trip() -> None:
    # Tags are not scanned: "keygen" is a normal term for HD-wallet key derivation.
    profile = {"slug": "ethereum-wallet-toolkit", "onexus": {"tags": ["keygen", "hd-wallet"]}}
    assert lure_reason(profile) is None
