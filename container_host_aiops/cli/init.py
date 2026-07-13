"""``container-host-aiops init`` — a friendly, interactive onboarding wizard.

Walks a new user through connecting their first container host: collects the
non-secret connection details into ``config.yaml`` and — for a Portainer target —
the API token into the *encrypted* store (never plaintext on disk). A direct
Docker socket target needs no secret. Designed to be run on a terminal;
everything it needs is prompted with sensible defaults.
"""

from __future__ import annotations

import getpass

import typer
import yaml

from container_host_aiops.cli._common import cli_errors, console
from container_host_aiops.config import CONFIG_DIR, CONFIG_FILE
from container_host_aiops.platform import (
    DEFAULT_DOCKER_SOCKET,
    DEFAULT_PORTAINER_PORT,
    DOCKER,
    PORTAINER,
)
from container_host_aiops.secretstore import SecretStore, resolve_master_password


def _load_existing_targets() -> list[dict]:
    if not CONFIG_FILE.exists():
        return []
    raw = yaml.safe_load(CONFIG_FILE.read_text("utf-8")) or {}
    return list(raw.get("targets", []))


def _write_targets(targets: list[dict]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_DIR.chmod(0o700)
    except OSError:
        pass
    CONFIG_FILE.write_text(yaml.safe_dump({"targets": targets}, sort_keys=False), "utf-8")


@cli_errors
def init_cmd() -> None:
    """Interactively set up your first Docker or Portainer connection."""
    console.print("[bold cyan]Container Host AIops — setup wizard[/]")
    console.print(
        "This collects Docker or Portainer connection details (saved to "
        "config.yaml). A Portainer target also stores its API token "
        "[bold]encrypted[/] in secrets.enc; a local Docker socket needs no secret.\n"
    )

    targets = _load_existing_targets()
    existing_names = {t.get("name") for t in targets}
    store: SecretStore | None = None

    while True:
        console.print("\n[bold]Add a target[/]")
        name = typer.prompt("Target name (e.g. prod1)").strip()
        if name in existing_names:
            if not typer.confirm(f"'{name}' already exists — overwrite?", default=False):
                continue
            targets = [t for t in targets if t.get("name") != name]

        platform = typer.prompt(
            f"Platform ({DOCKER} / {PORTAINER})", default=DOCKER
        ).strip().lower()
        if platform not in (DOCKER, PORTAINER):
            console.print("[red]Platform must be 'docker' or 'portainer'.[/]")
            continue

        entry: dict = {"name": name, "platform": platform}
        if platform == DOCKER:
            use_socket = typer.confirm(
                "Connect over a local unix socket? (No = TCP host)", default=True
            )
            if use_socket:
                entry["socket_path"] = typer.prompt(
                    "Docker socket path", default=DEFAULT_DOCKER_SOCKET
                ).strip()
            else:
                entry["host"] = typer.prompt("Docker host (IP or FQDN)").strip()
                entry["verify_ssl"] = typer.confirm(
                    "Use TLS (https)?", default=False
                )
        else:  # portainer
            entry["host"] = typer.prompt("Portainer host (IP or FQDN)").strip()
            entry["port"] = typer.prompt(
                "Portainer HTTPS port", default=DEFAULT_PORTAINER_PORT, type=int
            )
            entry["endpoint_id"] = typer.prompt(
                "Managed Docker endpoint id (for proxied Docker reads)", default="1"
            ).strip()
            entry["verify_ssl"] = typer.confirm(
                "Verify TLS certificate? (No for self-signed)", default=False
            )
            if store is None:
                console.print("\n[bold]Master password[/] (encrypts secrets.enc)")
                console.print(
                    "[dim]Set it later via CONTAINER_HOST_AIOPS_MASTER_PASSWORD for "
                    "non-interactive/MCP use.[/]"
                )
                password = resolve_master_password(confirm_if_new=True)
                store = SecretStore.unlock(password)
            token = getpass.getpass(f"Portainer API token for '{name}' (hidden): ")
            store = store.set(name, token)

        targets.append(entry)
        existing_names.add(name)
        _write_targets(targets)
        console.print(f"[green]✓ Saved target '{name}' ({platform}).[/]")

        if not typer.confirm("\nAdd another target?", default=False):
            break

    console.print(f"\n[green]✓ Setup complete.[/] Config: {CONFIG_FILE}")
    console.print(
        "[dim]Tip: export CONTAINER_HOST_AIOPS_MASTER_PASSWORD=... in your shell "
        "profile so the MCP server and CLI can unlock Portainer tokens "
        "non-interactively.[/]"
    )
    if typer.confirm("Run a connectivity check now (container-host-aiops doctor)?", default=True):
        from container_host_aiops.doctor import run_doctor

        raise typer.Exit(run_doctor())
