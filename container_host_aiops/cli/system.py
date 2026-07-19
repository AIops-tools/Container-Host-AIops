"""``container-host-aiops system`` — host system reads."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from container_host_aiops.cli._common import TargetOption, cli_errors, console, get_connection

system_app = typer.Typer(
    name="system",
    help="Host system: info, version, df (disk usage), events.",
    no_args_is_help=True,
)


@system_app.command("info")
@cli_errors
def system_info(target: TargetOption = None) -> None:
    """Daemon info: container/image counts, storage driver, kernel, resources."""
    from container_host_aiops.ops import system as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.system_info(conn)))


@system_app.command("version")
@cli_errors
def system_version(target: TargetOption = None) -> None:
    """Docker version details (API version, components)."""
    from container_host_aiops.ops import system as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.system_version(conn)))


@system_app.command("df")
@cli_errors
def system_df(target: TargetOption = None) -> None:
    """Disk-usage breakdown: images, containers, volumes, build cache."""
    from container_host_aiops.ops import system as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.system_df(conn)))


@system_app.command("events")
@cli_errors
def system_events(
    since: Annotated[int, typer.Option(help="Look-back window in seconds")] = 3600,
    event_type: Annotated[str | None, typer.Option("--type", help="Filter event type")] = None,
    target: TargetOption = None,
) -> None:
    """Recent daemon events, rolled up by type + action."""
    from container_host_aiops.ops import system as ops

    conn, _ = get_connection(target)
    result = ops.recent_events(conn, since, event_type)
    console.print_json(json.dumps(result))
    if result.get("truncated"):
        console.print(
            f"[yellow]… truncated at {result.get('limit')} events — "
            f"narrow the window with a smaller --since to see the rest.[/yellow]"
        )
