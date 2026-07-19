"""Patch / config drift MCP tools (read-only)."""

from typing import Any, Optional

from endpoint_aiops.governance import governed_tool
from endpoint_aiops.ops import drift as ops
from endpoint_aiops.ops import inventory as inv
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def drift_report(
    baseline: Optional[dict[str, Any]] = None,
    fields: Optional[list[str]] = None,
    endpoints: Optional[list[dict[str, Any]]] = None,
    target: Optional[str] = None,
    limit: int = 200,
) -> dict:
    """[READ] Report endpoints drifted from a per-field baseline (patch/agent/OS/profile).

    Answers "which endpoints have drifted from the fleet?" With no baseline it
    derives one by fleet majority (the most common value per field is treated as
    intended), so it works before any gold image is declared. Pass 'endpoints'
    for pure analysis, or a target to pull live inventory.

    Args:
        baseline: Field→intended-value map; omit to derive the fleet majority.
        fields: Inventory fields to check (default agentVersion, patchLevel,
            osBuild, profileId).
        endpoints: Injected inventory rows; skips live collection.
        target: Endpoint-management target name from config; omit for the default.
        limit: Max drifted endpoints to return (default 200).

    Returns dict: {totalEndpoints, baselineSource, baseline, fieldsChecked,
        driftedCount, compliantCount, driftByField, driftedEndpoints:{items[],
        returned, limit, truncated}}. driftedCount is the full count; when
        driftedEndpoints.truncated is true, re-run with a higher limit.

    Example: drift_report(endpoints=[{"hostname":"tc01","patchLevel":"2026-06"},
        {"hostname":"tc02","patchLevel":"2026-05"}]).
    """
    if endpoints is None:
        endpoints = inv.list_endpoints(_get_connection(target))
    return ops.config_drift(endpoints, baseline=baseline, fields=fields, limit=limit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def patch_status(
    target_patch: Optional[str] = None,
    endpoints: Optional[list[dict[str, Any]]] = None,
    target: Optional[str] = None,
    limit: int = 200,
) -> dict:
    """[READ] Patch-level distribution + which endpoints are behind the target level.

    Args:
        target_patch: Desired patch level; omit to use the fleet-majority level.
        endpoints: Injected inventory rows; skips live collection.
        target: Endpoint-management target name from config; omit for the default.
        limit: Max behind-endpoints to return (default 200).

    Returns dict: {totalEndpoints, targetPatch, targetSource, distribution,
        behindCount, behind:{items[], returned, limit, truncated}}. behindCount
        is the full count; when behind.truncated is true, re-run with a higher
        limit.
    """
    if endpoints is None:
        endpoints = inv.list_endpoints(_get_connection(target))
    return ops.patch_status(endpoints, target_patch=target_patch, limit=limit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def patch_compliance(
    endpoints: list[dict[str, Any]],
    target_patch: Optional[str] = None,
    sla_pct: float = 95.0,
    limit: int = 200,
) -> dict:
    """[READ] Patch-compliance SLA measure: % of the fleet on the target patch level.

    Reframes patch_status (the patch-level distribution) as an SLA/compliance
    verdict: what fraction of the fleet is on the target level, whether that meets
    the SLA, and which endpoints are non-compliant. Compliance is an exact string
    match on patchLevel — a transparent check, not a version-semantics parser.
    Injected-only: pass 'endpoints' (inventory rows); no live collection.

    Args:
        endpoints: Injected inventory rows to evaluate (e.g. from endpoint_list).
        target_patch: Desired patch level; omit to use the fleet-majority level.
        sla_pct: Compliance SLA threshold percent; default 95.0.
        limit: Max non-compliant endpoints to return (default 200).

    Returns dict: {endpointsEvaluated, targetPatch, targetSource, slaTargetPct,
        complianceRatePct, compliantCount, verdict, nonCompliantCount,
        nonCompliant:{items[], returned, limit, truncated}, note}. The rate is
        always computed over the whole fleet, never over the capped list.

    Example: patch_compliance(endpoints=[{"hostname":"tc01","patchLevel":"2026-06"},
        {"hostname":"tc02","patchLevel":"2026-05"}], target_patch="2026-06").
    """
    return ops.patch_compliance(
        endpoints, target_patch=target_patch, sla_pct=sla_pct, limit=limit
    )
