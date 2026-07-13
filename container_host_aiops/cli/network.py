"""``container-host-aiops network`` — Docker network reads."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from container_host_aiops.cli._common import TargetOption, cli_errors, console, get_connection

network_app = typer.Typer(
    name="network",
    help="Docker networks: list, inspect.",
    no_args_is_help=True,
)

NetArg = Annotated[str, typer.Argument(help="Network id or name")]


@network_app.command("list")
@cli_errors
def network_list(target: TargetOption = None) -> None:
    """List Docker networks, bucketed by driver."""
    from container_host_aiops.ops import networks as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.list_networks(conn)))


@network_app.command("inspect")
@cli_errors
def network_inspect(network_id: NetArg, target: TargetOption = None) -> None:
    """Inspect one network (driver, IPAM, attached containers)."""
    from container_host_aiops.ops import networks as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.inspect_network(conn, network_id)))
