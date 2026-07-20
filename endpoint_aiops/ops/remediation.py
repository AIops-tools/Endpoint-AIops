"""Endpoint remediation writes (guarded).

Two state-changing operations, each of which captures the endpoint's state
*before* the change so the harness can record a faithful undo / audit trail
(the before-state is read, never guessed):

  * ``assign_profile`` — reassign an endpoint's config profile. Reversible: the
    prior profile id is captured, so the inverse is "assign the prior profile".
  * ``reboot_endpoint`` — request a reboot. Has no safe inverse (you cannot
    un-reboot), so it records the prior online state for the audit trail but
    offers no undo descriptor.

These are the only writes in the tool; both are gated at the MCP layer by the
governance harness (risk tier + audit) and at the CLI layer by dry-run +
double-confirm.
"""

from __future__ import annotations

from typing import Any

from endpoint_aiops.ops._util import _seg, dialect_of
from endpoint_aiops.ops.inventory import get_endpoint


def assign_profile(conn: Any, endpoint_id: str, profile_id: str) -> dict:
    """[WRITE] Assign a config profile to an endpoint, capturing the prior one.

    Reads the endpoint first so the response carries ``priorState.profileId``
    (drives undo + audit); then POSTs the reassignment.
    """
    prior = get_endpoint(conn, endpoint_id)
    conn.post(
        dialect_of(conn).path_for("profile").format(id=_seg(endpoint_id)),
        json={"profile_id": profile_id},
    )
    return {
        "action": "assign_profile",
        "endpointId": endpoint_id,
        "profileId": profile_id,
        "priorState": {"profileId": prior.get("profileId")},
    }


def reboot_endpoint(conn: Any, endpoint_id: str) -> dict:
    """[WRITE] Request an endpoint reboot, capturing its prior online state.

    No safe inverse exists for a reboot, so this records the before-state for
    audit but the tool intentionally offers no undo descriptor.
    """
    prior = get_endpoint(conn, endpoint_id)
    conn.post(dialect_of(conn).path_for("reboot").format(id=_seg(endpoint_id)))
    return {
        "action": "reboot_endpoint",
        "endpointId": endpoint_id,
        "priorState": {
            "online": prior.get("online"),
            "lastSeenHours": prior.get("lastSeenHours"),
        },
    }
