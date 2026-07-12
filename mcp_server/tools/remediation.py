"""Endpoint remediation MCP tools (guarded writes).

The only state-changing tools in the package. Both are wrapped with the
governance harness (audit + graduated approval tier). ``endpoint_assign_profile``
is reversible and records an undo descriptor (reassign the prior profile);
``endpoint_reboot`` has no safe inverse and records none.
"""

from typing import Any, Optional

from endpoint_aiops.governance import governed_tool
from endpoint_aiops.ops import remediation as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


def _assign_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    """Inverse of assign_profile: reassign the profile captured before the change."""
    if not isinstance(result, dict):
        return None
    prior = (result.get("priorState") or {}).get("profileId")
    if not prior:
        return None  # no prior profile → no safe inverse
    return {
        "tool": "endpoint_assign_profile",
        "params": {"endpoint_id": params.get("endpoint_id"), "profile_id": prior},
        "note": "Reassign the profile that was active before this change.",
    }


@mcp.tool()
@governed_tool(risk_level="high", undo=_assign_undo)
@tool_errors("dict")
def endpoint_assign_profile(
    endpoint_id: str, profile_id: str, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=high] Assign a config profile to an endpoint (reversible).

    Captures the prior profile before switching, so the harness records an undo
    (reassign the prior profile) and a faithful audit trail.

    Args:
        endpoint_id: Endpoint id as returned by endpoint_list.
        profile_id: Config profile to assign.
        target: Endpoint-management target name from config; omit for the default.
    """
    return ops.assign_profile(_get_connection(target), endpoint_id, profile_id)


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def endpoint_reboot(endpoint_id: str, target: Optional[str] = None) -> dict:
    """[WRITE][risk=medium] Request an endpoint reboot (no safe inverse).

    Records the endpoint's prior online state for the audit trail; a reboot
    cannot be undone, so no undo descriptor is offered.

    Args:
        endpoint_id: Endpoint id as returned by endpoint_list.
        target: Endpoint-management target name from config; omit for the default.
    """
    return ops.reboot_endpoint(_get_connection(target), endpoint_id)
