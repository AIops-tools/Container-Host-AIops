"""``container-host-aiops overview`` — one-shot container-host health."""

from __future__ import annotations

import json

from container_host_aiops.cli._common import TargetOption, cli_errors, console, get_connection


@cli_errors
def overview_cmd(target: TargetOption = None) -> None:
    """One-shot host summary: version + container state rollup + disk headline."""
    from container_host_aiops.ops import overview as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.host_overview(conn)))
