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

from endpoint_aiops.cli._common import cli_errors, console
from endpoint_aiops.config import CONFIG_DIR, CONFIG_FILE
from endpoint_aiops.dialect import PRESETS
from endpoint_aiops.governance.paths import ops_path
from endpoint_aiops.secretstore import SecretStore, resolve_master_password

# Starter policy: keeps the secure-by-default gate (high/critical writes need a
# named approver) explicit and editable, and shows the other rule kinds.
DEFAULT_RULES_YAML = """\
# endpoint-aiops policy rules — hot-reloaded on change (no restart needed).
# Kinds: deny rules, maintenance_window, risk_tiers (graduated autonomy).

risk_tiers:
  - name: high-risk-requires-approver
    tier: dual
    min_risk_level: high
    reason: >-
      High/critical writes need a named human approver — set
      ENDPOINT_AUDIT_APPROVED_BY (and ENDPOINT_AUDIT_RATIONALE) before the call.

# deny:
#   - name: no-prod-reboots
#     operations: ["endpoint_reboot"]
#     environments: ["production"]
#     reason: "Endpoint reboots in production go through change management."

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
                    f"{preset.default_api_path} on port {preset.default_port} "
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

    _write_default_rules()
    console.print(f"\n[green]✓ Setup complete.[/] Config: {CONFIG_FILE}")
    console.print(
        "[dim]Tip: export ENDPOINT_AIOPS_MASTER_PASSWORD=... in your shell profile "
        "so the MCP server and CLI can unlock secrets non-interactively.[/]"
    )
    if typer.confirm("Run a connectivity check now (endpoint-aiops doctor)?", default=True):
        from endpoint_aiops.doctor import run_doctor

        raise typer.Exit(run_doctor())
