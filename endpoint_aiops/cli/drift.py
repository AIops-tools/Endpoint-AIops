"""``endpoint-aiops drift`` — patch/config drift + patch-level status."""

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

drift_app = typer.Typer(
    name="drift",
    help="Fleet drift: config/patch deviation vs a baseline, patch-level status.",
    no_args_is_help=True,
)


@drift_app.command("report")
@cli_errors
def drift_report(target: TargetOption = None, limit: LimitOption = 200) -> None:
    """Report endpoints drifted from the fleet-majority baseline."""
    from endpoint_aiops.ops import drift as ops
    from endpoint_aiops.ops import inventory as inv

    conn, _ = get_connection(target)
    result = ops.config_drift(inv.list_endpoints(conn), limit=limit)
    console.print_json(json.dumps(result))
    warn_if_truncated(result, "driftedEndpoints")


@drift_app.command("patch")
@cli_errors
def drift_patch(
    target_patch: Annotated[
        str | None, typer.Option("--target-patch", help="Desired patch level")
    ] = None,
    target: TargetOption = None,
    limit: LimitOption = 200,
) -> None:
    """Patch-level distribution + which endpoints are behind the target."""
    from endpoint_aiops.ops import drift as ops
    from endpoint_aiops.ops import inventory as inv

    conn, _ = get_connection(target)
    result = ops.patch_status(
        inv.list_endpoints(conn), target_patch=target_patch, limit=limit
    )
    console.print_json(json.dumps(result))
    warn_if_truncated(result, "behind")
