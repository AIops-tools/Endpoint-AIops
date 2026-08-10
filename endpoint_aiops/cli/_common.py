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
    """Exceptions translated to a one-line teaching error instead of a traceback.

    ``PolicyDenied`` belongs here even though it is not a ValueError: it is
    raised by ``@governed_tool``, which sits OUTSIDE ``@tool_errors``, so it is
    never flattened into an ``{"error": ...}`` dict — it would otherwise reach
    the CLI as an uncaught exception and exit 1 printing a traceback. Catching it
    here means a governed refusal surfaces as one red teaching line instead.
    """
    from endpoint_aiops.connection import EndpointApiError
    from endpoint_aiops.governance import PolicyDenied

    return (EndpointApiError, KeyError, OSError, ValueError, PolicyDenied)


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


def _teaching_message(message: str) -> str:
    """Undo ``str(KeyError)``'s repr quoting on an error flattened into a dict.

    ``tool_errors`` turns the exception into ``{"error": str(exc)}``, and
    ``str()`` of a ``KeyError`` — which is what ``UnsupportedResource`` is —
    wraps the message in repr quotes. :func:`cli_errors` already strips them on
    the exception path; the flattened-dict path has to do the same, or the one
    error in this tool that fully explains itself arrives wearing stray
    quotation marks.
    """
    if len(message) > 1 and message.startswith('"') and message.endswith('"'):
        return message[1:-1]
    return message


#: Exit status for a write whose outcome could not be determined. Kept distinct
#: from 0 (confirmed) and 1 (failed) on purpose: a write whose response was lost
#: is not a failure, but it is emphatically not a success either, and a script
#: must be able to tell all three apart.
EXIT_UNDETERMINED = 2


def checked(result: Any) -> Any:
    """Return ``result``, or abort when it reports a failed/undetermined write.

    Every CLI command that calls a governed twin MUST pass the result through
    here before printing its success line.

    Governed twins are wrapped in ``@tool_errors``, which flattens any exception
    into ``{"error": ...}`` and **returns** it. The CLI therefore never sees the
    exception, so a command that prints its result unconditionally reports a
    refused or failed operation exactly like a successful one — and exits 0, so
    a script cannot tell either. The dry-run path already refused with a
    non-zero status, which made the asymmetry worse: the preview was stricter
    than the real call.

    ``outcomeUnknown`` (set by the harness when a write's response is lost) is
    neither success nor failure — the change may still have landed. It gets its
    own line and :data:`EXIT_UNDETERMINED`, never a silent success.
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
        console.print(
            f"[yellow]Outcome undetermined: {result.get('note') or ''}[/]"
        )
        raise typer.Exit(EXIT_UNDETERMINED)
    if error:
        console.print(f"[red]Error: {error}[/]")
        hint = result.get("hint")
        if hint:
            console.print(f"[dim]{hint}[/]")
        raise typer.Exit(1)
    return result


def dry_run_preview(
    preview: Any, *, operation: str, api_call: str, parameters: dict | None = None
) -> None:
    """Render a GOVERNED dry-run result as the human-readable DRY-RUN banner.

    ``preview`` must come from calling the governed twin with ``dry_run=True``,
    so every guard that twin carries has already run against the real target
    and the same audit row lands as for a real call — the CLI silently not
    auditing previews was the outlier, since MCP previews have always been
    audited.

    A refusal arrives as ``{"error": ...}`` (``tool_errors`` flattens the
    exception into the dict) and is surfaced exactly like a refused real write:
    the teaching message in red, exit code 1. A green banner for a call the
    write is about to reject is the preview being *wrong*, not merely
    incomplete — and a caller that reads "here is what would happen" and then a
    refusal treats the refusal as transient and retries.

    Only the *serialization* stays CLI-shaped: the reader is a human, so the
    returned dict is rendered into the existing banner rather than dumped as
    JSON.

    Invariant: **a dry_run MAY read; it must never write.**
    """
    if isinstance(preview, dict) and preview.get("error"):
        console.print(f"[red]Error: {_teaching_message(str(preview['error']))}[/]")
        raise typer.Exit(1)
    dry_run_print(operation=operation, api_call=api_call, parameters=parameters)


def double_confirm(action: str, resource: str) -> None:
    """Require two confirmations for a destructive operation."""
    console.print(f"[bold yellow]⚠️  About to: {action} '{resource}'[/]")
    typer.confirm(f"Confirm 1/2: {action} '{resource}'?", abort=True)
    typer.confirm(
        f"Confirm 2/2: really {action} '{resource}'? This may be irreversible.",
        abort=True,
    )
