"""`GET /api/frameworks` — framework controls and which verdicts cite them."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from smadp.api.models import Framework, FrameworkControl, FrameworksResponse
from smadp.catalog.repo import CatalogRepo

router = APIRouter(tags=["frameworks"])


@router.get(
    "/frameworks",
    response_model=FrameworksResponse,
    summary="List frameworks (NIST AI RMF, ISO 42001, OWASP LLM Top 10) with verdict crosslinks",
)
async def list_frameworks(request: Request) -> FrameworksResponse:
    cfg = request.app.state.config
    path = cfg.meta_dir / "frameworks.json"
    if not path.exists():
        raise HTTPException(status_code=500, detail="frameworks.json not present in catalog/_meta")
    with path.open("r", encoding="utf-8") as fh:
        meta = json.load(fh)

    repo = CatalogRepo(cfg)
    # Map control id -> list of "a__b" pair refs
    control_to_pairs: dict[str, list[str]] = defaultdict(list)
    for verdict in repo.list_verdicts():
        ref = f"{verdict.pair[0]}__{verdict.pair[1]}"
        for _framework_id, control_ids in verdict.framework_mappings.items():
            for cid in control_ids:
                control_to_pairs[cid].append(ref)

    frameworks: list[Framework] = []
    for framework in meta.get("frameworks", []):
        controls: list[FrameworkControl] = []
        for control in framework.get("controls", []):
            cid = control.get("id", "")
            controls.append(
                FrameworkControl(
                    id=cid,
                    name=control.get("name", ""),
                    applies_to_risks=list(control.get("applies_to_risks", [])),
                    verdicts=sorted(set(control_to_pairs.get(cid, []))),
                )
            )
        frameworks.append(
            Framework(
                id=framework.get("id", ""),
                name=framework.get("name", ""),
                version=str(framework.get("version", "")),
                url=framework.get("url", ""),
                controls=controls,
            )
        )
    return FrameworksResponse(frameworks=frameworks)


@router.get("/frameworks/raw", summary="Raw frameworks.json", include_in_schema=False)
async def raw_frameworks(request: Request) -> dict[str, Any]:
    cfg = request.app.state.config
    path = cfg.meta_dir / "frameworks.json"
    if not path.exists():
        raise HTTPException(status_code=500, detail="frameworks.json not present")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)
