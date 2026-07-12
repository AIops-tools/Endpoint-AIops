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

# Health-score deductions per risk signal (points off a 100 baseline). Offline
# is the heaviest; a stale-but-online box and each version/patch lag stack.
_DEDUCT_OFFLINE = 40
_DEDUCT_STALE = 20
_DEDUCT_PATCH_BEHIND = 25
_DEDUCT_AGENT_BEHIND = 15

# Score-band cutoffs and the bound on the returned worst-first list.
_BAND_HEALTHY = 80
_BAND_DEGRADED = 50
_MAX_WORST = 50


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


def _majority(rows: list[dict], field: str) -> str | None:
    """Most common non-empty value of ``field`` (the derived fleet baseline)."""
    counts: dict[str, int] = {}
    for r in rows:
        value = r.get(field)
        if value:
            counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def _band(score: int) -> str:
    """Map a 0-100 score to its health band."""
    if score >= _BAND_HEALTHY:
        return "healthy"
    if score >= _BAND_DEGRADED:
        return "degraded"
    return "critical"


def _score_endpoint(
    row: dict, stale_hours: float, base_agent: str | None, base_patch: str | None
) -> dict:
    """Score one endpoint 0-100, deducting for each risk signal (each cited)."""
    score = 100
    reasons: list[str] = []
    if not row.get("online"):
        score -= _DEDUCT_OFFLINE
        reasons.append(f"offline (-{_DEDUCT_OFFLINE})")
    last_seen = row.get("lastSeenHours")
    if isinstance(last_seen, (int, float)) and last_seen >= stale_hours:
        score -= _DEDUCT_STALE
        reasons.append(f"stale: last seen {last_seen}h ago >= {stale_hours}h (-{_DEDUCT_STALE})")
    patch = row.get("patchLevel") or None
    if base_patch is not None and patch != base_patch:
        score -= _DEDUCT_PATCH_BEHIND
        reasons.append(f"patch {patch} != baseline {base_patch} (-{_DEDUCT_PATCH_BEHIND})")
    agent = row.get("agentVersion") or None
    if base_agent is not None and agent != base_agent:
        score -= _DEDUCT_AGENT_BEHIND
        reasons.append(f"agent {agent} != baseline {base_agent} (-{_DEDUCT_AGENT_BEHIND})")
    score = max(0, min(100, score))
    return {"endpoint": row.get("hostname") or row.get("id"), "score": score,
            "band": _band(score), "reasons": reasons}


def endpoint_health_score(
    endpoints: list[dict],
    stale_hours: float = _STALE_AFTER_HOURS,
    baseline: dict | None = None,
) -> dict:
    """[READ] Composite per-endpoint health/risk score, worst endpoints first.

    Pure analysis (no I/O): folds the fleet signals inventory already knows —
    offline, stale, patch-behind, agent-behind — into one 0-100 score per
    endpoint by deducting points for each risk signal, every deduction cited in
    that endpoint's ``reasons``. The patch/agent baseline is taken from
    ``baseline`` (keys ``agentVersion`` / ``patchLevel``) or derived by fleet
    majority when none is given, so it works before a gold image is declared.
    Advisory only: the score is 100 minus cited deductions, clamped to [0,100].
    """
    rows = list(endpoints or [])
    base = baseline or {}
    base_agent = base.get("agentVersion") or _majority(rows, "agentVersion")
    base_patch = base.get("patchLevel") or _majority(rows, "patchLevel")

    scored = [_score_endpoint(r, stale_hours, base_agent, base_patch) for r in rows]
    summary = {"healthy": 0, "degraded": 0, "critical": 0}
    for e in scored:
        summary[e["band"]] += 1
    worst = sorted(scored, key=lambda e: e["score"])

    return {
        "endpointsEvaluated": len(rows),
        "baseline": {
            "agentVersion": base_agent,
            "patchLevel": base_patch,
            "source": "provided" if baseline else "fleet-majority",
        },
        "summary": summary,
        "worst": worst[:_MAX_WORST],
        "note": (
            "Advisory read-only heuristic: 100 minus cited deductions, clamped "
            "to [0,100]; bands healthy>=80, degraded 50-79, critical<50."
        ),
    }


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
