"""Endpoint remediation MCP tools (guarded writes).

The only state-changing tools in the package. Both are wrapped with the
governance harness (audit + risk tier). ``endpoint_assign_profile``
is reversible and records an undo descriptor (reassign the prior profile);
``endpoint_reboot`` has no safe inverse and records none.
"""

from typing import Any, Optional

from endpoint_aiops.governance import governed_tool
from endpoint_aiops.ops import remediation as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


def _preview(conn: Any, endpoint_id: str, resource: str) -> dict:
    """Resolve the write's path and read the endpoint's before-state.

    This is what makes a preview worth asking for. Both lookups are the same
    ones the real write performs, so a preview refuses on exactly the grounds
    the write would: ``path_for`` raises ``UnsupportedResource`` on a management
    server whose API has no such resource, and the endpoint read fails for an id
    that does not exist. A preview that skipped them could only ever say "here
    is what would happen" — including for a call about to be rejected.

    Reading also makes the preview *concrete*: it reports the endpoint's actual
    current profile / online state rather than a hand-written guess at it.
    """
    from endpoint_aiops.ops._util import _seg, dialect_of
    from endpoint_aiops.ops.inventory import get_endpoint

    path = dialect_of(conn).path_for(resource).format(id=_seg(endpoint_id))
    return {"path": path, "current": get_endpoint(conn, endpoint_id)}


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
    endpoint_id: str, profile_id: str, dry_run: bool = False, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=high] Assign a config profile to an endpoint (reversible).

    Captures the prior profile before switching, so the harness records an undo
    (reassign the prior profile) and a faithful audit trail. Pass dry_run=True
    to preview: it resolves the same path and reads the same before-state as the
    real call, so it reports the profile that would actually be replaced and
    refuses on the same grounds the write would.

    Args:
        endpoint_id: Endpoint id as returned by endpoint_list.
        profile_id: Config profile to assign.
        dry_run: If True, preview without assigning.
        target: Endpoint-management target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        seen = _preview(conn, endpoint_id, "profile")
        return {
            "dryRun": True,
            "wouldAssign": {
                "endpointId": endpoint_id,
                "profileId": profile_id,
                "path": seen["path"],
                "currentProfileId": seen["current"].get("profileId"),
            },
        }
    return ops.assign_profile(conn, endpoint_id, profile_id)


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def endpoint_reboot(
    endpoint_id: str, dry_run: bool = False, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=medium] Request an endpoint reboot (no safe inverse).

    Records the endpoint's prior online state for the audit trail; a reboot
    cannot be undone, so no undo descriptor is offered. Pass dry_run=True to
    preview — for an operation with no inverse, knowing whether the endpoint is
    even online (and how long since it was last seen) before committing is the
    whole value of asking first.

    Args:
        endpoint_id: Endpoint id as returned by endpoint_list.
        dry_run: If True, preview without rebooting.
        target: Endpoint-management target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        seen = _preview(conn, endpoint_id, "reboot")
        return {
            "dryRun": True,
            "wouldReboot": {
                "endpointId": endpoint_id,
                "path": seen["path"],
                "currentlyOnline": seen["current"].get("online"),
                "lastSeenHours": seen["current"].get("lastSeenHours"),
            },
        }
    return ops.reboot_endpoint(conn, endpoint_id)
