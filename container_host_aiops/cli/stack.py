"""``container-host-aiops stack`` — Portainer stack + endpoint reads."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from container_host_aiops.cli._common import TargetOption, cli_errors, console, get_connection

stack_app = typer.Typer(
    name="stack",
    help="Portainer stacks + endpoints (requires a portainer target).",
    no_args_is_help=True,
)

StackArg = Annotated[str, typer.Argument(help="Portainer stack id")]


@stack_app.command("endpoints")
@cli_errors
def stack_endpoints(target: TargetOption = None) -> None:
    """Portainer endpoints (managed hosts)."""
    from container_host_aiops.ops import stacks as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.list_endpoints(conn)))


@stack_app.command("list")
@cli_errors
def stack_list(target: TargetOption = None) -> None:
    """Portainer stacks (Compose/Swarm)."""
    from container_host_aiops.ops import stacks as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.list_stacks(conn)))


@stack_app.command("detail")
@cli_errors
def stack_detail(stack_id: StackArg, target: TargetOption = None) -> None:
    """One Portainer stack in detail."""
    from container_host_aiops.ops import stacks as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.stack_detail(conn, stack_id)))
