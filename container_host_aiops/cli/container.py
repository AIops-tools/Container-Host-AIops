"""``container-host-aiops container`` — container-scoped reads."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from container_host_aiops.cli._common import TargetOption, cli_errors, console, get_connection

container_app = typer.Typer(
    name="container",
    help="Containers: list, inspect, logs, stats, top, restart summary.",
    no_args_is_help=True,
)

CidArg = Annotated[str, typer.Argument(help="Container id or name")]


@container_app.command("list")
@cli_errors
def container_list(
    running: Annotated[bool, typer.Option("--running", help="Only running")] = False,
    target: TargetOption = None,
) -> None:
    """List containers (all states by default, or only running)."""
    from container_host_aiops.ops import containers as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.list_containers(conn, all_states=not running)))


@container_app.command("inspect")
@cli_errors
def container_inspect(container_id: CidArg, target: TargetOption = None) -> None:
    """Full inspect of one container."""
    from container_host_aiops.ops import containers as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.inspect_container(conn, container_id)))


@container_app.command("logs")
@cli_errors
def container_logs(
    container_id: CidArg,
    tail: Annotated[int, typer.Option(help="Lines from the end (1..2000)")] = 100,
    target: TargetOption = None,
) -> None:
    """Tail the last N log lines of a container."""
    from container_host_aiops.ops import containers as ops

    conn, _ = get_connection(target)
    result = ops.container_logs(conn, container_id, tail)
    console.print_json(json.dumps(result))
    if result.get("truncated"):
        console.print(
            f"[yellow]… truncated at {result.get('limit')} lines — "
            f"re-run with a higher --tail to see more history.[/yellow]"
        )


@container_app.command("stats")
@cli_errors
def container_stats(container_id: CidArg, target: TargetOption = None) -> None:
    """One-shot CPU%/memory% snapshot for a container."""
    from container_host_aiops.ops import containers as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.container_stats(conn, container_id)))


@container_app.command("top")
@cli_errors
def container_top(container_id: CidArg, target: TargetOption = None) -> None:
    """Processes running inside a container."""
    from container_host_aiops.ops import containers as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.container_top(conn, container_id)))


@container_app.command("restarts")
@cli_errors
def container_restarts(target: TargetOption = None) -> None:
    """Restart-count + exit-code summary across containers."""
    from container_host_aiops.ops import containers as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.restart_summary(conn)))
