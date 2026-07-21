"""``endpoint-aiops init`` — a friendly, interactive onboarding wizard.

Walks a new user through connecting their first endpoint-management target:
collects the non-secret connection details into ``config.yaml`` and the API key
into the *encrypted* store (never plaintext on disk). Designed to be run on a
terminal; everything it needs is prompted with sensible defaults.
"""

from __future__ import annotations

import getpass

import typer
import yaml

from endpoint_aiops.auth import for_dialect
from endpoint_aiops.cli._common import cli_errors, console
from endpoint_aiops.config import CONFIG_DIR, CONFIG_FILE
from endpoint_aiops.dialect import PRESETS
from endpoint_aiops.secretstore import SecretStore, resolve_master_password


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
    """Interactively set up your first Endpoint connection."""
    console.print("[bold cyan]Endpoint AIops — setup wizard[/]")
    console.print(
        "This collects connection details (saved to config.yaml) and your "
        "Endpoint API key (saved [bold]encrypted[/] to secrets.enc).\n"
    )

    console.print("[bold]Step 1 — master password[/]")
    console.print(
        "[dim]Encrypts secrets.enc. You'll set it via the "
        "ENDPOINT_AIOPS_MASTER_PASSWORD env var for non-interactive/MCP use.[/]"
    )
    password = resolve_master_password(confirm_if_new=True)
    store = SecretStore.unlock(password)

    targets = _load_existing_targets()
    existing_names = {t.get("name") for t in targets}

    while True:
        console.print("\n[bold]Step 2 — add a target[/]")
        name = typer.prompt("Target name (e.g. nas1)").strip()
        if name in existing_names:
            if not typer.confirm(f"'{name}' already exists — overwrite?", default=False):
                continue
            targets = [t for t in targets if t.get("name") != name]

        host = typer.prompt("Host (IP or FQDN of the Endpoint server)").strip()

        # The dialect decides the port and API base path, so it is asked FIRST.
        # Leaving it unstated used to silently configure the generic placeholder
        # shape (/api/v2.0 on 443), which no real management server serves.
        console.print(
            "\n[dim]Which management server is this? The dialect sets the API "
            "paths, port and base path.[/]"
        )
        for key, preset in sorted(PRESETS.items()):
            note = ("neutral placeholder — you must describe your server's paths "
                    "yourself in config.yaml"
                    if key == "generic" else
                    f"{preset.default_api_path} on port {preset.default_port}, "
                    f"{for_dialect(preset).label} "
                    f"(modelled from vendor docs, NOT live-verified)")
            console.print(f"  [bold]{key}[/] — {note}")
        dialect = typer.prompt("Dialect", default="generic").strip()
        while dialect not in PRESETS:
            console.print(f"[red]Unknown dialect '{dialect}'.[/]")
            dialect = typer.prompt(
                f"Dialect ({', '.join(sorted(PRESETS))})", default="generic"
            ).strip()
        chosen = PRESETS[dialect]
        if dialect == "generic":
            console.print(
                "[yellow]![/] The generic dialect is a placeholder, not a real "
                "vendor API. Until you add a dialect: block describing your "
                "server's paths, calls will 404."
            )

        scheme = typer.prompt("Scheme (https or http)", default="https").strip()
        while scheme not in ("https", "http"):
            scheme = typer.prompt("Scheme must be 'https' or 'http'", default="https").strip()
        port = typer.prompt("Port", default=chosen.default_port, type=int)
        console.print("[dim]Lab / self-signed certificate setups can answer No here.[/]")
        verify_ssl = typer.confirm(
            "Verify TLS certificate? (No for self-signed lab certs)", default=True
        )

        # The dialect also decides HOW to authenticate, so the credential prompt
        # follows it. Asking for an "API key" on a dialect that logs in with a
        # username and password collects the wrong thing and fails at the first
        # call with a 401 that looks like a bad key.
        username = ""
        if for_dialect(chosen).name == "imi-session":
            console.print(
                "[dim]This dialect logs in with a UMS administrator account "
                "(HTTP Basic), not an API key. The account needs at least "
                "Read/Browse permission at the Devices level — with fewer "
                "permissions the server returns empty lists instead of an error.[/]"
            )
            username = typer.prompt("UMS administrator username").strip()
            secret = getpass.getpass(f"Password for '{username}' (hidden): ")
        else:
            console.print(
                "[dim]Create an API key in the Endpoint UI: Credentials → API Keys. "
                "Paste it below (input hidden).[/]"
            )
            secret = getpass.getpass(f"API key for '{name}' (hidden): ")
        store = store.set(name, secret)

        entry = {
            "name": name,
            "host": host,
            "port": port,
            "scheme": scheme,
            "verify_ssl": verify_ssl,
            "api_path": chosen.default_api_path,
            "dialect": dialect,
        }
        if username:
            entry["username"] = username
        targets.append(entry)
        existing_names.add(name)
        _write_targets(targets)
        console.print(
            f"[green]✓ Saved target '{name}'[/] — dialect [bold]{dialect}[/], "
            f"{scheme}://{host}:{port}{chosen.default_api_path} "
            f"(API key stored encrypted)."
        )

        if not typer.confirm("\nAdd another target?", default=False):
            break

    console.print(f"\n[green]✓ Setup complete.[/] Config: {CONFIG_FILE}")
    console.print(
        "[dim]Tip: export ENDPOINT_AIOPS_MASTER_PASSWORD=... in your shell profile "
        "so the MCP server and CLI can unlock secrets non-interactively.[/]"
    )
    if typer.confirm("Run a connectivity check now (endpoint-aiops doctor)?", default=True):
        from endpoint_aiops.doctor import run_doctor

        raise typer.Exit(run_doctor())
