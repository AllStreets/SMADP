"""Plan 5 headline integration: dispute REEVAL → DISPUTE refresh → both webhooks.

A vendor files a dispute, the operator triages it as SUBSTANTIVE then resolves
it as REEVAL. The resolution should:

* emit a ``dispute.resolved`` transparency event (Plan 4 → Plan 5 contract)
* enqueue a ``trigger=DISPUTE`` refresh row

When the refresh evaluator drains that row and the regenerated verdict
surfaces a new risk, both ``verdict.updated`` and
``framework_coverage.changed`` webhooks must fire.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from smadp.catalog.repo import CatalogRepo
from smadp.config import Config
from smadp.refresh import evaluator, queue
from smadp.schemas.dispute import DisputeDecision, RequestedOutcome
from smadp.schemas.refresh import RefreshTrigger
from smadp.schemas.verdict import Verdict
from smadp.vendor import store as vendor_store


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SMADP_KEK_MASTER", "x" * 64)
    monkeypatch.setenv("SMADP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SMADP_CATALOG", str(tmp_path / "catalog"))
    cfg = Config()
    cfg.catalog_dir.mkdir(parents=True, exist_ok=True)
    (cfg.catalog_dir / "verdicts").mkdir(parents=True, exist_ok=True)
    return cfg


def _build(sample: dict[str, Any], *, zero_severity: bool) -> Verdict:
    payload = dict(sample)
    payload["pair"] = tuple(payload["pair"])
    if zero_severity:
        payload["sub_verdicts"] = {
            k: {**v, "severity": "none"} for k, v in payload["sub_verdicts"].items()
        }
    return Verdict.model_validate(payload)


def test_dispute_reeval_drives_refresh_with_framework_coverage_delta(
    cfg: Config, sample_verdict: dict[str, Any]
) -> None:
    old = _build(sample_verdict, zero_severity=True)
    new = _build(sample_verdict, zero_severity=False)
    slug_a, slug_b = old.pair
    verdict_id = f"{slug_a}__{slug_b}"
    CatalogRepo(config=cfg).save_verdict(old)

    d = vendor_store.file_dispute(
        workspace_id="ws_TESTWS01",
        verdict_id=verdict_id,
        vendor_user_id="vendor-1",
        argument_md="reasonable challenge",
        requested_outcome=RequestedOutcome.REEVAL,
        config=cfg,
    )
    vendor_store.update_dispute_status(
        dispute_id=d.id,
        decision=DisputeDecision.SUBSTANTIVE,
        rationale_md=None,
        config=cfg,
    )
    vendor_store.update_dispute_status(
        dispute_id=d.id,
        decision=DisputeDecision.REEVAL,
        rationale_md="upheld on merit",
        config=cfg,
    )

    pending = queue.list_pending(config=cfg)
    assert len(pending) == 1
    assert pending[0].trigger is RefreshTrigger.DISPUTE
    assert pending[0].verdict_id == verdict_id

    async def fake_generate(*_args: Any, **_kw: Any) -> Verdict:
        return new

    with (
        patch(
            "smadp.refresh.evaluator._reload_inputs",
            return_value={"profile_a": object(), "profile_b": object(), "evidence": {}},
        ),
        patch("smadp.refresh.evaluator.generate_verdict", side_effect=fake_generate),
        patch("smadp.refresh.evaluator._emit_transparency"),
        patch("smadp.refresh.evaluator._dispatch_verdict_updated") as vu_mock,
        patch("smadp.refresh.evaluator._dispatch_framework_coverage_changed") as fc_mock,
    ):
        item = evaluator.drain_one(config=cfg)

    assert item is not None and item.trigger is RefreshTrigger.DISPUTE
    vu_mock.assert_called_once()
    fc_mock.assert_called_once()

    delta = fc_mock.call_args.kwargs["delta"]
    assert "owasp_llm_top_10" in delta["added"]
    assert "LLM01" in delta["added"]["owasp_llm_top_10"]
    assert delta["removed"] == {}
    assert queue.list_pending(config=cfg) == []
