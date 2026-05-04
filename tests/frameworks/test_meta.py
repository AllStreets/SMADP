"""Sanity tests for the catalog/_meta/frameworks.json fixture."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRAMEWORKS_JSON = REPO_ROOT / "catalog" / "_meta" / "frameworks.json"

EXPECTED_IDS = {
    # Pre-existing (referenced by catalog/verdicts/*.json — do not rename)
    "nist_ai_rmf",
    "iso_42001",
    "owasp_llm_top_10",
    # Plan 5 additions
    "eu_ai_act",
    "soc_2",
    "hipaa",
    "pci_dss",
    "gdpr",
    "fedramp_moderate",
    "caiq_sig",
    "nist_csf_2",
}

VALID_RISKS = {
    "A_prompt_injection",
    "B_data_leakage",
    "C_capability_conflict",
    "D_cascading_error",
    "E_compliance",
}


def _load() -> dict[str, dict]:
    raw = json.loads(FRAMEWORKS_JSON.read_text("utf-8"))
    if isinstance(raw, dict) and "frameworks" in raw:
        items = raw["frameworks"]
    elif isinstance(raw, list):
        items = raw
    else:
        items = list(raw.values())
    return {f["id"]: f for f in items}


def test_all_expected_frameworks_present() -> None:
    data = _load()
    assert set(data.keys()) == EXPECTED_IDS


def test_every_control_has_applies_to_risks_in_taxonomy() -> None:
    data = _load()
    for fw_id, fw in data.items():
        controls = fw.get("controls", [])
        assert controls, f"{fw_id} has no controls"
        for c in controls:
            assert "id" in c and "name" in c, f"{fw_id} control missing id/name"
            risks = c.get("applies_to_risks", [])
            assert risks, f"{fw_id}/{c['id']} missing applies_to_risks"
            for r in risks:
                assert r in VALID_RISKS, f"{fw_id}/{c['id']} unknown risk {r}"


def test_schema_version_present() -> None:
    raw = json.loads(FRAMEWORKS_JSON.read_text("utf-8"))
    assert isinstance(raw, dict)
    assert raw.get("schema_version") == "1.0"
    assert isinstance(raw.get("frameworks"), list)
