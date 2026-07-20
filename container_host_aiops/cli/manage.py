"""``container-host-aiops manage`` — guarded writes (dry-run + double-confirm).

Real execution is delegated to the ``@governed_tool``-wrapped functions in
``mcp_server.tools.writes`` so that CLI writes are audited + undo-recorded on the
SAME governance path as the MCP tools (the CLI keeps its own dry-run preview and
human double-confirm on top).
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from container_host_aiops.cli._common import (
    DryRunOption,
    TargetOption,
    cli_errors,
    console,
    double_confirm,
    dry_run_print,
    dry_run_result,
)

manage_app = typer.Typer(
    name="manage",
    help="Guarded writes: restart/stop/start/remove, prune, update, recreate-stack.",
    no_args_is_help=True,
)

CidArg = Annotated[str, typer.Argument(help="Container id or name")]


def _emit(result: dict) -> None:
    console.print_json(json.dumps(result))


@manage_app.command("restart")
@cli_errors
def restart(
    container_id: CidArg, target: TargetOption = None, dry_run: DryRunOption = False
) -> None:
    """Restart a container (dry-run + confirm)."""
    from mcp_server.tools import writes as gov

    if dry_run:
        dry_run_print(
            operation="restart_container",
            api_call=f"POST /containers/{container_id}/restart",
        )
        return
    double_confirm("restart", container_id)
    _emit(gov.restart_container(container_id=container_id, target=target))


@manage_app.command("stop")
@cli_errors
def stop(
    container_id: CidArg, target: TargetOption = None, dry_run: DryRunOption = False
) -> None:
    """Stop a running container (undo: start; dry-run + confirm)."""
    from mcp_server.tools import writes as gov

    if dry_run:
        # Routed through the governed twin so the preview runs the same guards
        # and lands the same audit row as the real stop; the banner stays.
        dry_run_result(
            gov.stop_container(container_id=container_id, dry_run=True, target=target),
            operation="stop_container",
            api_call=f"POST /containers/{container_id}/stop",
            payload_key="wouldStop",
        )
        return
    double_confirm("stop", container_id)
    _emit(gov.stop_container(container_id=container_id, target=target))


@manage_app.command("start")
@cli_errors
def start(
    container_id: CidArg, target: TargetOption = None, dry_run: DryRunOption = False
) -> None:
    """Start a stopped container (undo: stop; dry-run + confirm)."""
    from mcp_server.tools import writes as gov

    if dry_run:
        dry_run_print(
            operation="start_container",
            api_call=f"POST /containers/{container_id}/start",
        )
        return
    double_confirm("start", container_id)
    _emit(gov.start_container(container_id=container_id, target=target))


@manage_app.command("remove")
@cli_errors
def remove(
    container_id: CidArg,
    force: Annotated[
        bool, typer.Option("--force", help="Force-remove a running container")
    ] = False,
    volumes: Annotated[
        bool, typer.Option("--volumes", help="Also remove anonymous volumes")
    ] = False,
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Remove a container (captures full inspect first; no undo; dry-run + confirm)."""
    from mcp_server.tools import writes as gov

    if dry_run:
        dry_run_result(
            gov.remove_container(container_id=container_id, force=force,
                                 remove_volumes=volumes, dry_run=True, target=target),
            operation="remove_container",
            api_call=f"DELETE /containers/{container_id}",
            payload_key="wouldRemove",
        )
        return
    double_confirm("remove", container_id)
    _emit(gov.remove_container(
        container_id=container_id, force=force, remove_volumes=volumes, target=target
    ))


@manage_app.command("prune-images")
@cli_errors
def prune_images(
    all_unused: Annotated[
        bool, typer.Option("--all", help="Also prune images unused by any container")
    ] = False,
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Prune images (dangling by default; dry-run lists candidates + confirm)."""
    from mcp_server.tools import writes as gov

    if dry_run:
        _emit(gov.prune_images(dangling_only=not all_unused, dry_run=True, target=target))
        return
    double_confirm("prune images on", "this host")
    _emit(gov.prune_images(dangling_only=not all_unused, target=target))


@manage_app.command("prune-volumes")
@cli_errors
def prune_volumes(target: TargetOption = None, dry_run: DryRunOption = False) -> None:
    """Prune unreferenced volumes (dry-run lists candidates + confirm)."""
    from mcp_server.tools import writes as gov

    if dry_run:
        _emit(gov.prune_volumes(dry_run=True, target=target))
        return
    double_confirm("prune volumes on", "this host")
    _emit(gov.prune_volumes(target=target))


@manage_app.command("update")
@cli_errors
def update(
    container_id: CidArg,
    resources_json: Annotated[
        str, typer.Argument(help='JSON of limits, e.g. {"Memory":536870912}')
    ],
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Update a container's resource limits (captures prior; undo restores; dry-run + confirm)."""
    from mcp_server.tools import writes as gov

    resources = json.loads(resources_json)
    if dry_run:
        dry_run_print(
            operation="update_container",
            api_call=f"POST /containers/{container_id}/update",
            parameters=resources,
        )
        return
    double_confirm("update resource limits on", container_id)
    _emit(gov.update_container(container_id=container_id, resources=resources, target=target))


@manage_app.command("recreate-stack")
@cli_errors
def recreate_stack(
    stack_id: Annotated[str, typer.Argument(help="Portainer stack id")],
    endpoint_id: Annotated[str | None, typer.Option("--endpoint-id", help="Endpoint id")] = None,
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Recreate (redeploy) a Portainer stack (no undo; dry-run + confirm)."""
    from mcp_server.tools import writes as gov

    if dry_run:
        dry_run_print(
            operation="recreate_stack",
            api_call=f"PUT /api/stacks/{stack_id}/git/redeploy",
            parameters={"endpoint_id": endpoint_id},
        )
        return
    double_confirm("recreate stack", stack_id)
    _emit(gov.recreate_stack(stack_id=stack_id, endpoint_id=endpoint_id, target=target))
