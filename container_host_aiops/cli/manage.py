"""``container-host-aiops manage`` — guarded writes (dry-run + double-confirm)."""

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
    get_connection,
)

manage_app = typer.Typer(
    name="manage",
    help="Guarded writes: restart/stop/start/remove, prune, update, recreate-stack.",
    no_args_is_help=True,
)

CidArg = Annotated[str, typer.Argument(help="Container id or name")]


@manage_app.command("restart")
@cli_errors
def restart(
    container_id: CidArg, target: TargetOption = None, dry_run: DryRunOption = False
) -> None:
    """Restart a container (dry-run + confirm)."""
    from container_host_aiops.ops import writes as ops

    if dry_run:
        dry_run_print(
            operation="restart_container",
            api_call=f"POST /containers/{container_id}/restart",
        )
        return
    double_confirm("restart", container_id)
    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.restart_container(conn, container_id)))


@manage_app.command("stop")
@cli_errors
def stop(
    container_id: CidArg, target: TargetOption = None, dry_run: DryRunOption = False
) -> None:
    """Stop a running container (undo: start; dry-run + confirm)."""
    from container_host_aiops.ops import writes as ops

    if dry_run:
        dry_run_print(operation="stop_container", api_call=f"POST /containers/{container_id}/stop")
        return
    double_confirm("stop", container_id)
    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.stop_container(conn, container_id)))


@manage_app.command("start")
@cli_errors
def start(
    container_id: CidArg, target: TargetOption = None, dry_run: DryRunOption = False
) -> None:
    """Start a stopped container (undo: stop; dry-run + confirm)."""
    from container_host_aiops.ops import writes as ops

    if dry_run:
        dry_run_print(
            operation="start_container",
            api_call=f"POST /containers/{container_id}/start",
        )
        return
    double_confirm("start", container_id)
    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.start_container(conn, container_id)))


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
    from container_host_aiops.ops import writes as ops

    if dry_run:
        dry_run_print(
            operation="remove_container",
            api_call=f"DELETE /containers/{container_id}",
            parameters={"force": force, "volumes": volumes},
        )
        return
    double_confirm("remove", container_id)
    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.remove_container(conn, container_id, force, volumes)))


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
    from container_host_aiops.ops import writes as ops

    conn, _ = get_connection(target)
    if dry_run:
        preview = ops.preview_prune_images(conn, dangling_only=not all_unused)
        console.print_json(json.dumps({"dryRun": True, **preview}))
        return
    double_confirm("prune images on", "this host")
    console.print_json(json.dumps(ops.prune_images(conn, dangling_only=not all_unused)))


@manage_app.command("prune-volumes")
@cli_errors
def prune_volumes(target: TargetOption = None, dry_run: DryRunOption = False) -> None:
    """Prune unreferenced volumes (dry-run lists candidates + confirm)."""
    from container_host_aiops.ops import writes as ops

    conn, _ = get_connection(target)
    if dry_run:
        console.print_json(json.dumps({"dryRun": True, **ops.preview_prune_volumes(conn)}))
        return
    double_confirm("prune volumes on", "this host")
    console.print_json(json.dumps(ops.prune_volumes(conn)))


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
    from container_host_aiops.ops import writes as ops

    resources = json.loads(resources_json)
    if dry_run:
        dry_run_print(
            operation="update_container",
            api_call=f"POST /containers/{container_id}/update",
            parameters=resources,
        )
        return
    double_confirm("update resource limits on", container_id)
    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.update_container(conn, container_id, resources)))


@manage_app.command("recreate-stack")
@cli_errors
def recreate_stack(
    stack_id: Annotated[str, typer.Argument(help="Portainer stack id")],
    endpoint_id: Annotated[str | None, typer.Option("--endpoint-id", help="Endpoint id")] = None,
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Recreate (redeploy) a Portainer stack (no undo; dry-run + confirm)."""
    from container_host_aiops.ops import writes as ops

    if dry_run:
        dry_run_print(
            operation="recreate_stack",
            api_call=f"PUT /api/stacks/{stack_id}/git/redeploy",
            parameters={"endpoint_id": endpoint_id},
        )
        return
    double_confirm("recreate stack", stack_id)
    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.recreate_stack(conn, stack_id, endpoint_id)))
