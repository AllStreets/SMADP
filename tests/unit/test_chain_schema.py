"""Chain schema — Pydantic + JSON Schema agreement."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from smadp.schemas import Chain

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "catalog" / "_meta" / "schema" / "1.0" / "chain.schema.json"


def _sub() -> dict:
    return {
        "severity": "low",
        "rationale": "Stub rationale.",
        "citations": [{"profile_field": "a.capabilities.execute_shell"}],
        "conditions": [],
        "mitigations": [],
    }


def _base(**overrides) -> dict:
    body = {
        "schema_version": "1.0",
        "chain_id": "c_demo-chain",
        "name": "Demo Chain",
        "topology": "linear",
        "participants": [
            {"slug": "agent-a", "role": "planner"},
            {"slug": "agent-b", "role": "executor"},
            {"slug": "agent-c", "role": "critic"},
        ],
        "edges": [
            {"from": "agent-a", "to": "agent-b", "channel": "prompt"},
            {"from": "agent-b", "to": "agent-c", "channel": "filesystem"},
        ],
        "headline": "Demo headline.",
        "sub_verdicts": {
            "A_prompt_injection": _sub(),
            "B_data_leakage": _sub(),
            "C_capability_conflict": _sub(),
            "D_cascading_error": _sub(),
            "E_compliance": _sub(),
        },
        "framework_mappings": {},
        "first_seen_at": "2026-05-04T00:00:00Z",
        "last_refreshed_at": "2026-05-04T00:00:00Z",
    }
    body.update(overrides)
    return body


def test_pydantic_round_trip() -> None:
    c = Chain.model_validate(_base())
    assert c.chain_id == "c_demo-chain"
    assert len(c.participants) == 3


def test_default_schema_version_is_1_1() -> None:
    body = _base()
    del body["schema_version"]
    c = Chain.model_validate(body)
    assert c.schema_version == "1.1"


def test_existing_1_0_chain_still_validates_with_empty_provenance() -> None:
    c = Chain.model_validate(_base(schema_version="1.0"))
    assert c.composed_from == []
    assert c.composition_method is None
    assert c.stale_reason is None


def test_1_1_chain_accepts_provenance_fields() -> None:
    c = Chain.model_validate(
        _base(
            schema_version="1.1",
            composition_method="deterministic-v1",
            composed_from=["v_2026-01-01_a__b_abcd"],
            stale_reason="capability_drift",
        )
    )
    assert c.composition_method == "deterministic-v1"
    assert c.composed_from == ["v_2026-01-01_a__b_abcd"]
    assert c.stale_reason == "capability_drift"


def test_pydantic_rejects_too_few_participants() -> None:
    with pytest.raises(ValidationError):
        Chain.model_validate(
            _base(
                participants=[
                    {"slug": "a", "role": "planner"},
                    {"slug": "b", "role": "executor"},
                ]
            )
        )


def test_pydantic_rejects_bad_topology() -> None:
    with pytest.raises(ValidationError):
        Chain.model_validate(_base(topology="mesh"))


def test_pydantic_rejects_bad_chain_id() -> None:
    with pytest.raises(ValidationError):
        Chain.model_validate(_base(chain_id="bad-id"))


def test_json_schema_accepts_valid() -> None:
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    Draft202012Validator(schema).validate(_base())


def test_json_schema_rejects_missing_required() -> None:
    body = _base()
    del body["topology"]
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(body))
    assert errors
