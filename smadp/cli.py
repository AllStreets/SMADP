"""SMADP command-line interface (`smadp`).

Click-based, Rich-rendered. Subcommands are listed in §16 of the design spec.
External LLM/sandbox dependencies are imported lazily so the CLI is usable
even in environments where those subsystems aren't installed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table

from smadp import __version__
from smadp.catalog.chronicle import Chronicle
from smadp.catalog.index import CatalogIndex
from smadp.catalog.lint import LintReport, lint_catalog
from smadp.catalog.repo import CatalogRepo, NotFoundError
from smadp.config import Config, load_config
from smadp.passport.cli import passport_group
from smadp.proxy.cli import proxy as proxy_group
from smadp.refresh.cli import refresh_group
from smadp.transparency.cli import transparency_group
from smadp.utils.slug import normalize_slug, sort_pair
from smadp.vendor.cli import vendor_group
from smadp.webhooks.cli import webhook_group

console = Console()
err_console = Console(stderr=True)

# Severity colors lifted from catalog/_meta/risk-taxonomy.json
_SEVERITY_COLORS = {
    "none": "#22C55E",
    "low": "#84CC16",
    "medium": "#F59E0B",
    "high": "#EF4444",
    "critical": "#7F1D1D",
}
_EVIDENCE_COLORS = {
    "unverified-profile": "#71717A",
    "docs-only": "#A78BFA",
    "behavior-observed": "#06B6D4",
    "profile-verified": "#7C3AED",
    "sandbox-validated": "#22C55E",
}


def _config_from_ctx(ctx: click.Context) -> Config:
    cfg: Config | None = ctx.obj.get("config") if ctx.obj else None
    if cfg is not None:
        return cfg
    cfg = load_config()
    if ctx.obj is None:
        ctx.obj = {}
    ctx.obj["config"] = cfg
    return cfg


def _scoped_setenv(ctx: click.Context, key: str, value: str) -> None:
    """Set an env var for the duration of this Click invocation only.

    Without this scoping, --catalog would leak across invocations in the same
    process (e.g. in pytest where every CliRunner.invoke shares os.environ).
    """
    import os

    previous = os.environ.get(key)
    os.environ[key] = value

    def _restore() -> None:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous

    ctx.call_on_close(_restore)


# --------------------------------------------------------------------- root cmd
@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    help="SMADP — Safe Multi-Agent Deployment Platform.",
)
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Override the catalog directory (otherwise `$SMADP_CATALOG` or `<repo>/catalog`).",
)
@click.version_option(__version__, prog_name="smadp")
@click.pass_context
def cli(ctx: click.Context, catalog_path: Path | None) -> None:
    ctx.ensure_object(dict)
    if catalog_path is not None:
        _scoped_setenv(ctx, "SMADP_CATALOG", str(catalog_path.resolve()))
    ctx.obj["config"] = load_config()


# --------------------------------------------------------------------- version
@cli.command()
def version() -> None:
    """Print the SMADP version."""
    console.print(f"smadp [bold cyan]{__version__}[/]")


# ------------------------------------------------------------------------ init
@cli.command()
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Catalog directory to create (default: cwd/catalog).",
)
@click.pass_context
def init(ctx: click.Context, catalog_path: Path | None) -> None:
    """Initialize a new catalog directory tree."""
    if catalog_path is not None:
        _scoped_setenv(ctx, "SMADP_CATALOG", str(catalog_path.resolve()))
    cfg = load_config()
    cfg.ensure_dirs()
    console.print(f"[green]initialized catalog at[/] {cfg.catalog_dir}")


# --------------------------------------------------------------------- profile
@cli.command()
@click.argument("slug_or_url")
@click.option("--name", default=None, help="Display name for new profiles.")
@click.option("--unverified", is_flag=True, help="Save under profiles/_unverified/.")
@click.pass_context
def profile(
    ctx: click.Context,
    slug_or_url: str,
    name: str | None,
    unverified: bool,
) -> None:
    """Generate or refresh a Safety Profile."""
    cfg = _config_from_ctx(ctx)
    repo = CatalogRepo(cfg)
    chronicle = Chronicle(cfg)

    is_url = slug_or_url.startswith(("http://", "https://"))
    if not is_url:
        slug = normalize_slug(slug_or_url)
        try:
            existing = repo.load_profile(slug)
            console.print(f"[cyan]found existing profile:[/] {slug} ({existing.name})")
        except NotFoundError:
            err_console.print(f"[red]no profile {slug!r} on disk and no URL provided[/]")
            ctx.exit(2)

    try:
        from smadp.profiler.pipeline import build_profile  # type: ignore[import-not-found]
    except Exception as exc:
        err_console.print(f"[red]profiler unavailable:[/] {type(exc).__name__}: {exc}")
        err_console.print(
            "[yellow]install the profiler subsystem (smadp.profiler) to generate profiles[/]"
        )
        ctx.exit(1)
        return

    urls = [slug_or_url] if is_url else []
    fallback_slug = None if is_url else slug
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as p:
        p.add_task("Building profile (LLM extraction + citation validation)", total=None)
        try:
            built = build_profile(  # type: ignore[misc]
                urls=urls,
                name=name,
                slug=fallback_slug,
                verified=not unverified,
            )
        except Exception as exc:
            err_console.print(f"[red]profile build failed:[/] {exc}")
            ctx.exit(1)
            return
    path = repo.save_profile(built, verified=not unverified)
    chronicle.record(
        "profile.created" if not is_url else "profile.refreshed",
        slug=built.slug,
        details={"path": str(path), "via": "cli"},
    )
    console.print(f"[green]saved[/] {path}")


# --------------------------------------------------------------------- verdict
@cli.command()
@click.argument("slug_a")
@click.argument("slug_b")
@click.option("--regenerate", is_flag=True, help="Force re-generation even if cached.")
@click.pass_context
def verdict(ctx: click.Context, slug_a: str, slug_b: str, regenerate: bool) -> None:
    """Generate or fetch a pairwise verdict."""
    cfg = _config_from_ctx(ctx)
    repo = CatalogRepo(cfg)
    chronicle = Chronicle(cfg)

    try:
        a, b = sort_pair(slug_a, slug_b)
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/]")
        ctx.exit(2)
        return

    for slug in (a, b):
        if not repo.profile_exists(slug):
            err_console.print(f"[red]unknown profile:[/] {slug}")
            ctx.exit(2)
            return

    if not regenerate and repo.verdict_exists(a, b):
        loaded = repo.load_verdict(a, b)
        _render_verdict(loaded)
        return

    try:
        from smadp.analyzer.pipeline import (
            generate_verdict as _gv,  # type: ignore[import-not-found]
        )
    except Exception as exc:
        err_console.print(f"[red]analyzer unavailable:[/] {type(exc).__name__}: {exc}")
        ctx.exit(1)
        return

    profile_a = repo.load_profile(a)
    profile_b = repo.load_profile(b)
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as p:
        p.add_task(f"Generating verdict {a} <> {b}", total=None)
        new_verdict = asyncio.run(
            _gv(
                a,
                b,
                profile_a=profile_a,
                profile_b=profile_b,
                evidence={},
                config=cfg,
            )
        )
    repo.save_verdict(new_verdict)
    chronicle.record(
        "verdict.regenerated" if regenerate else "verdict.generated",
        pair=(a, b),
        verdict_id=new_verdict.verdict_id,
    )
    _render_verdict(new_verdict)


def _render_verdict(verdict_obj: Any) -> None:
    table = Table(title=f"Verdict: {verdict_obj.pair[0]} <> {verdict_obj.pair[1]}")
    table.add_column("Risk")
    table.add_column("Severity")
    table.add_column("Rationale", max_width=80)
    for name in (
        "A_prompt_injection",
        "B_data_leakage",
        "C_capability_conflict",
        "D_cascading_error",
        "E_compliance",
    ):
        sv = getattr(verdict_obj.sub_verdicts, name)
        color = _SEVERITY_COLORS.get(sv.severity, "white")
        table.add_row(name, f"[{color}]{sv.severity}[/]", sv.rationale)
    console.print(table)
    ev_color = _EVIDENCE_COLORS.get(verdict_obj.evidence_level, "white")
    console.print(
        f"[bold]headline:[/] {verdict_obj.headline}\n"
        f"[bold]evidence_level:[/] [{ev_color}]{verdict_obj.evidence_level}[/]   "
        f"[bold]composite:[/] {verdict_obj.composite_score:.3f}   "
        f"[bold]confidence:[/] {verdict_obj.confidence:.2f}"
    )


# --------------------------------------------------------------------- validate
@cli.command()
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
)
@click.pass_context
def validate(ctx: click.Context, catalog_path: Path | None) -> None:
    """Schema + cross-reference check the entire catalog."""
    if catalog_path is not None:
        _scoped_setenv(ctx, "SMADP_CATALOG", str(catalog_path.resolve()))
    cfg = load_config()
    report = lint_catalog(cfg)
    _render_lint_report(report, cfg)
    if not report.ok:
        ctx.exit(1)


@cli.command()
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
)
@click.pass_context
def lint(ctx: click.Context, catalog_path: Path | None) -> None:
    """Alias of `validate`."""
    ctx.invoke(validate, catalog_path=catalog_path)


def _render_lint_report(report: LintReport, cfg: Config) -> None:
    console.print(
        f"[bold]Catalog:[/] {cfg.catalog_dir}\n"
        f"profiles={report.profiles_checked}  "
        f"verdicts={report.verdicts_checked}  "
        f"evidence={report.evidence_checked}"
    )
    if not report.issues:
        console.print("[green]all checks passed.[/]")
        return
    table = Table(show_lines=False)
    table.add_column("severity")
    table.add_column("kind")
    table.add_column("target", overflow="fold")
    table.add_column("message", overflow="fold")
    for issue in report.issues:
        color = "red" if issue.severity == "error" else "yellow"
        table.add_row(
            f"[{color}]{issue.severity}[/]",
            issue.kind,
            issue.target,
            issue.message,
        )
    console.print(table)
    err_count = len(report.errors)
    warn_count = len(report.warnings)
    console.print(f"[bold]summary:[/] [red]{err_count} errors[/], [yellow]{warn_count} warnings[/]")


# --------------------------------------------------------------------- submit
@cli.command()
@click.argument("url")
@click.option("--name", default=None, help="Display name (optional).")
@click.pass_context
def submit(ctx: click.Context, url: str, name: str | None) -> None:
    """Submit an agent for unverified profiling."""
    if not url.startswith(("http://", "https://")):
        err_console.print(f"[red]not a URL:[/] {url}")
        ctx.exit(2)
        return
    ctx.invoke(profile, slug_or_url=url, name=name, unverified=True)


# --------------------------------------------------------------------- evaluate
@cli.command()
@click.argument("agents", nargs=-1, required=True)
@click.option("--scenario", default=None, help="Optional scenario name to bias the evaluation.")
@click.pass_context
def evaluate(ctx: click.Context, agents: tuple[str, ...], scenario: str | None) -> None:
    """Evaluate every pair from a list of agents."""
    if len(agents) < 2:
        err_console.print("[red]need at least two agents[/]")
        ctx.exit(2)
        return
    cfg = _config_from_ctx(ctx)
    repo = CatalogRepo(cfg)
    chronicle = Chronicle(cfg)

    for slug in agents:
        if not repo.profile_exists(slug):
            err_console.print(f"[red]unknown agent:[/] {slug}")
            ctx.exit(2)
            return

    try:
        from smadp.analyzer.pipeline import generate_verdict  # type: ignore[import-not-found]
    except Exception:
        generate_verdict = None  # type: ignore[assignment]

    table = Table(title=f"Evaluating {len(agents)} agents")
    table.add_column("pair")
    table.add_column("status")
    table.add_column("composite")
    table.add_column("evidence")

    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for i, a in enumerate(agents):
        for b in agents[i + 1 :]:
            p = sort_pair(a, b)
            if p not in seen:
                seen.add(p)
                pairs.append(p)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        task = progress.add_task("evaluating pairs", total=len(pairs))
        for a, b in pairs:
            try:
                v = repo.load_verdict(a, b)
                status = "cached"
            except NotFoundError:
                if generate_verdict is None:
                    status = "no analyzer"
                    table.add_row(f"{a} <> {b}", f"[yellow]{status}[/]", "-", "-")
                    progress.advance(task)
                    continue
                try:
                    v = asyncio.run(
                        generate_verdict(  # type: ignore[misc]
                            a,
                            b,
                            profile_a=repo.load_profile(a),
                            profile_b=repo.load_profile(b),
                            evidence={},
                            config=cfg,
                        )
                    )
                    repo.save_verdict(v)
                    chronicle.record(
                        "verdict.generated",
                        pair=(a, b),
                        verdict_id=v.verdict_id,
                        details={"scenario": scenario},
                    )
                    status = "generated"
                except Exception as exc:
                    table.add_row(
                        f"{a} <> {b}",
                        "[red]error[/]",
                        "-",
                        f"[red]{exc}[/]",
                    )
                    progress.advance(task)
                    continue
            ev_color = _EVIDENCE_COLORS.get(v.evidence_level, "white")
            table.add_row(
                f"{a} <> {b}",
                status,
                f"{v.composite_score:.3f}",
                f"[{ev_color}]{v.evidence_level}[/]",
            )
            progress.advance(task)
    console.print(table)


# ----------------------------------------------------------------------- serve
@cli.command()
@click.option("--port", default=8000, type=int)
@click.option("--host", default="127.0.0.1")
@click.option("--reload", is_flag=True, help="Enable autoreload (dev only).")
@click.pass_context
def serve(ctx: click.Context, port: int, host: str, reload: bool) -> None:
    """Start the REST API."""
    try:
        import uvicorn
    except ImportError:
        err_console.print("[red]uvicorn is not installed[/]")
        ctx.exit(1)
        return
    console.print(f"[bold green]SMADP API[/] starting on http://{host}:{port}  (reload={reload})")
    uvicorn.run(
        "smadp.api.server:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )


# --------------------------------------------------------------------- sandbox
@cli.group()
def sandbox() -> None:
    """Sandbox queue: enqueue, list, inspect runs."""


@sandbox.command("run")
@click.argument("slug_a")
@click.argument("slug_b")
@click.option("--scenario", required=True, help="Scenario name (one of the built-ins).")
@click.pass_context
def sandbox_run(ctx: click.Context, slug_a: str, slug_b: str, scenario: str) -> None:
    """Enqueue a sandbox run after capability binding."""
    cfg = _config_from_ctx(ctx)
    repo = CatalogRepo(cfg)
    a, b = sort_pair(slug_a, slug_b)
    for slug in (a, b):
        if not repo.profile_exists(slug):
            err_console.print(f"[red]unknown agent:[/] {slug}")
            ctx.exit(2)
            return
    try:
        from smadp.sandbox.binding import ScenarioBindingError
        from smadp.sandbox.queue import enqueue_sandbox_run
    except Exception as exc:
        err_console.print(f"[red]sandbox subsystem unavailable:[/] {exc}")
        ctx.exit(1)
        return
    try:
        run_id = enqueue_sandbox_run(slug_a=a, slug_b=b, scenario=scenario, config=cfg)
    except ScenarioBindingError as exc:
        err_console.print(f"[red]binding failed:[/] {exc}")
        ctx.exit(2)
        return
    console.print(f"[green]queued[/] run_id={run_id} pair={a} <> {b} scenario={scenario}")


@sandbox.command("status")
@click.argument("run_id", required=False)
@click.pass_context
def sandbox_status(ctx: click.Context, run_id: str | None) -> None:
    """Show queue state, or one run's status if run_id provided."""
    try:
        from smadp.sandbox.queue import (  # type: ignore[import-not-found]
            get_run_status,
            list_pending,
        )
    except Exception as exc:
        err_console.print(f"[red]sandbox subsystem unavailable:[/] {exc}")
        ctx.exit(1)
        return
    if run_id is not None:
        rec = get_run_status(run_id)  # type: ignore[misc]
        if rec is None:
            err_console.print(f"[red]unknown run:[/] {run_id}")
            ctx.exit(2)
            return
        _print_json(rec)
        return
    pending = list_pending()  # type: ignore[misc]
    table = Table(title="Pending sandbox runs")
    table.add_column("run_id")
    table.add_column("pair")
    table.add_column("scenario")
    table.add_column("status")
    for r in pending:
        if isinstance(r, dict):
            pair = r.get("pair") or [r.get("slug_a"), r.get("slug_b")]
            table.add_row(
                str(r.get("run_id", "")),
                f"{pair[0]} <> {pair[1]}",
                str(r.get("scenario", "-")),
                str(r.get("status", "")),
            )
    console.print(table)


@sandbox.command("watch")
@click.argument("run_id")
@click.pass_context
def sandbox_watch(ctx: click.Context, run_id: str) -> None:
    """Tail a sandbox run's transcript live, then print its final outcome.

    Tails the per-event-flushed transcript JSONL by byte offset and prints
    each event as it appears; loops until the queue row reaches a terminal
    state, then prints the outcome line. Unknown run -> exit 2.
    """
    import time

    cfg = _config_from_ctx(ctx)
    try:
        from smadp.sandbox.queue import get_raw_row  # type: ignore[import-not-found]
        from smadp.sandbox.runner import transcript_path_for
        from smadp.sandbox.transcripts import TranscriptEvent
    except Exception as exc:
        err_console.print(f"[red]sandbox subsystem unavailable:[/] {exc}")
        ctx.exit(1)
        return

    row = get_raw_row(run_id, config=cfg)
    if row is None:
        err_console.print(f"[red]unknown run:[/] {run_id}")
        ctx.exit(2)
        return

    path = transcript_path_for(run_id, config=cfg)
    offset = 0
    terminal_states = {"completed", "failed"}

    def _drain() -> None:
        nonlocal offset
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as fh:
            fh.seek(offset)
            for line in fh:
                if not line.endswith("\n"):
                    break  # partial flush; retry next tick
                offset += len(line.encode("utf-8"))
                text = line.strip()
                if not text:
                    continue
                try:
                    event = TranscriptEvent.from_json_line(text)
                except Exception:  # noqa: S112
                    continue
                console.print(
                    f"[dim]{event.event_type}[/] {event.agent}: "
                    f"{json.dumps(event.payload, ensure_ascii=False)}"
                )

    while True:
        _drain()
        row = get_raw_row(run_id, config=cfg)
        state = str(row["state"]) if row else ""
        if state in terminal_states:
            _drain()
            outcome = (row.get("outcome") if row else None) or "-"
            console.print(f"[bold]state={state} outcome={outcome}[/]")
            return
        time.sleep(0.25)


@sandbox.command("halt")
@click.argument("run_id")
@click.pass_context
def sandbox_halt(ctx: click.Context, run_id: str) -> None:
    """Request an operator halt for a pending/running sandbox run.

    Unknown run or already-terminal run -> exit 2.
    """
    cfg = _config_from_ctx(ctx)
    try:
        from smadp.sandbox.queue import request_halt  # type: ignore[import-not-found]
    except Exception as exc:
        err_console.print(f"[red]sandbox subsystem unavailable:[/] {exc}")
        ctx.exit(1)
        return
    try:
        accepted = request_halt(run_id, config=cfg)
    except KeyError:
        err_console.print(f"[red]unknown run:[/] {run_id}")
        ctx.exit(2)
        return
    if not accepted:
        err_console.print(f"[red]run is already terminal:[/] {run_id}")
        ctx.exit(2)
        return
    console.print(f"[green]halt requested[/] run_id={run_id}")


@sandbox.command("runs")
@click.option("--limit", default=50, type=int)
@click.pass_context
def sandbox_runs(ctx: click.Context, limit: int) -> None:
    """List recent sandbox runs (any status)."""
    cfg = _config_from_ctx(ctx)
    try:
        from smadp.sandbox.queue import iter_runs  # type: ignore[import-not-found]
    except Exception as exc:
        err_console.print(f"[red]sandbox subsystem unavailable:[/] {exc}")
        ctx.exit(1)
        return
    table = Table(title=f"Sandbox runs (limit={limit})")
    table.add_column("run_id")
    table.add_column("pair")
    table.add_column("status")
    table.add_column("outcome")
    table.add_column("queued_at")
    try:
        records = iter_runs(limit=limit)  # type: ignore[misc]
    except TypeError:
        records = iter_runs()  # type: ignore[misc]

    # Look up the queue-state column, which iter_runs doesn't surface on the
    # SandboxRun schema (that schema is verdict-facing). We hit the same DB
    # to read `state` per row so the CLI can show pending/running/completed.
    states_by_id: dict[str, str] = {}
    try:
        from smadp.sandbox.queue import get_raw_row  # type: ignore[import-not-found]
    except Exception:
        get_raw_row = None  # type: ignore[assignment]

    rows = list(records)[:limit]
    for r in rows:
        rid = getattr(r, "run_id", None)
        if isinstance(rid, str) and get_raw_row is not None:
            row = get_raw_row(rid, config=cfg)
            if row is not None:
                states_by_id[rid] = str(row["state"])

    for r in rows:
        if isinstance(r, dict):  # legacy contract: tolerate dict-shaped rows
            pair = r.get("pair") or [r.get("slug_a"), r.get("slug_b")]
            table.add_row(
                str(r.get("run_id", "")),
                f"{pair[0]} <> {pair[1]}",
                str(r.get("status", states_by_id.get(str(r.get("run_id", "")), "-"))),
                str(r.get("outcome", "-")),
                str(r.get("queued_at", r.get("created_at", "-"))),
            )
            continue
        # SandboxRun pydantic model
        run_id = getattr(r, "run_id", "")
        scenario_label = getattr(r, "scenario", None) or "-"
        # SandboxRun doesn't carry slug_a/slug_b — fall back to the raw row.
        slug_a = slug_b = "?"
        if get_raw_row is not None:
            raw = get_raw_row(run_id, config=cfg)
            if raw is not None:
                slug_a = str(raw["slug_a"])
                slug_b = str(raw["slug_b"])
        table.add_row(
            str(run_id),
            f"{slug_a} <> {slug_b} ({scenario_label})",
            states_by_id.get(run_id, "-"),
            str(getattr(r, "outcome", "-")),
            str(getattr(r, "started_at", "-")),
        )
    console.print(table)


@sandbox.command("pin-images")
@click.option(
    "--adapter",
    "adapters",
    multiple=True,
    help="Adapter slug to pin (repeatable). Default: all adapters under adapters/.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would change without writing files.",
)
@click.pass_context
def sandbox_pin_images(ctx: click.Context, adapters: tuple[str, ...], dry_run: bool) -> None:
    """Pull each adapter image and write its sha256 digest into approved_images.json + mcp.json."""
    from smadp.sandbox.pin_images import PinImagesError, pin_images  # local import (docker dep)

    repo_root = Path(__file__).resolve().parents[1]
    adapters_root = repo_root / "adapters"
    approved_images_path = repo_root / "smadp" / "sandbox" / "approved_images.json"
    try:
        result = pin_images(
            slugs=list(adapters) or None,
            adapters_root=adapters_root,
            approved_images_path=approved_images_path,
            dry_run=dry_run,
        )
    except PinImagesError as exc:
        err_console.print(f"[red]pin-images failed:[/] {exc}")
        ctx.exit(2)
        return

    if not result.changed and not result.unchanged:
        console.print("[yellow]no adapters processed[/]")
        return
    table = Table(title="pin-images" + (" (dry run)" if dry_run else ""))
    table.add_column("slug")
    table.add_column("status")
    table.add_column("digest")
    changed_label = "[yellow]would change[/]" if dry_run else "[yellow]changed[/]"
    for slug, digest in result.changed.items():
        table.add_row(slug, changed_label, digest)
    for slug, digest in result.unchanged.items():
        table.add_row(slug, "[dim]unchanged[/]", digest)
    console.print(table)


@sandbox.command("work")
@click.option("--once", is_flag=True, help="Process at most one run, then exit.")
@click.option(
    "--max",
    "max_runs",
    type=int,
    default=None,
    help="Exit after N completed runs.",
)
@click.option("--scenario", default=None, help="Only process runs for this scenario.")
@click.option(
    "--keys-file",
    type=click.Path(file_okay=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to keys.env (default: ~/.smadp/keys.env).",
)
@click.option("--poll-interval", type=float, default=2.0, help="Seconds between queue polls.")
@click.pass_context
def sandbox_work(
    ctx: click.Context,
    once: bool,
    max_runs: int | None,
    scenario: str | None,
    keys_file: Path | None,
    poll_interval: float,
) -> None:
    """Drain the sandbox queue: exec each run, promote the verdict."""
    import asyncio

    from smadp.sandbox.worker import run_worker

    cfg = _config_from_ctx(ctx)
    summary = asyncio.run(
        run_worker(
            once=once,
            max_runs=max_runs,
            scenario_filter=scenario,
            config=cfg,
            keys_path=keys_file,
            poll_interval_s=poll_interval,
        )
    )
    console.print(
        f"[green]worker exit[/] runs_completed={summary.runs_completed} "
        f"runs_failed={summary.runs_failed}"
    )


# ------------------------------------------------------------------- chronicle
@cli.command()
@click.option("--tail", is_flag=True, help="Follow new events as they arrive.")
@click.option("--since", default=None, help="ISO datetime lower bound.")
@click.option("--limit", default=100, type=int)
@click.pass_context
def chronicle(ctx: click.Context, tail: bool, since: str | None, limit: int) -> None:
    """Show audit log."""
    cfg = _config_from_ctx(ctx)
    chron = Chronicle(cfg)
    since_dt: datetime | None = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as exc:
            err_console.print(f"[red]bad --since:[/] {exc}")
            ctx.exit(2)
            return
    events = list(chron.iter_events(since=since_dt))
    events.sort(key=lambda e: e.ts, reverse=True)
    events = events[:limit]
    table = Table(title="Chronicle")
    table.add_column("ts")
    table.add_column("event")
    table.add_column("by")
    table.add_column("subject")
    for e in events:
        subject = ""
        if e.pair:
            subject = f"{e.pair[0]} <> {e.pair[1]}"
        elif e.slug:
            subject = e.slug
        table.add_row(e.ts.isoformat(), e.event, e.by, subject)
    console.print(table)
    if tail:
        console.print("[dim]--tail not yet implemented; printed snapshot[/]")


# ------------------------------------------------------------------- autopilot
@cli.group()
def autopilot() -> None:
    """Autonomous growth of pair and chain verdicts."""


@autopilot.command("tick")
@click.option("--dry-run", is_flag=True, help="Show what would be enqueued without writing")
@click.pass_context
def autopilot_tick(ctx: click.Context, dry_run: bool) -> None:
    """Plan the next batch of sandbox runs and enqueue them."""
    from smadp.autopilot.tick import run_tick

    cfg = _config_from_ctx(ctx)
    summary = run_tick(repo_root=cfg.repo_root, dry_run=dry_run)
    if dry_run:
        click.echo(f"would enqueue {summary.would_enqueue} (reason: {summary.reason})")
    else:
        click.echo(f"enqueued {summary.enqueued} (reason: {summary.reason})")


@autopilot.command("approve")
@click.argument("key")
@click.pass_context
def autopilot_approve(ctx: click.Context, key: str) -> None:
    """Publish a pending verdict by moving it to catalog/verdicts/."""
    from smadp.autopilot.approve import ApproveError, approve

    cfg = _config_from_ctx(ctx)
    try:
        approve(key=key, repo_root=cfg.repo_root)
    except ApproveError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"approved {key}")


@autopilot.command("compose-chains")
@click.pass_context
def autopilot_compose_chains(ctx: click.Context) -> None:
    """Compose authored chains into pending/chains/ (deterministic; numbers in Python)."""
    from smadp.autopilot.chain_composer import compose_authored_chains
    from smadp.autopilot.config import load_autopilot_config

    cfg = _config_from_ctx(ctx)
    autopilot_cfg = load_autopilot_config(cfg.repo_root / "config" / "autopilot.yaml")
    summary = compose_authored_chains(
        repo_root=cfg.repo_root, config=cfg, autopilot_cfg=autopilot_cfg
    )
    if summary.disabled:
        click.echo("compose-chains disabled (chain_composition.enabled: false)")
        return
    click.echo(f"composed={summary.composed} needs_judge={summary.needs_judge}")


@autopilot.command("approve-chain")
@click.argument("chain_id")
@click.pass_context
def autopilot_approve_chain(ctx: click.Context, chain_id: str) -> None:
    """Promote a composed chain candidate (pending/chains -> catalog/chains)."""
    from smadp.autopilot.approve import ApproveError, approve_chain

    cfg = _config_from_ctx(ctx)
    try:
        approve_chain(repo_root=cfg.repo_root, chain_id=chain_id)
    except ApproveError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"approved chain {chain_id}")


@autopilot.command("bootstrap-onexus")
@click.option(
    "--onexus-root",
    default=str(Path.home() / "Downloads" / "Integration" / "ONEXUS-Agents" / "catalog"),
    help="Path to the ONEXUS-Agents catalog directory.",
)
@click.option("--top-n", default=100, type=int, help="Number of top-scored agents to include.")
@click.option("--pair-cap", default=4950, type=int, help="Maximum pairs to enqueue.")
@click.pass_context
def autopilot_bootstrap_onexus(
    ctx: click.Context,
    onexus_root: str,
    top_n: int,
    pair_cap: int,
) -> None:
    """Import ONEXUS agents and queue Docs-only pair work."""
    from smadp.autopilot.bootstrap import bootstrap_onexus

    config = ctx.obj["config"]
    summary = bootstrap_onexus(
        repo_root=config.repo_root,
        onexus_root=Path(onexus_root).expanduser(),
        top_n=top_n,
        pair_cap=pair_cap,
    )
    click.echo(
        f"profiles_written={summary.profiles_written} "
        f"profiles_skipped={summary.profiles_skipped} "
        f"pairs_queued={summary.pairs_queued}"
    )


@autopilot.command("sync-onexus")
@click.option(
    "--max-promote",
    default=25,
    type=int,
    help="Max staged _unverified seeds to promote into research this run (volume cap).",
)
@click.pass_context
def autopilot_sync_onexus(ctx: click.Context, max_promote: int) -> None:
    """Promote staged ONEXUS seeds from _unverified/ into the research queue.

    Honours the state/AGENTS_SYNC_DISABLED kill switch. Independent of the
    NEXUS catalog pipeline.
    """
    from smadp.autopilot.agents_sync import sync_onexus

    config = ctx.obj["config"]
    summary = sync_onexus(repo_root=config.repo_root, max_promote=max_promote)
    if summary.disabled:
        click.echo("sync-onexus disabled (state/AGENTS_SYNC_DISABLED present)")
        return
    click.echo(
        f"promoted={summary.promoted} queued={summary.queued} "
        f"staged_remaining={summary.staged_remaining}"
    )


@autopilot.command("docs-only-tick")
@click.option("--batch-size", default=10, type=int)
@click.pass_context
def autopilot_docs_only_tick(ctx: click.Context, batch_size: int) -> None:
    """Drain the docs-only queue, dispatch to the right judge, publish."""
    import os

    from smadp.autopilot.docs_only_tick import run_docs_only_tick
    from smadp.autopilot.enrichers.github_readme import GithubReadmeFetcher
    from smadp.autopilot.judges.docs_only import DocsOnlyJudge
    from smadp.autopilot.judges.profile_enrich import ProfileEnrichmentJudge
    from smadp.llm.client import LLMClient

    config = ctx.obj["config"]
    client = LLMClient(config=config)
    rubric_path = config.rubric_path

    fetcher = GithubReadmeFetcher(
        cache_dir=config.repo_root / "state" / "enrichment_cache",
        token=os.environ.get("GITHUB_TOKEN"),
    )
    judges = {
        "profile_enrich": ProfileEnrichmentJudge(
            client=client,
            readme_fetcher=fetcher,
            model="gpt-5.4-mini",
        ),
        "docs_only": DocsOnlyJudge(
            client=client,
            model="gpt-5.4-mini",
            rubric_path=rubric_path,
        ),
    }
    summary = run_docs_only_tick(
        repo_root=config.repo_root,
        judges=judges,
        batch_size=batch_size,
    )
    click.echo(f"published={summary.published} failed={summary.failed} reason={summary.reason}")


@autopilot.command("daily-report")
@click.pass_context
def autopilot_daily_report(ctx: click.Context) -> None:
    """Generate today's catalog briefing at report/YYYY-MM-DD.md."""
    from smadp.autopilot.daily_report import write_report

    cfg = _config_from_ctx(ctx)
    path = write_report(repo_root=cfg.repo_root)
    click.echo(f"wrote {path}")


@autopilot.command("scaffold-tick")
@click.option("--batch-size", default=5, type=int)
@click.pass_context
def autopilot_scaffold_tick(ctx: click.Context, batch_size: int) -> None:
    """Pick top-scored not-yet-scaffolded docs-only profiles and scaffold each.

    One per fire: keeps per-tick wall-time bounded and respects the anonymous
    GitHub API budget. Writes one JSONL row per attempt to
    ``state/scaffold_tick.jsonl`` for audit.
    """
    import json as _json
    import os as _os
    from datetime import datetime as _dt

    from smadp.autopilot.scaffolders.language_detector import GithubMetadataLanguageDetector
    from smadp.autopilot.scaffolders.mcp_adapter import MCPAdapterScaffolder

    config = ctx.obj["config"]
    profiles_dir = config.repo_root / "catalog" / "profiles"
    adapters_dir = config.repo_root / "adapters"
    log_path = config.repo_root / "state" / "scaffold_tick.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Auto-load .env so manual runs see GITHUB_TOKEN without the user having
    # to `set -a; source .env`. The launchd loop already sources it; this
    # keeps the CLI symmetric.
    env_path = config.repo_root / ".env"
    if env_path.exists():
        for raw in env_path.read_text("utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            _os.environ.setdefault(k, v)

    already: set[str] = {p.name for p in adapters_dir.iterdir() if p.is_dir()}
    # Also skip slugs we've already attempted (success or failure) so failed
    # ones don't re-burn budget every 300s. Delete the row to force a retry.
    if log_path.exists():
        for line in log_path.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            attempted_slug = row.get("slug")
            if isinstance(attempted_slug, str):
                already.add(attempted_slug)

    candidates: list[tuple[float, str, dict[str, Any]]] = []
    for p in profiles_dir.glob("*.json"):
        try:
            profile = _json.loads(p.read_text("utf-8"))
        except (OSError, _json.JSONDecodeError):
            continue
        if profile.get("evidence_level") != "docs-only":
            continue
        slug = profile.get("slug") or p.stem
        if slug in already:
            continue
        onexus = profile.get("onexus") or {}
        if not onexus.get("source_github"):
            continue
        score = float(profile.get("composite_score") or 0)
        candidates.append((score, slug, profile))
    candidates.sort(key=lambda t: t[0], reverse=True)

    token = _os.environ.get("GITHUB_TOKEN")
    detector = GithubMetadataLanguageDetector(token=token)

    def _resolve_pin(github_source: str) -> str:
        return "HEAD"

    scaffolder = MCPAdapterScaffolder(detector=detector, commit_pin_resolver=_resolve_pin)

    attempted = 0
    succeeded = 0
    for _, slug, profile in candidates[:batch_size]:
        target_dir = adapters_dir / slug
        result = scaffolder.scaffold(profile, target_dir=target_dir)
        row = {
            "ts": _dt.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "slug": slug,
            "success": result.success,
            "reason": result.reason,
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(row) + "\n")
        attempted += 1
        if result.success:
            succeeded += 1

    click.echo(
        f"scaffold-tick attempted={attempted} succeeded={succeeded} "
        f"queue_remaining={max(0, len(candidates) - attempted)}"
    )


@autopilot.command("pair-gate-plan")
@click.option("--top-n", default=100, type=int)
@click.option("--pair-cap", default=4950, type=int)
@click.pass_context
def autopilot_pair_gate_plan(ctx: click.Context, top_n: int, pair_cap: int) -> None:
    """Re-scan profiles, enqueue pair-judge work where both sides are enriched."""
    import json as _json
    from datetime import datetime

    from smadp.autopilot.planners.pair_gate import PairGatePlanner
    from smadp.autopilot.work_queue import append_items

    config = ctx.obj["config"]
    profiles_dir = config.repo_root / "catalog" / "profiles"
    profiles: list[dict[str, Any]] = []
    for p in profiles_dir.glob("*.json"):
        try:
            profiles.append(_json.loads(p.read_text("utf-8")))
        except (OSError, _json.JSONDecodeError):
            continue

    # Skip pairs that already have a verdict — published (catalog/verdicts) or
    # awaiting the operator gate (catalog/pending). Without this the planner
    # re-enqueues every pair on every tick and the queue (and pending/) fills
    # with duplicates of already-judged work.
    exclude_pairs: set[tuple[str, str]] = set()
    for sub in ("verdicts", "pending"):
        for vf in (config.repo_root / "catalog" / sub).glob("*.json"):
            if vf.name.endswith(".sig.json"):
                continue  # detached BYOK signature sidecar, not a verdict
            try:
                pair = _json.loads(vf.read_text("utf-8")).get("pair")
            except (OSError, _json.JSONDecodeError):
                continue
            if isinstance(pair, list) and len(pair) == 2:
                a, b = sorted(str(x) for x in pair)
                exclude_pairs.add((a, b))

    planner = PairGatePlanner(top_n=top_n, pair_cap=pair_cap)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = planner.plan(profiles=profiles, now_iso=now, exclude_pairs=exclude_pairs)
    queue_path = config.repo_root / "state" / "docs_only_queue.jsonl"
    append_items(queue_path, items)
    click.echo(f"enqueued={len(items)} excluded_existing={len(exclude_pairs)}")


# --------------------------------------------------------------------- helpers
def _print_json(obj: Any) -> None:
    text = json.dumps(obj, indent=2, default=str, sort_keys=True)
    console.print(Syntax(text, "json", theme="ansi_dark", word_wrap=True))


# --------------------------------------------------------------------- search
@cli.command()
@click.argument("query")
@click.option("--limit", default=20, type=int)
@click.pass_context
def search(ctx: click.Context, query: str, limit: int) -> None:
    """Full-text search the catalog."""
    cfg = _config_from_ctx(ctx)
    index = CatalogIndex(cfg)
    hits = index.search(query, limit=limit)
    if not hits:
        console.print("[yellow]no hits[/]")
        return
    table = Table(title=f"Search results for {query!r}")
    table.add_column("kind")
    table.add_column("ref")
    table.add_column("title", overflow="fold")
    table.add_column("snippet", overflow="fold")
    for h in hits:
        table.add_row(h.kind, h.ref, h.title, h.snippet)
    console.print(table)


cli.add_command(transparency_group)
cli.add_command(passport_group)
cli.add_command(proxy_group)
cli.add_command(webhook_group)
cli.add_command(vendor_group)
cli.add_command(refresh_group)


# --------------------------------------------------------------------- analyzer
@cli.group()
def analyzer() -> None:
    """Offline analysis tooling (triage model training, etc.)."""


@analyzer.command("triage-train")
@click.option("--out", default=None, help="Artifact output path.")
@click.option("--seed", default=1234, type=int, help="Deterministic training seed.")
@click.option("--version", default="v1", help="Artifact version label.")
@click.pass_context
def analyzer_triage_train(ctx: click.Context, out: str | None, seed: int, version: str) -> None:
    """Train the dependency-light triage model into a versioned JSON artifact."""
    from scripts.train_triage import main as train_main

    cfg = _config_from_ctx(ctx)
    argv = ["--catalog", str(cfg.catalog_dir), "--seed", str(seed), "--version", version]
    if out:
        argv += ["--out", out]
    rc = train_main(argv)
    if rc != 0:
        raise click.ClickException(f"triage-train failed (exit {rc})")


# --------------------------------------------------------------------- adapters
@cli.group()
def adapters() -> None:
    """MCP adapter scaffolding (Docker image + mcp.json generator)."""


@adapters.command("scaffold")
@click.option("--from-profile", "slug", required=True, help="Slug of an enriched profile.")
@click.option(
    "--commit-pin",
    default=None,
    help="Pin to a specific commit SHA. Defaults to HEAD of the repo's default branch.",
)
@click.option("--no-verify", is_flag=True, help="Skip docker build verification.")
@click.pass_context
def adapters_scaffold(
    ctx: click.Context, slug: str, commit_pin: str | None, no_verify: bool
) -> None:
    """Generate a Dockerfile + mcp.json adapter for an enriched profile."""
    import json as _json
    import os as _os

    from smadp.autopilot.scaffolders.docker_verify import verify_adapter_build
    from smadp.autopilot.scaffolders.language_detector import GithubMetadataLanguageDetector
    from smadp.autopilot.scaffolders.mcp_adapter import MCPAdapterScaffolder

    config = ctx.obj["config"]
    profile_path = config.repo_root / "catalog" / "profiles" / f"{slug}.json"
    if not profile_path.exists():
        raise click.ClickException(f"profile not found: {profile_path}")
    profile = _json.loads(profile_path.read_text("utf-8"))

    token = _os.environ.get("GITHUB_TOKEN")
    detector = GithubMetadataLanguageDetector(token=token)

    def resolve_pin(github_source: str) -> str:
        if commit_pin:
            return commit_pin
        return "HEAD"

    scaffolder = MCPAdapterScaffolder(detector=detector, commit_pin_resolver=resolve_pin)
    target_dir = config.repo_root / "adapters" / slug
    result = scaffolder.scaffold(profile, target_dir=target_dir)

    click.echo(f"scaffold: success={result.success} reason={result.reason} dir={result.target_dir}")
    if not result.success:
        raise click.ClickException(f"scaffold failed: {result.reason}")

    if no_verify:
        click.echo("skip-verify: per --no-verify flag")
        return

    verify = verify_adapter_build(result.target_dir, image_tag=f"smadp/agent/{slug}:scaffold")
    click.echo(f"verify: success={verify.success} skipped={verify.skipped} reason={verify.reason}")
    if not verify.success and not verify.skipped:
        prov_path = result.target_dir / ".scaffolded.json"
        prov = _json.loads(prov_path.read_text("utf-8"))
        prov["verify"] = {
            "success": False,
            "reason": verify.reason,
            "build_log_tail": verify.build_log_tail,
        }
        prov_path.write_text(_json.dumps(prov, indent=2) + "\n", encoding="utf-8")
        raise click.ClickException(f"docker build failed: see {prov_path}")


# --------------------------------------------------------------------- pending
@cli.group()
def pending() -> None:
    """Review queue for autopilot-produced verdicts before they're published."""


@pending.command("init-signing-key")
def pending_init_signing_key() -> None:
    """Provision the BYOK Ed25519 key used to sign published verdicts.

    Generates a fresh Ed25519 key, stores it (AES-GCM encrypted at rest) under
    the ``_smadp_publisher`` workspace, and prints the public key hex. Once set,
    ``pending approve`` and ``autopilot approve`` write a detached signature
    sidecar next to each published verdict.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    from smadp.autopilot.pending import PUBLISHER_WORKSPACE_ID, ensure_publisher_workspace
    from smadp.tenancy import keys

    cfg = load_config()
    ensure_publisher_workspace(config=cfg)
    existing = keys.load_signing_key(workspace_id=PUBLISHER_WORKSPACE_ID, config=cfg)
    if existing is not None:
        pub = (
            existing.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw).hex()
        )
        console.print("[yellow]publisher signing key already provisioned[/]")
        console.print(f"public_key_hex: {pub}")
        return
    priv = Ed25519PrivateKey.generate()
    keys.upload_signing_key(workspace_id=PUBLISHER_WORKSPACE_ID, private_key=priv, config=cfg)
    pub = priv.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw).hex()
    console.print(f"[green]provisioned publisher signing key[/]\npublic_key_hex: {pub}")


@pending.command("list")
@click.option("--tier", type=str, default=None, help="Filter by evidence_level (e.g. docs-only).")
@click.option(
    "--min-confidence",
    type=float,
    default=None,
    help="Only show verdicts with confidence >= this value (0-1).",
)
@click.option(
    "--max-composite",
    type=float,
    default=None,
    help="Only show verdicts with composite_score <= this value (lower = safer).",
)
@click.option(
    "--pair-contains",
    type=str,
    default=None,
    help="Substring match against any slug in the pair (e.g. 'aider').",
)
@click.option("--limit", type=int, default=50, help="Max rows to display.")
@click.pass_context
def pending_list(
    ctx: click.Context,
    tier: str | None,
    min_confidence: float | None,
    max_composite: float | None,
    pair_contains: str | None,
    limit: int,
) -> None:
    """List pending verdicts awaiting review."""
    from smadp.autopilot.pending import list_pending

    cfg = _config_from_ctx(ctx)
    rows = list_pending(
        repo_root=cfg.repo_root,
        tier=tier,
        min_confidence=min_confidence,
        max_composite=max_composite,
        pair_contains=pair_contains,
        limit=limit,
    )
    if not rows:
        click.echo("no pending verdicts match the filter")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("key", style="cyan", overflow="fold", max_width=58)
    table.add_column("pair", style="white")
    table.add_column("tier", style="magenta")
    table.add_column("conf", justify="right")
    table.add_column("score", justify="right")
    table.add_column("headline", overflow="fold", max_width=40)
    for v in rows:
        table.add_row(
            v.key,
            " x ".join(v.pair),
            v.evidence_level,
            f"{v.confidence:.2f}",
            f"{v.composite_score:.2f}",
            v.headline[:60],
        )
    console.print(table)
    click.echo(f"{len(rows)} shown")


@pending.command("show")
@click.argument("key")
@click.pass_context
def pending_show(ctx: click.Context, key: str) -> None:
    """Pretty-print a single pending verdict."""
    cfg = _config_from_ctx(ctx)
    path = cfg.repo_root / "catalog" / "pending" / f"{key}.json"
    if not path.exists():
        raise click.ClickException(f"no pending verdict at {path}")
    console.print(Syntax(path.read_text("utf-8"), "json", theme="monokai", line_numbers=False))


@pending.command("approve")
@click.argument("keys", nargs=-1)
@click.option("--tier", type=str, default=None)
@click.option("--min-confidence", type=float, default=None)
@click.option("--max-composite", type=float, default=None)
@click.option("--pair-contains", type=str, default=None)
@click.option("--limit", type=int, default=None, help="Cap on batch size (only with filters).")
@click.option(
    "--all",
    "approve_all",
    is_flag=True,
    help="Approve every pending verdict that matches the filters (no limit).",
)
@click.option("--yes", "yes_flag", is_flag=True, help="Skip the confirmation prompt for batches.")
@click.pass_context
def pending_approve(
    ctx: click.Context,
    keys: tuple[str, ...],
    tier: str | None,
    min_confidence: float | None,
    max_composite: float | None,
    pair_contains: str | None,
    limit: int | None,
    approve_all: bool,
    yes_flag: bool,
) -> None:
    """Approve pending verdicts. Pass explicit keys, or filters + --limit/--all for bulk."""
    from smadp.autopilot.pending import approve_batch, list_pending

    cfg = _config_from_ctx(ctx)
    explicit = list(keys)
    if explicit:
        moved = approve_batch(repo_root=cfg.repo_root, keys=explicit)
        click.echo(f"approved {len(moved)} explicit key(s)")
        return
    if limit is None and not approve_all:
        raise click.ClickException(
            "no keys given. Pass --limit N or --all to bulk-approve by filter."
        )
    # Preview the batch first; require --yes for non-trivial sizes.
    preview = list_pending(
        repo_root=cfg.repo_root,
        tier=tier,
        min_confidence=min_confidence,
        max_composite=max_composite,
        pair_contains=pair_contains,
        limit=limit,
    )
    if not preview:
        click.echo("no pending verdicts match the filter; nothing approved")
        return
    if not yes_flag and len(preview) > 5:
        sample = ", ".join(v.key for v in preview[:3])
        click.echo(
            f"About to approve {len(preview)} verdicts (sample: {sample}…). "
            f"Re-run with --yes to confirm."
        )
        return
    moved = approve_batch(
        repo_root=cfg.repo_root,
        tier=tier,
        min_confidence=min_confidence,
        max_composite=max_composite,
        pair_contains=pair_contains,
        limit=limit,
    )
    click.echo(f"approved {len(moved)} verdict(s)")


@pending.command("reject")
@click.argument("key")
@click.option("--reason", required=True, help="Why this verdict is being rejected (audit log).")
@click.pass_context
def pending_reject(ctx: click.Context, key: str, reason: str) -> None:
    """Move a pending verdict to catalog/_rejected/ (preserved with a reason)."""
    from smadp.autopilot.pending import reject_one

    cfg = _config_from_ctx(ctx)
    target = reject_one(key=key, repo_root=cfg.repo_root, reason=reason)
    click.echo(f"rejected → {target}")


# ----------------------------------------------------------------------- entry
def main() -> None:
    """Entry point declared in pyproject.toml."""
    try:
        cli(standalone_mode=False)
    except click.ClickException as exc:
        exc.show()
        sys.exit(exc.exit_code)
    except click.exceptions.Exit as exc:
        sys.exit(exc.exit_code)


if __name__ == "__main__":
    main()
