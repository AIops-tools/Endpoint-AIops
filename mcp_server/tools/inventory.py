"""Managed-endpoint inventory MCP tools (read-only)."""

from typing import Optional

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
