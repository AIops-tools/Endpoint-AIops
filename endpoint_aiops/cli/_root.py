"""Top-level Typer app: assembles sub-apps and top-level commands."""

from __future__ import annotations

import typer

from endpoint_aiops.cli._common import cli_errors
from endpoint_aiops.cli.doctor import doctor_cmd
from endpoint_aiops.cli.drift import drift_app
from endpoint_aiops.cli.endpoint import endpoint_app
from endpoint_aiops.cli.init import init_cmd
from endpoint_aiops.cli.overview import overview_cmd
from endpoint_aiops.cli.secret import secret_app
from endpoint_aiops.cli.session import session_app
from endpoint_aiops.cli.undo import undo_app

app = typer.Typer(
    name="endpoint-aiops",
    help="Governed AI-ops for managed-endpoint fleets (thin clients / VDI).",
    no_args_is_help=True,
)

app.add_typer(endpoint_app, name="endpoint")
app.add_typer(session_app, name="session")
app.add_typer(drift_app, name="drift")
app.add_typer(secret_app, name="secret")
app.add_typer(undo_app, name="undo")
app.command("init")(init_cmd)
app.command("overview")(overview_cmd)
app.command("doctor")(doctor_cmd)


@app.command("mcp")
@cli_errors
def mcp_cmd() -> None:
    """Start the MCP server (stdio transport).

    Single-command entry point for MCP clients (does not go through uvx/PyPI
    resolution at launch):
        endpoint-aiops mcp
    """
    import sys

    if sys.version_info < (3, 11):
        typer.echo(
            f"ERROR: endpoint-aiops requires Python >= 3.11 "
            f"(got {sys.version_info.major}.{sys.version_info.minor}).\n"
            f"Fix: uv python install 3.12 && "
            f"uv tool install --python 3.12 --force endpoint-aiops",
            err=True,
        )
        raise typer.Exit(2)

    from mcp_server.server import main as _mcp_main

    _mcp_main()


if __name__ == "__main__":
    app()
