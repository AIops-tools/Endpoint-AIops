"""Managed-endpoint inventory MCP tools (read-only)."""

from typing import Any, Optional

from endpoint_aiops.governance import governed_tool
from endpoint_aiops.ops import inventory as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def overview(target: Optional[str] = None) -> dict:
    """[READ] One-shot fleet health: online/offline, stale endpoints, version spread.

    Call this first to triage a managed-endpoint fleet before drilling into a
    specific endpoint, login storm, or drift report.

    Args:
        target: Endpoint-management target name from config; omit for the default.
    """
    return ops.fleet_overview(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def endpoint_list(target: Optional[str] = None) -> list:
    """[READ] List all managed endpoints (id, hostname, OS, agent/patch, online).

    Args:
        target: Endpoint-management target name from config; omit for the default.
    """
    return ops.list_endpoints(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def endpoint_get(endpoint_id: str, target: Optional[str] = None) -> dict:
    """[READ] One managed endpoint by id, normalised to the stable shape.

    Args:
        endpoint_id: Endpoint id (or uuid/mac) as returned by endpoint_list.
        target: Endpoint-management target name from config; omit for the default.
    """
    return ops.get_endpoint(_get_connection(target), endpoint_id)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def endpoint_health_score(
    endpoints: list[dict[str, Any]],
    stale_hours: float = 24.0,
    baseline: Optional[dict[str, Any]] = None,
) -> dict:
    """[READ] Composite per-endpoint health score (0-100), worst endpoints first.

    Answers "which endpoints are worst?" by folding the fleet signals into one
    ranked view: it deducts points for each risk signal (offline, stale,
    patch-behind, agent-behind) and cites every deduction in the endpoint's
    'reasons'. Pure analysis over injected inventory rows (the shape from
    endpoint_list) — no live connection is used. With no baseline, the patch and
    agent baselines are derived by fleet majority, so it works before a gold
    image is declared.

    Args:
        endpoints: Injected inventory rows (id, hostname, online, lastSeenHours,
            agentVersion, patchLevel) to score. Required — no live pull.
        stale_hours: An endpoint whose lastSeenHours >= this is 'stale' (default 24).
        baseline: Intended {'agentVersion', 'patchLevel'}; omit to derive the
            fleet majority.

    Returns dict: {endpointsEvaluated, baseline:{agentVersion, patchLevel,
        source}, summary:{healthy, degraded, critical}, worst:[{endpoint, score,
        band, reasons[]} ...worst-first], note}.

    Example: endpoint_health_score(endpoints=[
        {"hostname":"tc01","online":True,"agentVersion":"12.6","patchLevel":"2026-06"},
        {"hostname":"tc02","online":False,"agentVersion":"12.5","patchLevel":"2026-05"}]).
    """
    return ops.endpoint_health_score(endpoints, stale_hours=stale_hours, baseline=baseline)
