"""``endpoint-aiops overview`` — one-shot fleet health."""

from __future__ import annotations

import json

from endpoint_aiops.cli._common import TargetOption, cli_errors, console, get_connection


@cli_errors
def overview_cmd(target: TargetOption = None) -> None:
    """One-shot fleet health: online/offline, stale endpoints, version spread."""
    from endpoint_aiops.ops import inventory as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.fleet_overview(conn)))
