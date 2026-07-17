"""``container-host-aiops init`` — a friendly, interactive onboarding wizard.

Walks a new user through connecting their first container host: collects the
non-secret connection details into ``config.yaml`` and — for a Portainer target —
the API token into the *encrypted* store (never plaintext on disk). A direct
Docker or Podman socket target needs no secret. Designed to be run on a terminal;
everything it needs is prompted with sensible defaults.
"""

from __future__ import annotations

import getpass

import typer
import yaml

from container_host_aiops.cli._common import cli_errors, console
from container_host_aiops.config import CONFIG_DIR, CONFIG_FILE
from container_host_aiops.governance.paths import ops_path
from container_host_aiops.platform import (
    DEFAULT_DOCKER_SOCKET,
    DEFAULT_PORTAINER_PORT,
    DOCKER,
    PODMAN,
    PORTAINER,
    default_podman_socket,
)
from container_host_aiops.secretstore import SecretStore, resolve_master_password

# Starter policy: keeps the secure-by-default gate (high/critical writes need a
# named approver) explicit and editable, and shows the other rule kinds.
DEFAULT_RULES_YAML = """\
# container-host-aiops policy rules — hot-reloaded on change (no restart needed).
# Kinds: deny rules, maintenance_window, risk_tiers (graduated autonomy).

risk_tiers:
  - name: high-risk-requires-approver
    tier: dual
    min_risk_level: high
    reason: >-
      High/critical writes need a named human approver — set
      CONTAINER_HOST_AUDIT_APPROVED_BY (and CONTAINER_HOST_AUDIT_RATIONALE)
      before the call.

# deny:
#   - name: no-prod-removes
#     operations: ["remove_*", "prune_*"]
#     environments: ["production"]
#     reason: "Container removes/prunes in production go through change management."

# maintenance_window:
#   start: "22:00"
#   end: "06:00"
"""


def _write_default_rules() -> None:
    """Seed a starter rules.yaml (only when none exists) so the policy layer
    is explicit from day one; never overwrites an operator-authored file."""
    rules_path = ops_path("rules.yaml")
    if rules_path.exists():
        return
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(DEFAULT_RULES_YAML, "utf-8")
    console.print(f"[green]✓ Wrote default policy rules:[/] {rules_path}")


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
        "This collects Docker, Portainer, or Podman connection details (saved to "
        "config.yaml). A Portainer target also stores its API token "
        "[bold]encrypted[/] in secrets.enc; a local Docker/Podman socket needs no "
        "secret.\n"
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
            f"Platform ({DOCKER} / {PORTAINER} / {PODMAN})", default=DOCKER
        ).strip().lower()
        if platform not in (DOCKER, PORTAINER, PODMAN):
            console.print("[red]Platform must be 'docker', 'portainer', or 'podman'.[/]")
            continue

        entry: dict = {"name": name, "platform": platform}
        if platform in (DOCKER, PODMAN):
            engine = "Docker" if platform == DOCKER else "Podman"
            use_socket = typer.confirm(
                "Connect over a local unix socket? (No = TCP host)", default=True
            )
            if use_socket:
                default_socket = (
                    DEFAULT_DOCKER_SOCKET if platform == DOCKER else default_podman_socket()
                )
                entry["socket_path"] = typer.prompt(
                    f"{engine} socket path", default=default_socket
                ).strip()
            else:
                entry["host"] = typer.prompt(f"{engine} host (IP or FQDN)").strip()
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
            console.print("[dim]Lab/self-signed setups can answer No here.[/]")
            entry["verify_ssl"] = typer.confirm(
                "Verify TLS certificate? (No for self-signed)", default=True
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

    _write_default_rules()
    console.print(f"\n[green]✓ Setup complete.[/] Config: {CONFIG_FILE}")
    console.print(
        "[dim]Tip: export CONTAINER_HOST_AIOPS_MASTER_PASSWORD=... in your shell "
        "profile so the MCP server and CLI can unlock Portainer tokens "
        "non-interactively.[/]"
    )
    if typer.confirm("Run a connectivity check now (container-host-aiops doctor)?", default=True):
        from container_host_aiops.doctor import run_doctor

        raise typer.Exit(run_doctor())
