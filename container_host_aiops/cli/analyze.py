"""``container-host-aiops analyze`` — the flagship signature analyses."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from container_host_aiops.cli._common import TargetOption, cli_errors, console, get_connection

analyze_app = typer.Typer(
    name="analyze",
    help="Flagship analyses: restart-loop RCA, resource pressure, image/volume bloat.",
    no_args_is_help=True,
)


@analyze_app.command("restart-loop")
@cli_errors
def analyze_restart_loop(
    threshold: Annotated[int, typer.Option(help="Restart count = looping")] = 3,
    target: TargetOption = None,
) -> None:
    """Find crash-looping containers and map each to a cause + action."""
    from container_host_aiops.ops import analyses as ops

    conn, _ = get_connection(target)
    rows, logs = ops.pull_restart_data(conn)
    console.print_json(json.dumps(ops.restart_loop_rca(rows, logs, threshold)))


@analyze_app.command("resource-pressure")
@cli_errors
def analyze_resource_pressure(
    cpu: Annotated[float, typer.Option(help="CPU%% = over pressure")] = 80.0,
    mem: Annotated[float, typer.Option(help="Memory%% = over pressure")] = 80.0,
    target: TargetOption = None,
) -> None:
    """Rank running containers by CPU/memory pressure vs their limits."""
    from container_host_aiops.ops import analyses as ops

    conn, _ = get_connection(target)
    samples = ops.pull_resource_pressure(conn)
    console.print_json(json.dumps(ops.resource_pressure_analysis(samples, cpu, mem)))


@analyze_app.command("bloat")
@cli_errors
def analyze_bloat(target: TargetOption = None) -> None:
    """Dangling images + volumes + build cache → prune candidates."""
    from container_host_aiops.ops import analyses as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.pull_bloat(conn)))
