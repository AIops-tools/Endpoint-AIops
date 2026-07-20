"""Shared helpers for endpoint-aiops CLI sub-modules."""

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


def _cli_error_types() -> tuple[type[BaseException], ...]:
    """Exceptions translated to a one-line teaching error instead of a traceback."""
    from endpoint_aiops.connection import EndpointApiError

    return (EndpointApiError, KeyError, OSError, ValueError)


def cli_errors(fn: Callable) -> Callable:
    """Translate known exceptions into one red line + exit code 1."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (typer.Exit, typer.Abort):
            raise
        except _cli_error_types() as e:
            from endpoint_aiops.dialect import UnsupportedResource

            message = str(e)
            if isinstance(e, UnsupportedResource):
                # Already a complete teaching message; prefixing it with a
                # config-key headline sends the reader down the wrong path.
                message = message.strip('"')
            elif isinstance(e, KeyError):
                message = f"Missing required key or environment variable: {message}"
            console.print(f"[red]Error: {message}[/]")
            raise typer.Exit(1) from e

    return wrapper


def get_connection(target: str | None, config_path: Path | None = None) -> tuple[Any, Any]:
    """Return a (conn, config) tuple for the given target."""
    from endpoint_aiops.config import load_config
    from endpoint_aiops.connection import ConnectionManager

    cfg = load_config(config_path)
    mgr = ConnectionManager(cfg)
    return mgr.connect(target), cfg


LimitOption = Annotated[
    int, typer.Option("--limit", help="Max rows in each returned list")
]


def warn_if_truncated(result: dict, *keys: str) -> None:
    """Print a visible note for every truncation envelope that was capped.

    The JSON already carries ``truncated``; a human reading a long dump will
    miss it, so each capped list also says so in plain words, with the fix.
    """
    for key in keys:
        section = result.get(key)
        if isinstance(section, dict) and section.get("truncated"):
            console.print(
                f"[yellow]Note: '{key}' shows {section.get('returned')} of more "
                f"than {section.get('limit')} rows — truncated, re-run with a "
                f"higher --limit to see the rest.[/]"
            )


def dry_run_print(*, operation: str, api_call: str, parameters: dict | None = None) -> None:
    """Print a dry-run preview of the API call that would be made."""
    console.print("\n[bold magenta][DRY-RUN] No changes will be made.[/]")
    console.print(f"[magenta]  Operation: {operation}[/]")
    console.print(f"[magenta]  API Call:  {api_call}[/]")
    for k, v in (parameters or {}).items():
        console.print(f"[magenta]  Param:     {k} = {v}[/]")
    console.print("[magenta]  Run without --dry-run to execute.[/]\n")


def double_confirm(action: str, resource: str) -> None:
    """Require two confirmations for a destructive operation."""
    console.print(f"[bold yellow]⚠️  About to: {action} '{resource}'[/]")
    typer.confirm(f"Confirm 1/2: {action} '{resource}'?", abort=True)
    typer.confirm(
        f"Confirm 2/2: really {action} '{resource}'? This may be irreversible.",
        abort=True,
    )
