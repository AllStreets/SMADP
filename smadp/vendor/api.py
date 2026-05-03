"""FastAPI router for /api/vendor."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from smadp.config import Config, load_config
from smadp.schemas.tenancy import Role, Workspace
from smadp.schemas.dispute import (
    Dispute,
    DisputeDecision,
    RequestedOutcome,
)
from smadp.schemas.vendor import (
    ClaimMethod,
    ClaimVerification,
    DnsEvidence,
    EmailEvidence,
    RepoEvidence,
    TokenEvidence,
    VendorClaim,
    VendorResponse,
)
from smadp.tenancy.deps import current_user_id, current_workspace, require_role
from smadp.vendor import store, verifier

router = APIRouter(prefix="/vendor", tags=["vendor"])


class _Instructions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: ClaimMethod
    text: str
    magic_link_url: str | None = None


class _CreateClaimBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    method: ClaimMethod
    evidence_url: str | None = None


class _CreateClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: VendorClaim
    token: str
    instructions: _Instructions


class _VerifyEvidence(BaseModel):
    """Discriminated by method on the parent body."""

    model_config = ConfigDict(extra="allow")


class _VerifyClaimBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: ClaimMethod
    evidence: dict[str, Any] = Field(default_factory=dict)


class _VerifyClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: VendorClaim
    verification: ClaimVerification


def _build_instructions(method: ClaimMethod, claim_id: str, token: str, cfg: Config) -> _Instructions:
    if method == ClaimMethod.REPO:
        return _Instructions(
            method=method,
            text=(
                f"Place the token in your repo at .smadp/owner.txt and POST verify with"
                f" {{'repo_url': '<base raw URL>'}}. Token: {token}"
            ),
        )
    if method == ClaimMethod.DNS:
        return _Instructions(
            method=method,
            text=(
                f"Add a TXT record at _smadp-owner.<your-domain> with value {token}"
                f" and POST verify with {{'domain': '<your-domain>'}}."
            ),
        )
    if method == ClaimMethod.EMAIL:
        link = verifier.build_email_magic_link(
            public_base_url=cfg.public_base_url, claim_id=claim_id, token=token
        )
        return _Instructions(
            method=method,
            text=(
                "Visit the magic-link URL OR POST verify with {'token': '<token>'}."
                " The operator must deliver this URL to the vendor out-of-band; SMADP"
                " does not send email in this version."
            ),
            magic_link_url=link,
        )
    raise ValueError(f"unknown method: {method!r}")


def _coerce_evidence(method: ClaimMethod, raw: dict[str, Any]):
    if method == ClaimMethod.REPO:
        return RepoEvidence(**raw)
    if method == ClaimMethod.DNS:
        return DnsEvidence(**raw)
    if method == ClaimMethod.EMAIL:
        return TokenEvidence(**raw)
    raise ValueError(f"unknown method: {method!r}")


@router.post(
    "/claims",
    response_model=_CreateClaimResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_claim(
    body: _CreateClaimBody,
    workspace: Workspace = Depends(current_workspace),
    user_id: str = Depends(current_user_id),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    cfg = load_config()
    claim = store.create_claim(
        workspace_id=workspace.id,
        agent_id=body.agent_id,
        vendor_user_id=user_id,
        method=body.method,
        evidence_url=body.evidence_url,
        config=cfg,
    )
    instructions = _build_instructions(body.method, claim.id, claim.token, cfg)
    return _CreateClaimResponse(claim=claim, token=claim.token, instructions=instructions)


@router.get("/claims", response_model=list[dict[str, Any]])
def list_claims(
    agent_id: str | None = None,
    workspace: Workspace = Depends(current_workspace),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    claims = store.list_claims(workspace_id=workspace.id, agent_id=agent_id)
    # NEVER return the raw token on list — exclude it completely
    result = []
    for c in claims:
        data = c.model_dump()
        del data["token"]
        result.append(data)
    return result


@router.post(
    "/claims/{claim_id}/verify",
    response_model=_VerifyClaimResponse,
)
def verify_claim(
    claim_id: str,
    body: _VerifyClaimBody,
    workspace: Workspace = Depends(current_workspace),
    user_id: str = Depends(current_user_id),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    try:
        claim = store.get_claim(claim_id=claim_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if claim.workspace_id != workspace.id or claim.vendor_user_id != user_id:
        raise HTTPException(status_code=404, detail="claim not found in this workspace")
    if body.method != claim.method:
        raise HTTPException(
            status_code=400,
            detail=f"verify method ({body.method.value}) must match claim method ({claim.method.value})",
        )
    try:
        evidence = _coerce_evidence(body.method, body.evidence)
    except Exception as exc:  # ValidationError or ValueError
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = verifier.verify(claim=claim, evidence=evidence)
    if result.verified:
        store.mark_claim_verified(claim_id=claim_id)
        claim = store.get_claim(claim_id=claim_id)
        return _VerifyClaimResponse(claim=claim, verification=result)
    # Surface mismatch as 409 so the operator sees it as a state conflict, not a server error
    return _verify_failed_response(claim, result)


def _verify_failed_response(claim: VendorClaim, result: ClaimVerification):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=409,
        content=_VerifyClaimResponse(claim=claim, verification=result).model_dump(mode="json"),
    )


@router.post("/claims/{claim_id}/revoke", response_model=VendorClaim)
def revoke_claim(
    claim_id: str,
    workspace: Workspace = Depends(current_workspace),
    user_id: str = Depends(current_user_id),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    try:
        claim = store.get_claim(claim_id=claim_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if claim.workspace_id != workspace.id or claim.vendor_user_id != user_id:
        raise HTTPException(status_code=404, detail="claim not found in this workspace")
    store.revoke_claim(claim_id=claim_id)
    return store.get_claim(claim_id=claim_id)


class _PostResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict_id: str
    agent_id: str
    body_md: str = Field(min_length=1, max_length=8192)


@router.post(
    "/responses",
    response_model=VendorResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_response(
    body: _PostResponseBody,
    workspace: Workspace = Depends(current_workspace),
    user_id: str = Depends(current_user_id),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    found = store.find_verified_claim(
        workspace_id=workspace.id, vendor_user_id=user_id, agent_id=body.agent_id
    )
    if found is None:
        raise HTTPException(
            status_code=403, detail="posting requires a verified claim for this agent"
        )
    return store.post_response(
        workspace_id=workspace.id,
        verdict_id=body.verdict_id,
        vendor_user_id=user_id,
        body_md=body.body_md,
    )


@router.get("/responses", response_model=list[VendorResponse])
def list_responses(
    verdict_id: str,
    workspace: Workspace = Depends(current_workspace),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    return store.list_responses(workspace_id=workspace.id, verdict_id=verdict_id)


class _FileDisputeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict_id: str
    agent_id: str
    argument_md: str = Field(min_length=1, max_length=16384)
    requested_outcome: RequestedOutcome


@router.post(
    "/disputes",
    response_model=Dispute,
    status_code=status.HTTP_201_CREATED,
)
def file_dispute(
    body: _FileDisputeBody,
    workspace: Workspace = Depends(current_workspace),
    user_id: str = Depends(current_user_id),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    found = store.find_verified_claim(
        workspace_id=workspace.id, vendor_user_id=user_id, agent_id=body.agent_id
    )
    if found is None:
        raise HTTPException(
            status_code=403, detail="filing requires a verified claim for this agent"
        )
    return store.file_dispute(
        workspace_id=workspace.id,
        verdict_id=body.verdict_id,
        vendor_user_id=user_id,
        argument_md=body.argument_md,
        requested_outcome=body.requested_outcome,
    )


@router.get("/disputes", response_model=list[Dispute])
def list_disputes(
    verdict_id: str | None = None,
    workspace: Workspace = Depends(current_workspace),
    _role: None = Depends(require_role(Role.EDITOR)),
) -> Any:
    return store.list_disputes(workspace_id=workspace.id, verdict_id=verdict_id)


class _UpdateDisputeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: DisputeDecision
    rationale_md: str | None = None


@router.patch("/disputes/{dispute_id}", response_model=Dispute)
def update_dispute(
    dispute_id: str,
    body: _UpdateDisputeBody,
    workspace: Workspace = Depends(current_workspace),
    _role: None = Depends(require_role(Role.ADMIN)),
) -> Any:
    try:
        existing = store.get_dispute(dispute_id=dispute_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if existing.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="dispute not found in this workspace")
    try:
        return store.update_dispute_status(
            dispute_id=dispute_id,
            decision=body.decision,
            rationale_md=body.rationale_md,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


__all__ = ["router"]
