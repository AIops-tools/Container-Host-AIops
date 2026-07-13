"""``container-host-aiops image`` — image-scoped reads."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from container_host_aiops.cli._common import TargetOption, cli_errors, console, get_connection

image_app = typer.Typer(
    name="image",
    help="Images: list, inspect (with history), dangling, disk usage.",
    no_args_is_help=True,
)

ImageArg = Annotated[str, typer.Argument(help="Image id or name:tag")]


@image_app.command("list")
@cli_errors
def image_list(
    all_images: Annotated[bool, typer.Option("--all", help="Include intermediate layers")] = False,
    target: TargetOption = None,
) -> None:
    """List images (largest first)."""
    from container_host_aiops.ops import images as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.list_images(conn, all_images)))


@image_app.command("inspect")
@cli_errors
def image_inspect(image_id: ImageArg, target: TargetOption = None) -> None:
    """Inspect an image plus its build history."""
    from container_host_aiops.ops import images as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.inspect_image(conn, image_id)))


@image_app.command("dangling")
@cli_errors
def image_dangling(target: TargetOption = None) -> None:
    """Untagged (dangling) images + reclaimable bytes."""
    from container_host_aiops.ops import images as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.dangling_images(conn)))


@image_app.command("disk-usage")
@cli_errors
def image_disk_usage(target: TargetOption = None) -> None:
    """Image disk usage from system/df."""
    from container_host_aiops.ops import images as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.image_disk_usage(conn)))
