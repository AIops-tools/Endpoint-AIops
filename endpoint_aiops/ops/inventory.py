"""Managed-endpoint inventory and fleet health (read-only).

Reads the endpoint-management server's device inventory and folds it into a
one-shot fleet summary an agent can call first: how many endpoints are online,
which have gone stale (not seen recently), and how spread-out the agent /
firmware / patch levels are (a wide spread is the drift signal that
``drift.config_drift`` then quantifies).

Every endpoint dict is normalised to a stable shape so downstream analysis
(``sessions``, ``drift``) never has to special-case a vendor's field names.
All server-supplied text passes through ``sanitize`` at the ``_util`` layer.
"""

from __future__ import annotations

from typing import Any

from endpoint_aiops.ops._util import as_list, s

# An endpoint not seen for this many hours is treated as "stale" (offline/lost).
_STALE_AFTER_HOURS = 24.0


def _normalise(raw: dict) -> dict:
    """Fold one raw endpoint record into the stable inventory shape.

    Vendor payloads vary; we read the common fields and fall back to ``None``
    rather than inventing values, so drift/analysis can tell "absent" from a
    real value.
    """
    return {
        "id": s(raw.get("id") or raw.get("uuid") or raw.get("mac")),
        "hostname": s(raw.get("hostname") or raw.get("name")),
        "os": s(raw.get("os") or raw.get("platform")),
        "osBuild": s(raw.get("os_build") or raw.get("build") or raw.get("firmware")),
        "agentVersion": s(raw.get("agent_version") or raw.get("agent")),
        "patchLevel": s(raw.get("patch_level") or raw.get("patch")),
        "profileId": s(raw.get("profile_id") or raw.get("profile")),
        "online": bool(raw.get("online", raw.get("connected", False))),
        "lastSeenHours": _last_seen_hours(raw),
    }


def _last_seen_hours(raw: dict) -> float | None:
    """Hours since last contact, if the server reported it numerically."""
    value = raw.get("last_seen_hours", raw.get("idle_hours"))
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return None


def list_endpoints(conn: Any) -> list[dict]:
    """[READ] All managed endpoints, normalised to the stable inventory shape."""
    return [_normalise(r) for r in as_list(conn.get("/endpoints"))]


def get_endpoint(conn: Any, endpoint_id: str) -> dict:
    """[READ] One managed endpoint by id, normalised."""
    raw = conn.get(f"/endpoints/{endpoint_id}")
    if isinstance(raw, dict) and raw:
        return _normalise(raw)
    raise KeyError(f"Endpoint '{endpoint_id}' not found.")


def _spread(rows: list[dict], key: str) -> dict[str, int]:
    """Count endpoints per distinct value of ``key`` (the version/level spread)."""
    counts: dict[str, int] = {}
    for r in rows:
        value = r.get(key) or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def fleet_overview(conn: Any) -> dict:
    """[READ] One-shot fleet summary: online/stale counts + version/patch spread.

    Resilient: if the inventory call fails the whole summary is an ``error``
    field rather than a raised traceback (a health probe must survive the thing
    it probes being unhealthy).
    """
    try:
        rows = list_endpoints(conn)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": str(exc)[:200]}

    online = [r for r in rows if r["online"]]
    stale = [
        r["hostname"] or r["id"]
        for r in rows
        if isinstance(r["lastSeenHours"], (int, float))
        and r["lastSeenHours"] >= _STALE_AFTER_HOURS
    ]
    return {
        "total": len(rows),
        "online": len(online),
        "offline": len(rows) - len(online),
        "stale": stale,
        "staleThresholdHours": _STALE_AFTER_HOURS,
        "agentVersionSpread": _spread(rows, "agentVersion"),
        "patchLevelSpread": _spread(rows, "patchLevel"),
    }
