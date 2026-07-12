"""``endpoint-aiops endpoint`` — inventory reads + guarded remediation writes."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from endpoint_aiops.cli._common import (
    DryRunOption,
    TargetOption,
    cli_errors,
    console,
    double_confirm,
    dry_run_print,
    get_connection,
)

endpoint_app = typer.Typer(
    name="endpoint",
    help="Managed endpoints: list/get, assign a profile, reboot.",
    no_args_is_help=True,
)

IdArg = Annotated[str, typer.Argument(help="Endpoint id (from 'endpoint list')")]


@endpoint_app.command("list")
@cli_errors
def endpoint_list(target: TargetOption = None) -> None:
    """List all managed endpoints."""
    from endpoint_aiops.ops import inventory as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.list_endpoints(conn)))


@endpoint_app.command("get")
@cli_errors
def endpoint_get(endpoint_id: IdArg, target: TargetOption = None) -> None:
    """Show one managed endpoint by id."""
    from endpoint_aiops.ops import inventory as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.get_endpoint(conn, endpoint_id)))


@endpoint_app.command("assign-profile")
@cli_errors
def endpoint_assign_profile(
    endpoint_id: IdArg,
    profile_id: Annotated[str, typer.Argument(help="Config profile id to assign")],
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Assign a config profile to an endpoint (reversible; dry-run + confirm)."""
    from endpoint_aiops.ops import remediation as ops

    if dry_run:
        dry_run_print(
            operation="assign_profile",
            api_call=f"POST /endpoints/{endpoint_id}/profile",
            parameters={"profile_id": profile_id},
        )
        return
    double_confirm(f"assign profile '{profile_id}' to", endpoint_id)
    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.assign_profile(conn, endpoint_id, profile_id)))


@endpoint_app.command("reboot")
@cli_errors
def endpoint_reboot(
    endpoint_id: IdArg,
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Request an endpoint reboot (no undo; dry-run + confirm)."""
    from endpoint_aiops.ops import remediation as ops

    if dry_run:
        dry_run_print(
            operation="reboot_endpoint",
            api_call=f"POST /endpoints/{endpoint_id}/reboot",
        )
        return
    double_confirm("reboot", endpoint_id)
    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.reboot_endpoint(conn, endpoint_id)))
