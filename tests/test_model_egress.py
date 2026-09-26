"""Model egress: off by default, one host, announced.

The adversarial scenarios declare an empty egress list, which becomes
--network none. That is right for a scenario about exfiltration and wrong for
every LLM agent, which cannot act without reaching a model. Under those
scenarios a real agent times out and the run grades as though no attack
succeeded, which is indistinguishable in the record from agents that resisted.
"""
from __future__ import annotations

import pytest

from smadp.sandbox.runner import MODEL_EGRESS_ENV, _effective_egress
from smadp.sandbox.scenarios import load_scenario


def _adversarial():
    return load_scenario("induced_execution")


def _cooperative():
    return load_scenario("calendar_email")


def test_default_is_unchanged(monkeypatch) -> None:
    monkeypatch.delenv(MODEL_EGRESS_ENV, raising=False)
    s = _adversarial()
    assert _effective_egress(s) == tuple(s.allow_egress)
    assert _effective_egress(s) == ()


def test_a_named_host_is_added_and_announced(monkeypatch) -> None:
    monkeypatch.setenv(MODEL_EGRESS_ENV, "host.docker.internal:11434")
    with pytest.warns(UserWarning, match="egress extended"):
        egress = _effective_egress(_adversarial())
    # The port is stripped: egress rules are per host.
    assert egress == ("host.docker.internal",)


def test_a_url_is_reduced_to_its_host(monkeypatch) -> None:
    monkeypatch.setenv(MODEL_EGRESS_ENV, "localhost:11434/v1")
    with pytest.warns(UserWarning):
        assert _effective_egress(_adversarial()) == ("localhost",)


def test_a_scenario_that_already_allows_the_host_is_untouched(monkeypatch) -> None:
    s = _cooperative()
    existing = s.allow_egress[0]
    monkeypatch.setenv(MODEL_EGRESS_ENV, existing)
    # No warning, because nothing was widened.
    assert _effective_egress(s) == tuple(s.allow_egress)


def test_the_cooperative_allowlist_is_preserved(monkeypatch) -> None:
    """Adding a model host must extend, never replace: a scenario that needs
    its own hosts still gets them."""
    monkeypatch.setenv(MODEL_EGRESS_ENV, "host.docker.internal")
    s = _cooperative()
    with pytest.warns(UserWarning):
        egress = _effective_egress(s)
    for host in s.allow_egress:
        assert host in egress
    assert "host.docker.internal" in egress


def test_an_empty_value_is_ignored(monkeypatch) -> None:
    monkeypatch.setenv(MODEL_EGRESS_ENV, "   ")
    assert _effective_egress(_adversarial()) == ()
