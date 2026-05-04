"""Click subgroup: smadp vendor {claims,responses,disputes} ..."""

from __future__ import annotations

import json
import os
import sys

import click
from rich.console import Console
from rich.table import Table

from smadp.config import load_config
from smadp.schemas.dispute import DisputeDecision, RequestedOutcome
from smadp.schemas.vendor import (
    ClaimMethod,
    DnsEvidence,
    RepoEvidence,
    TokenEvidence,
)
from smadp.vendor import store, verifier

_console = Console()


def _workspace_id() -> str:
    v = os.environ.get("SMADP_WORKSPACE_ID")
    if not v:
        click.echo("SMADP_WORKSPACE_ID env or --workspace-id is required", err=True)
        sys.exit(2)
    return v


def _user_id() -> str:
    v = os.environ.get("SMADP_USER_ID")
    if not v:
        click.echo("SMADP_USER_ID env or --user-id is required", err=True)
        sys.exit(2)
    return v


@click.group(name="vendor")
def vendor_group() -> None:
    """Vendor flows: claims, responses, disputes."""


@vendor_group.group("claims")
def _claims() -> None:
    """Vendor claim management."""


@_claims.command("create")
@click.option("--agent-id", required=True)
@click.option("--method", type=click.Choice(["repo", "dns", "email"]), required=True)
@click.option(
    "--evidence-url",
    default=None,
    help="Required for method=repo (the repo raw base URL).",
)
def _claims_create(agent_id: str, method: str, evidence_url: str | None) -> None:
    cfg = load_config()
    claim = store.create_claim(
        workspace_id=_workspace_id(),
        agent_id=agent_id,
        vendor_user_id=_user_id(),
        method=ClaimMethod(method),
        evidence_url=evidence_url,
        config=cfg,
    )
    _console.print(f"created  {claim.id}")
    _console.print(f"token:   {claim.token}")
    if method == "email":
        link = verifier.build_email_magic_link(
            public_base_url=cfg.public_base_url, claim_id=claim.id, token=claim.token
        )
        _console.print(f"magic-link: {link}")


@_claims.command("ls")
@click.option("--agent-id", default=None)
def _claims_ls(agent_id: str | None) -> None:
    cfg = load_config()
    claims = store.list_claims(workspace_id=_workspace_id(), agent_id=agent_id, config=cfg)
    table = Table(title="Vendor Claims")
    for col in ("id", "agent", "method", "status", "created_at"):
        table.add_column(col)
    for c in claims:
        table.add_row(c.id, c.agent_id, c.method.value, c.status.value, c.created_at.isoformat())
    _console.print(table)


@_claims.command("verify")
@click.argument("claim_id")
@click.option("--evidence-json", required=True, help="JSON object matching the claim method.")
def _claims_verify(claim_id: str, evidence_json: str) -> None:
    cfg = load_config()
    raw = json.loads(evidence_json)
    claim = store.get_claim(claim_id=claim_id, config=cfg)
    if claim.method == ClaimMethod.REPO:
        evidence = RepoEvidence(**raw)
    elif claim.method == ClaimMethod.DNS:
        evidence = DnsEvidence(**raw)
    else:
        evidence = TokenEvidence(**raw)
    result = verifier.verify(claim=claim, evidence=evidence)
    if result.verified:
        store.mark_claim_verified(claim_id=claim_id, config=cfg)
        _console.print(f"[green]verified[/green]  {result.detail}")
    else:
        _console.print(f"[red]not verified[/red]  {result.detail}")
        sys.exit(1)


@_claims.command("revoke")
@click.argument("claim_id")
def _claims_revoke(claim_id: str) -> None:
    cfg = load_config()
    store.revoke_claim(claim_id=claim_id, config=cfg)
    _console.print(f"revoked  {claim_id}")


@vendor_group.group("responses")
def _responses() -> None:
    """Vendor responses on verdicts."""


@_responses.command("post")
@click.option("--verdict-id", required=True)
@click.option("--agent-id", required=True)
@click.option("--body-md", required=True)
def _responses_post(verdict_id: str, agent_id: str, body_md: str) -> None:
    cfg = load_config()
    if (
        store.find_verified_claim(
            workspace_id=_workspace_id(), vendor_user_id=_user_id(), agent_id=agent_id, config=cfg
        )
        is None
    ):
        click.echo("error: posting requires a verified claim for this agent", err=True)
        sys.exit(2)
    r = store.post_response(
        workspace_id=_workspace_id(),
        verdict_id=verdict_id,
        vendor_user_id=_user_id(),
        body_md=body_md,
        config=cfg,
    )
    _console.print(f"posted  {r.id}")


@_responses.command("ls")
@click.option("--verdict-id", required=True)
def _responses_ls(verdict_id: str) -> None:
    cfg = load_config()
    rows = store.list_responses(workspace_id=_workspace_id(), verdict_id=verdict_id, config=cfg)
    table = Table(title=f"Responses — {verdict_id}")
    for col in ("id", "vendor_user_id", "created_at"):
        table.add_column(col)
    for r in rows:
        table.add_row(r.id, r.vendor_user_id, r.created_at.isoformat())
    _console.print(table)


@vendor_group.group("disputes")
def _disputes() -> None:
    """Vendor disputes."""


@_disputes.command("file")
@click.option("--verdict-id", required=True)
@click.option("--agent-id", required=True)
@click.option("--argument-md", required=True)
@click.option(
    "--requested-outcome",
    type=click.Choice(["reeval", "withdraw", "amend"]),
    required=True,
)
def _disputes_file(
    verdict_id: str, agent_id: str, argument_md: str, requested_outcome: str
) -> None:
    cfg = load_config()
    if (
        store.find_verified_claim(
            workspace_id=_workspace_id(), vendor_user_id=_user_id(), agent_id=agent_id, config=cfg
        )
        is None
    ):
        click.echo("error: filing requires a verified claim for this agent", err=True)
        sys.exit(2)
    d = store.file_dispute(
        workspace_id=_workspace_id(),
        verdict_id=verdict_id,
        vendor_user_id=_user_id(),
        argument_md=argument_md,
        requested_outcome=RequestedOutcome(requested_outcome),
        config=cfg,
    )
    _console.print(f"filed  {d.id}")


@_disputes.command("triage")
@click.argument("dispute_id")
@click.option("--decision", type=click.Choice(["spam", "substantive"]), required=True)
def _disputes_triage(dispute_id: str, decision: str) -> None:
    cfg = load_config()
    d = store.update_dispute_status(
        dispute_id=dispute_id,
        decision=DisputeDecision(decision),
        rationale_md=None,
        config=cfg,
    )
    _console.print(f"triaged  {d.id}  {d.status.value}")


@_disputes.command("resolve")
@click.argument("dispute_id")
@click.option("--decision", type=click.Choice(["reeval", "stands"]), required=True)
@click.option("--rationale-md", required=True)
def _disputes_resolve(dispute_id: str, decision: str, rationale_md: str) -> None:
    cfg = load_config()
    d = store.update_dispute_status(
        dispute_id=dispute_id,
        decision=DisputeDecision(decision),
        rationale_md=rationale_md,
        config=cfg,
    )
    _console.print(f"resolved  {d.id}  {d.status.value}")


@_disputes.command("ls")
@click.option("--verdict-id", default=None)
def _disputes_ls(verdict_id: str | None) -> None:
    cfg = load_config()
    rows = store.list_disputes(workspace_id=_workspace_id(), verdict_id=verdict_id, config=cfg)
    table = Table(title="Disputes")
    for col in ("id", "verdict_id", "status", "filed_at", "sla_breached_at"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r.id,
            r.verdict_id,
            r.status.value,
            r.filed_at.isoformat(),
            r.sla_breached_at.isoformat() if r.sla_breached_at else "—",
        )
    _console.print(table)
