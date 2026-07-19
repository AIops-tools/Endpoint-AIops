"""Patch / configuration drift across an endpoint fleet (pure analysis).

The second signature analysis: given endpoint inventory, answer *which
endpoints have drifted from the fleet* — outdated patch level, a stray agent
version, a divergent OS build or config profile. This is the "why is one thin
client behaving differently" question, made fleet-wide.

``config_drift`` is pure (no I/O): pass it inventory rows (from
``inventory.list_endpoints`` or injected) and, optionally, an explicit baseline.
With no baseline it derives one by fleet majority (the most common value per
field is treated as the intended state), so it works out-of-the-box on a fleet
that has no declared gold image yet.
"""

from __future__ import annotations

from endpoint_aiops.ops._util import envelope

# Inventory fields compared for drift, in report order.
DEFAULT_FIELDS = ("agentVersion", "patchLevel", "osBuild", "profileId")

MAX_ROWS = 200


def _majority(rows: list[dict], field: str) -> str | None:
    """Most common non-empty value of ``field`` across the fleet (the baseline)."""
    counts: dict[str, int] = {}
    for r in rows:
        value = r.get(field)
        if value:
            counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def _value_spread(rows: list[dict], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        value = r.get(field) or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def config_drift(
    endpoints: list[dict],
    baseline: dict | None = None,
    fields: list[str] | None = None,
    limit: int = MAX_ROWS,
) -> dict:
    """[READ] Report endpoints that deviate from a per-field baseline.

    Args mirror the tool: ``endpoints`` are inventory rows; ``baseline`` maps a
    field to its intended value (omit to derive the fleet majority); ``fields``
    overrides which fields are checked (default: agent version, patch level, OS
    build, profile); ``limit`` caps how many drifted endpoints are returned.
    Returns per-field drift counts, the effective baseline, and the drifted
    endpoints with their exact expected-vs-actual deviations.

    ``driftedEndpoints`` is a truncation envelope — ``{"items": [...],
    "returned": N, "limit": L, "truncated": bool}`` — so a capped list says so
    itself. ``driftedCount`` remains the full, uncapped count.
    """
    rows = list(endpoints or [])
    checked = [f for f in (fields or DEFAULT_FIELDS)]

    effective = dict(baseline) if baseline else {}
    source = "provided" if baseline else "fleet-majority"
    if not baseline:
        effective = {f: _majority(rows, f) for f in checked}

    drift_by_field: dict[str, dict] = {}
    drifted: list[dict] = []
    for r in rows:
        deviations = []
        for f in checked:
            expected = effective.get(f)
            actual = r.get(f) or None
            # Only a genuine mismatch counts; an unset baseline field is skipped.
            if expected is not None and actual != expected:
                deviations.append({"field": f, "expected": expected, "actual": actual})
                bucket = drift_by_field.setdefault(
                    f, {"expected": expected, "deviating": 0, "values": {}}
                )
                bucket["deviating"] += 1
        if deviations:
            drifted.append({
                "endpoint": r.get("hostname") or r.get("id"),
                "deviations": deviations,
            })

    for f in checked:
        if f in drift_by_field:
            drift_by_field[f]["values"] = _value_spread(rows, f)

    return {
        "totalEndpoints": len(rows),
        "baselineSource": source,
        "baseline": effective,
        "fieldsChecked": checked,
        "driftedCount": len(drifted),
        "compliantCount": len(rows) - len(drifted),
        "driftByField": drift_by_field,
        "driftedEndpoints": envelope(drifted, limit),
    }


def patch_status(
    endpoints: list[dict], target_patch: str | None = None, limit: int = MAX_ROWS
) -> dict:
    """[READ] Patch-level distribution + which endpoints are behind the target.

    ``target_patch`` is the desired level; with none, the fleet-majority level
    is used. "Behind" is a plain string inequality against that target — a
    transparent check, not a version-semantics parser. ``limit`` caps the
    returned list; ``behind`` is a truncation envelope ({items, returned, limit,
    truncated}) while ``behindCount`` stays the full count.
    """
    rows = list(endpoints or [])
    target = target_patch or _majority(rows, "patchLevel")
    behind = [
        {"endpoint": r.get("hostname") or r.get("id"), "patchLevel": r.get("patchLevel") or None}
        for r in rows
        if target is not None and (r.get("patchLevel") or None) != target
    ]
    return {
        "totalEndpoints": len(rows),
        "targetPatch": target,
        "targetSource": "provided" if target_patch else "fleet-majority",
        "distribution": _value_spread(rows, "patchLevel"),
        "behindCount": len(behind),
        "behind": envelope(behind, limit),
    }


def patch_compliance(
    endpoints: list[dict],
    target_patch: str | None = None,
    sla_pct: float = 95.0,
    limit: int = MAX_ROWS,
) -> dict:
    """[READ] Patch-compliance SLA measure: % of the fleet on the target level.

    The SLA/compliance companion to ``patch_status``: instead of the patch-level
    *distribution*, it answers "what fraction of the fleet is on the target
    patch, and does that meet the SLA?" ``target_patch`` is the desired level;
    with none, the fleet-majority level is used. A compliant endpoint is an exact
    string match on ``patchLevel`` — a transparent check, not a version-semantics
    parser. Compliance rate is compliant / evaluated x 100 (0.0 on an empty
    fleet). Verdict is ``meets_sla`` when the rate >= ``sla_pct``, ``below_sla``
    otherwise, and ``insufficient`` for an empty fleet. ``limit`` caps the
    returned ``nonCompliant`` list, which is a truncation envelope ({items,
    returned, limit, truncated}); the compliance rate is always computed over
    the whole fleet, never over the capped list.
    """
    rows = list(endpoints or [])
    target = target_patch or _majority(rows, "patchLevel")
    non_compliant = [
        {"endpoint": r.get("hostname") or r.get("id"), "patchLevel": r.get("patchLevel") or None}
        for r in rows
        if (r.get("patchLevel") or None) != target
    ]
    compliant_count = len(rows) - len(non_compliant)
    rate = (compliant_count / len(rows) * 100) if rows else 0.0
    verdict = "insufficient" if not rows else ("meets_sla" if rate >= sla_pct else "below_sla")
    return {
        "endpointsEvaluated": len(rows),
        "targetPatch": target,
        "targetSource": "provided" if target_patch else "fleet-majority",
        "slaTargetPct": sla_pct,
        "complianceRatePct": round(rate, 2),
        "compliantCount": compliant_count,
        "verdict": verdict,
        "nonCompliantCount": len(non_compliant),
        "nonCompliant": envelope(non_compliant, limit),
        "note": (
            "Advisory read-only SLA check: compliance is an exact-match on "
            "patchLevel against the target, not a version-semantics comparison."
        ),
    }
