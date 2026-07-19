"""``endpoint-aiops session`` — login/boot sessions + login-storm analysis."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from endpoint_aiops.cli._common import (
    LimitOption,
    TargetOption,
    cli_errors,
    console,
    get_connection,
    warn_if_truncated,
)

session_app = typer.Typer(
    name="session",
    help="Login/boot sessions: list recent, analyse login storms.",
    no_args_is_help=True,
)

SinceOption = Annotated[
    int, typer.Option("--since-hours", help="Look-back window in hours (1..720)")
]


@session_app.command("list")
@cli_errors
def session_list(since_hours: SinceOption = 24, target: TargetOption = None) -> None:
    """List recent login/boot sessions."""
    from endpoint_aiops.ops import sessions as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.list_sessions(conn, since_hours=since_hours)))


@session_app.command("storm")
@cli_errors
def session_storm(
    since_hours: SinceOption = 24,
    window_s: Annotated[float, typer.Option(help="Sliding window (s) for concurrency")] = 300.0,
    min_concurrent: Annotated[int, typer.Option(help="Logins/window that = a storm")] = 10,
    target: TargetOption = None,
    limit: LimitOption = 25,
) -> None:
    """Detect login storms and rank the slowest login/boot contributors."""
    from endpoint_aiops.ops import sessions as ops

    conn, _ = get_connection(target)
    rows = ops.list_sessions(conn, since_hours=since_hours)
    result = ops.login_storm(
        rows, window_s=window_s, min_concurrent=min_concurrent, limit=limit
    )
    console.print_json(json.dumps(result))
    warn_if_truncated(result, "storms", "slowestByLogin", "slowestByBoot")
