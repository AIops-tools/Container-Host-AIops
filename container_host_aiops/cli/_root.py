"""Top-level Typer app: assembles sub-apps and top-level commands."""

from __future__ import annotations

import typer

from container_host_aiops.cli._common import cli_errors
from container_host_aiops.cli.analyze import analyze_app
from container_host_aiops.cli.container import container_app
from container_host_aiops.cli.doctor import doctor_cmd
from container_host_aiops.cli.image import image_app
from container_host_aiops.cli.init import init_cmd
from container_host_aiops.cli.manage import manage_app
from container_host_aiops.cli.network import network_app
from container_host_aiops.cli.overview import overview_cmd
from container_host_aiops.cli.secret import secret_app
from container_host_aiops.cli.stack import stack_app
from container_host_aiops.cli.system import system_app
from container_host_aiops.cli.volume import volume_app

app = typer.Typer(
    name="container-host-aiops",
    help="Governed AI-ops for Docker + Portainer container hosts: container / "
    "image / volume / network / system reads, flagship analyses, and guarded "
    "lifecycle + prune writes with a built-in governance harness.",
    no_args_is_help=True,
)

app.add_typer(container_app, name="container")
app.add_typer(image_app, name="image")
app.add_typer(volume_app, name="volume")
app.add_typer(network_app, name="network")
app.add_typer(system_app, name="system")
app.add_typer(stack_app, name="stack")
app.add_typer(analyze_app, name="analyze")
app.add_typer(manage_app, name="manage")
app.add_typer(secret_app, name="secret")
app.command("init")(init_cmd)
app.command("overview")(overview_cmd)
app.command("doctor")(doctor_cmd)


@app.command("mcp")
@cli_errors
def mcp_cmd() -> None:
    """Start the MCP server (stdio transport).

    Single-command entry point for MCP clients (does not go through uvx/PyPI
    resolution at launch):
        container-host-aiops mcp
    """
    import sys

    if sys.version_info < (3, 11):
        typer.echo(
            f"ERROR: container-host-aiops requires Python >= 3.11 "
            f"(got {sys.version_info.major}.{sys.version_info.minor}).\n"
            f"Fix: uv python install 3.12 && "
            f"uv tool install --python 3.12 --force container-host-aiops",
            err=True,
        )
        raise typer.Exit(2)

    from mcp_server.server import main as _mcp_main

    _mcp_main()


if __name__ == "__main__":
    app()
