"""``container-host-aiops volume`` — volume-scoped reads."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from container_host_aiops.cli._common import TargetOption, cli_errors, console, get_connection

volume_app = typer.Typer(
    name="volume",
    help="Volumes: list, inspect, dangling.",
    no_args_is_help=True,
)

NameArg = Annotated[str, typer.Argument(help="Volume name")]


@volume_app.command("list")
@cli_errors
def volume_list(target: TargetOption = None) -> None:
    """List named volumes."""
    from container_host_aiops.ops import volumes as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.list_volumes(conn)))


@volume_app.command("inspect")
@cli_errors
def volume_inspect(name: NameArg, target: TargetOption = None) -> None:
    """Inspect one named volume."""
    from container_host_aiops.ops import volumes as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.inspect_volume(conn, name)))


@volume_app.command("dangling")
@cli_errors
def volume_dangling(target: TargetOption = None) -> None:
    """Dangling (unreferenced) volumes + reclaimable bytes."""
    from container_host_aiops.ops import volumes as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.dangling_volumes(conn)))
