"""Click subcommands for webhooks: subscriptions ls/create/delete, deliveries ls, worker."""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table

from smadp.config import load_config
from smadp.schemas.webhooks import EventType
from smadp.webhooks import deliveries, store, worker

console = Console()


@click.group(name="webhook")
def webhook_group() -> None:
    """Manage webhook subscriptions, view deliveries, run the delivery worker."""


# --- subscriptions ---------------------------------------------------------

@webhook_group.group(name="subscriptions")
def subscriptions_group() -> None:
    """Create / list / delete webhook subscriptions."""


@subscriptions_group.command(name="create")
@click.option("--workspace", "workspace_id", required=True, help="Workspace id.")
@click.option("--url", required=True, help="HTTPS URL to POST events to.")
@click.option(
    "--event",
    "events",
    multiple=True,
    required=True,
    help="Event type to subscribe to (repeatable).",
)
def subscriptions_create(workspace_id: str, url: str, events: tuple[str, ...]) -> None:
    cfg = load_config()
    try:
        event_types = [EventType(e) for e in events]
    except ValueError as exc:
        console.print(f"[red]invalid event type:[/red] {exc}")
        sys.exit(2)
    sub, secret = store.create_subscription(
        workspace_id=workspace_id, url=url, event_types=event_types, config=cfg
    )
    console.print(f"[green]created[/green] {sub.id}")
    console.print(f"  url:    {sub.url}")
    console.print(f"  events: {', '.join(t.value for t in sub.event_types)}")
    console.print(f"  secret: [bold]{secret}[/bold]   (shown once — save it now)")


@subscriptions_group.command(name="ls")
@click.option("--workspace", "workspace_id", required=True, help="Workspace id.")
def subscriptions_ls(workspace_id: str) -> None:
    cfg = load_config()
    rows = store.list_subscriptions(workspace_id=workspace_id, config=cfg)
    if not rows:
        console.print("[yellow]no subscriptions[/yellow]")
        return
    t = Table(title=f"Subscriptions for {workspace_id}")
    t.add_column("id")
    t.add_column("url", overflow="fold")
    t.add_column("events")
    t.add_column("active")
    for s in rows:
        t.add_row(
            s.id,
            s.url,
            ", ".join(e.value for e in s.event_types),
            "yes" if s.active else "no",
        )
    console.print(t)


@subscriptions_group.command(name="delete")
@click.argument("subscription_id")
def subscriptions_delete(subscription_id: str) -> None:
    cfg = load_config()
    try:
        store.deactivate_subscription(subscription_id=subscription_id, config=cfg)
    except KeyError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(2)
    console.print(f"[green]deactivated[/green] {subscription_id}")


# --- deliveries ------------------------------------------------------------

@webhook_group.group(name="deliveries")
def deliveries_group() -> None:
    """Inspect webhook delivery rows."""


@deliveries_group.command(name="ls")
@click.option("--limit", default=50, type=int)
def deliveries_ls(limit: int) -> None:
    cfg = load_config()
    rows = list(deliveries.iter_all(config=cfg))[-limit:]
    if not rows:
        console.print("[yellow]no deliveries[/yellow]")
        return
    t = Table(title=f"Webhook deliveries (last {len(rows)})")
    t.add_column("id")
    t.add_column("event_type", no_wrap=True)
    t.add_column("status")
    t.add_column("attempts")
    t.add_column("subscription")
    t.add_column("error", overflow="fold")
    for d in rows:
        t.add_row(
            d.id,
            d.event_type.value,
            d.status.value,
            str(d.attempts),
            d.subscription_id,
            d.last_error or "-",
        )
    console.print(t)


# --- worker ----------------------------------------------------------------

@webhook_group.command(name="worker")
@click.option("--once", is_flag=True, help="Process one pending row, then exit.")
@click.option(
    "--max-iterations",
    type=int,
    default=None,
    help="Bound the loop (for tests/CI).",
)
def worker_cmd(once: bool, max_iterations: int | None) -> None:
    cfg = load_config()
    if once:
        did = worker.process_one_pending(config=cfg)
        if did:
            console.print("[green]processed one delivery[/green]")
        else:
            console.print("[yellow]no pending deliveries[/yellow]")
        return
    n = worker.run_loop(config=cfg, max_iterations=max_iterations)
    console.print(f"[green]processed {n} deliveries[/green]")


__all__ = ["webhook_group"]
