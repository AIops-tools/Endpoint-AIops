"""Environment and connectivity diagnostics for Endpoint AIops."""

from __future__ import annotations

from rich.console import Console

from endpoint_aiops.config import CONFIG_FILE, ENV_FILE, load_config
from endpoint_aiops.secretstore import SECRETS_FILE, check_permissions, has_store

_console = Console()


def run_doctor(skip_auth: bool = False) -> int:
    """Check config, secrets, and (optionally) connectivity.

    Returns a process exit code: 0 healthy, 1 problems found. Connectivity
    failures are reported as status, never raised as tracebacks (a doctor must
    survive the thing it diagnoses being unhealthy).
    """
    problems = 0

    if not CONFIG_FILE.exists():
        _console.print(f"[red]✗ Config file missing: {CONFIG_FILE}[/]")
        _console.print("[yellow]  Run 'endpoint-aiops init' to set up your first target.[/]")
        return 1
    _console.print(f"[green]✓ Config file present: {CONFIG_FILE}[/]")

    try:
        config = load_config()
    except Exception as exc:  # noqa: BLE001 — report, do not crash
        _console.print(f"[red]✗ Config load failed: {exc}[/]")
        return 1

    if not config.targets:
        _console.print("[red]✗ No targets configured[/]")
        return 1
    _console.print(f"[green]✓ {len(config.targets)} target(s) configured[/]")

    if has_store():
        _console.print(f"[green]✓ Encrypted secret store present: {SECRETS_FILE}[/]")
        perm_warning = check_permissions()
        if perm_warning:
            _console.print(f"[yellow]! {perm_warning}[/]")
    elif ENV_FILE.exists():
        _console.print(
            f"[yellow]! Using legacy plaintext .env ({ENV_FILE}). Migrate with "
            f"'endpoint-aiops secret migrate'.[/]"
        )
    else:
        _console.print(
            "[yellow]! No secret store yet. Run 'endpoint-aiops init' to set up "
            "credentials (stored encrypted).[/]"
        )
        problems += 1

    for target in config.targets:
        try:
            _ = target.api_key
            _console.print(f"[green]✓ API key present for '{target.name}'[/]")
        except OSError as exc:
            _console.print(f"[red]✗ {exc}[/]")
            problems += 1

    if skip_auth:
        _console.print("[dim]Skipping connectivity check (--skip-auth).[/]")
        return 1 if problems else 0

    from endpoint_aiops.connection import ConnectionManager

    mgr = ConnectionManager(config)
    for target in config.targets:
        problems += _check_target(mgr, target)

    return 1 if problems else 0


def _check_target(mgr: object, target: object) -> int:
    """Reachability, then authentication, then an authenticated read.

    Deliberately three steps, not one. They fail for unrelated reasons and a
    single green "connected" line hides which one actually passed — on IGEL UMS
    the version path is the one *unauthenticated* endpoint, so a combined check
    would print a reassuring tick having never presented a credential.
    """
    from endpoint_aiops.auth import AuthSchemeError
    from endpoint_aiops.connection import EndpointApiError

    name = getattr(target, "name", "?")
    try:
        conn = mgr.connect(name)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 — a bad dialect/auth config is a status
        _console.print(f"[red]✗ '{name}': could not build a connection: {exc}[/]")
        return 1

    dialect = conn.target.dialect_obj
    scheme = conn.auth_strategy
    _console.print(
        f"[dim]  '{name}': dialect '{dialect.name}', authenticating with {scheme.label}.[/]"
    )

    # 1 — reachability, without logging in.
    try:
        info = conn.probe(dialect.path_for("version"))
        version = info.get("version", "?") if isinstance(info, dict) else "?"
        _console.print(
            f"[green]✓ Reached '{name}' ({target.host}) — management server {version}[/]"
        )
    except Exception as exc:  # noqa: BLE001 — connectivity is a status, not a crash
        _console.print(f"[red]✗ Reach '{name}' ({target.host}) failed: {exc}[/]")
        return 1

    # 2 — authentication, named precisely so a wrong scheme never reads as a
    #     wrong password. Those have different fixes.
    try:
        conn.authenticate()
    except AuthSchemeError as exc:
        _console.print(f"[red]✗ '{name}': auth scheme not usable as configured: {exc}[/]")
        return 1
    except EndpointApiError as exc:
        _console.print(f"[red]✗ '{name}': {_auth_diagnosis(exc, scheme)}[/]")
        return 1
    except Exception as exc:  # noqa: BLE001 — auth failure is a status, not a crash
        _console.print(f"[red]✗ '{name}': login failed: {exc}[/]")
        return 1

    # 3 — an authenticated read. Step 2 can be a no-op for a static-token
    #     scheme, so this is the first call that actually presents credentials.
    try:
        rows = conn.get(dialect.path_for("endpoints"))
    except EndpointApiError as exc:
        _console.print(f"[red]✗ '{name}': {_auth_diagnosis(exc, scheme)}[/]")
        return 1
    except Exception as exc:  # noqa: BLE001 — status, not a crash
        _console.print(f"[red]✗ '{name}': authenticated read failed: {exc}[/]")
        return 1

    _console.print(f"[green]✓ Authenticated to '{name}' with {scheme.label}[/]")
    if _is_empty_collection(rows):
        _console.print(
            f"[yellow]! '{name}' authenticated but returned no endpoints. That is not "
            f"proof the fleet is empty: on IGEL UMS an account without at least "
            f"Read/Browse at the Devices level gets an empty list rather than a 403. "
            f"Confirm the count in the management console before trusting it.[/]"
        )
    return 0


def _is_empty_collection(rows: object) -> bool:
    """True when a list read came back with nothing in it (envelope or bare)."""
    if isinstance(rows, list):
        return not rows
    if isinstance(rows, dict):
        for value in rows.values():
            if isinstance(value, list):
                return not value
    return False


def _auth_diagnosis(exc: object, scheme: object) -> str:
    """One line naming the scheme used and, when known, the one wanted."""
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        challenge = (getattr(exc, "challenge", "") or "").strip()
        wanted = (
            f" the server asked for '{challenge}'"
            if challenge
            else " the server did not say which scheme it wants"
        )
        return (
            f"authentication rejected ({status}). This target presented "
            f"{getattr(scheme, 'label', '?')};{wanted}. If those disagree, the dialect is "
            f"wrong rather than the credentials — check 'dialect:' before rotating keys."
        )
    return f"authenticated read failed: {exc}"
