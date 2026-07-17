"""``container-host-aiops pod`` — Podman pod reads (requires a podman target)."""

from __future__ import annotations

import json

import typer

from container_host_aiops.cli._common import TargetOption, cli_errors, console, get_connection

pod_app = typer.Typer(
    name="pod",
    help="Podman pods (requires a podman target — Docker/Portainer have no pods).",
    no_args_is_help=True,
)


@pod_app.command("list")
@cli_errors
def pod_list(target: TargetOption = None) -> None:
    """List Podman pods (id, name, status, member containers)."""
    from container_host_aiops.ops import pods as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.list_pods(conn)))
