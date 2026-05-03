"""SMADP command-line interface (`smadp`).

Click-based, Rich-rendered. Subcommands are listed in §16 of the design spec.
External LLM/sandbox dependencies are imported lazily so the CLI is usable
even in environments where those subsystems aren't installed.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
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
from smadp.utils.slug import normalize_slug, sort_pair

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
        new_verdict = _gv(profile_a=profile_a, profile_b=profile_b)  # type: ignore[misc]
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
                    v = generate_verdict(  # type: ignore[misc]
                        profile_a=repo.load_profile(a),
                        profile_b=repo.load_profile(b),
                        scenario=scenario,
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
@click.option("--scenario", default=None)
@click.pass_context
def sandbox_run(ctx: click.Context, slug_a: str, slug_b: str, scenario: str | None) -> None:
    """Enqueue a sandbox run."""
    cfg = _config_from_ctx(ctx)
    repo = CatalogRepo(cfg)
    a, b = sort_pair(slug_a, slug_b)
    for slug in (a, b):
        if not repo.profile_exists(slug):
            err_console.print(f"[red]unknown agent:[/] {slug}")
            ctx.exit(2)
            return
    try:
        from smadp.sandbox.queue import enqueue_sandbox_run  # type: ignore[import-not-found]
    except Exception as exc:
        err_console.print(f"[red]sandbox subsystem unavailable:[/] {exc}")
        ctx.exit(1)
        return
    record = enqueue_sandbox_run(slug_a=a, slug_b=b, scenario=scenario)  # type: ignore[misc]
    if isinstance(record, dict):
        console.print(
            f"[green]queued[/] run_id={record.get('run_id')} "
            f"pair={a} <> {b} scenario={scenario or '-'}"
        )
    else:
        console.print(f"[green]queued[/] run_id={record} pair={a} <> {b}")


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


@sandbox.command("runs")
@click.option("--limit", default=50, type=int)
@click.pass_context
def sandbox_runs(ctx: click.Context, limit: int) -> None:
    """List recent sandbox runs (any status)."""
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
    for r in list(records)[:limit]:
        if not isinstance(r, dict):
            continue
        pair = r.get("pair") or [r.get("slug_a"), r.get("slug_b")]
        table.add_row(
            str(r.get("run_id", "")),
            f"{pair[0]} <> {pair[1]}",
            str(r.get("status", "")),
            str(r.get("outcome", "-")),
            str(r.get("queued_at", r.get("created_at", "-"))),
        )
    console.print(table)


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
