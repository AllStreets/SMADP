"""Meta endpoints: categories, risk taxonomy, rubric."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from smadp.config import Config

router = APIRouter(prefix="/meta", tags=["meta"])


def _load_meta(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"meta file not found: {path.name}")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail=f"meta file malformed: {path.name}")
    return data


@router.get("/categories", summary="List of agent categories")
async def categories(request: Request) -> dict[str, Any]:
    cfg: Config = request.app.state.config
    return _load_meta(cfg.meta_dir / "categories.json")


@router.get("/risk-taxonomy", summary="Five-risk taxonomy + severity scale")
async def risk_taxonomy(request: Request) -> dict[str, Any]:
    cfg: Config = request.app.state.config
    return _load_meta(cfg.meta_dir / "risk-taxonomy.json")


@router.get("/rubric", summary="Current LLM-judge rubric")
async def rubric(request: Request) -> dict[str, Any]:
    cfg: Config = request.app.state.config
    return _load_meta(cfg.rubric_path)
