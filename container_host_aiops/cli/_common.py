"""Shared helpers for container-host-aiops CLI sub-modules."""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

console = Console()

# ─── Shared Option types ───────────────────────────────────────────────────

TargetOption = Annotated[
    str | None, typer.Option("--target", "-t", help="Target name from config")
]
DryRunOption = Annotated[
    bool, typer.Option("--dry-run", help="Print the API call without executing")
]


EXIT_UNDETERMINED = 2


def checked(result: Any) -> Any:
    """Return ``result``, or abort when it reports a failed/undetermined write.

    Every CLI command that calls a governed twin MUST pass its result through
    here before reporting success.

    Governed twins are wrapped in ``@tool_errors``, which flattens any exception
    into ``{"error": ...}`` and **returns** it — the CLI never sees the
    exception. Without this check the command prints the payload and exits 0,
    so a *refused* write is indistinguishable from a successful one to anything
    reading the exit status. Live-caught against a real Portainer 2.39.5
    (2026-08-03): stopping the Portainer container itself was correctly refused
    by the self-lockout guard, and the CLI still exited 0. The dry-run path
    already refused with exit 1, which made the asymmetry worse — the preview
    was stricter than the real call. Same defect class already fixed in
    proxmox-, xcpng-, veeam- and truenas-aiops; this repo was never swept.
    """
    if not isinstance(result, dict):
        return result
    error = result.get("error")
    # ``outcomeUnknown`` is judged BEFORE ``error``, matching the harness: a
    # write whose response was lost carries BOTH keys, and it is audited
    # `unknown` precisely because it may have taken effect. Reporting that as a
    # plain failure would tell a script the change did not happen and invite the
    # double-apply the payload's own note warns about.
    if result.get("outcomeUnknown"):
        console.print(f"[yellow]Outcome undetermined: {result.get('note') or ''}[/]")
        raise typer.Exit(EXIT_UNDETERMINED)
    if error:
        console.print(f"[red]Error: {error}[/]")
        hint = result.get("hint")
        if hint:
            console.print(f"[dim]{hint}[/]")
        raise typer.Exit(1)
    return result


def _cli_error_types() -> tuple[type[BaseException], ...]:
    """Exceptions translated to a one-line teaching error instead of a traceback.

    ``PolicyDenied`` belongs here even though it is not a ValueError: its message
    names the exact env var to set and why, which is the single most actionable
    error this tool produces. Without it a high-risk command with no approver
    exits 1 printing NOTHING — a bare traceback for the product's flagship
    graduated-approval feature.
    """
    from container_host_aiops.connection import ContainerHostApiError
    from container_host_aiops.governance import PolicyDenied

    return (ContainerHostApiError, KeyError, OSError, ValueError, PolicyDenied)


def cli_errors(fn: Callable) -> Callable:
    """Translate known exceptions into one red line + exit code 1."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (typer.Exit, typer.Abort):
            raise
        except _cli_error_types() as e:
            message = str(e)
            if isinstance(e, KeyError):
                message = f"Missing required key or environment variable: {message}"
            console.print(f"[red]Error: {message}[/]")
            raise typer.Exit(1) from e

    return wrapper


def get_connection(target: str | None, config_path: Path | None = None) -> tuple[Any, Any]:
    """Return a (conn, config) tuple for the given target."""
    from container_host_aiops.config import load_config
    from container_host_aiops.connection import ConnectionManager

    cfg = load_config(config_path)
    mgr = ConnectionManager(cfg)
    return mgr.connect(target), cfg


def dry_run_print(*, operation: str, api_call: str, parameters: dict | None = None) -> None:
    """Print a dry-run preview of the API call that would be made."""
    console.print("\n[bold magenta][DRY-RUN] No changes will be made.[/]")
    console.print(f"[magenta]  Operation: {operation}[/]")
    console.print(f"[magenta]  API Call:  {api_call}[/]")
    for k, v in (parameters or {}).items():
        console.print(f"[magenta]  Param:     {k} = {v}[/]")
    console.print("[magenta]  Run without --dry-run to execute.[/]\n")


def dry_run_result(
    result: Any,
    *,
    operation: str,
    api_call: str,
    payload_key: str = "",
    parameters: dict | None = None,
) -> None:
    """Render a governed dry-run result as the human DRY-RUN banner, or refuse.

    CLI previews route through the ``@governed_tool``-wrapped twin so they run
    the same guards and land the same audit row as the real call — the CLI
    silently not auditing previews was the outlier, since MCP previews have
    always been audited. Only the *serialization* stays CLI-shaped: the caller
    is a human, so the returned dict is rendered into the existing banner rather
    than dumped as JSON.

    A preview that cannot be refused would promise an operation the write then
    rejects, so a refusal is surfaced exactly like a refused real write: the
    teaching message in red, exit code 1.

    Invariant: **a dry_run MAY read; it must never write.**

    ``payload_key`` pulls the banner parameters straight out of the governed
    dict, so the preview shows the tool's real resolved state rather than a
    hand-written guess. Pass ``parameters`` instead when the caller has already
    reshaped that state into something more readable than the raw payload.
    """
    if isinstance(result, dict) and result.get("error"):
        console.print(f"[red]Error: {result['error']}[/]")
        raise typer.Exit(1)
    if parameters is None:
        payload = result.get(payload_key) if isinstance(result, dict) and payload_key else None
        parameters = payload if isinstance(payload, dict) else None
    dry_run_print(operation=operation, api_call=api_call, parameters=parameters)


def double_confirm(action: str, resource: str) -> None:
    """Require two confirmations for a destructive operation."""
    console.print(f"[bold yellow]⚠️  About to: {action} '{resource}'[/]")
    typer.confirm(f"Confirm 1/2: {action} '{resource}'?", abort=True)
    typer.confirm(
        f"Confirm 2/2: really {action} '{resource}'? This may be irreversible.",
        abort=True,
    )
