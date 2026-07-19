"""Tests for the composite endpoint health score (pure analysis + MCP tool).

Covers the ops function ``endpoint_health_score`` (healthy vs each deducting
signal, cited reasons, derived vs provided baseline, summary bands, worst-first
ordering, empty input) and the ``endpoint_health_score`` MCP tool (harness
marker, low risk tier, and that it runs over injected rows). All pure — no
management server is needed.
"""

import pytest

from endpoint_aiops.ops import inventory as ops


def _row(hostname, online=True, agent="12.6", patch="2026-06", last_seen=0.1):
    return {
        "hostname": hostname,
        "online": online,
        "agentVersion": agent,
        "patchLevel": patch,
        "lastSeenHours": last_seen,
    }


@pytest.mark.unit
def test_healthy_endpoint_scores_high_no_reasons():
    rows = [_row("tc01"), _row("tc02")]  # identical → majority baseline, all good
    out = ops.endpoint_health_score(rows)
    top = {e["endpoint"]: e for e in out["worst"]["items"]}
    assert top["tc01"]["score"] == 100
    assert top["tc01"]["band"] == "healthy"
    assert top["tc01"]["reasons"] == []


@pytest.mark.unit
def test_offline_deducts_and_is_cited():
    rows = [_row("tc01"), _row("tc02"), _row("bad", online=False)]
    worst = ops.endpoint_health_score(rows)["worst"]["items"][0]
    assert worst["endpoint"] == "bad"
    assert worst["score"] == 60  # 100 - 40 offline
    assert any("offline" in r for r in worst["reasons"])


@pytest.mark.unit
def test_stale_deducts_and_is_cited():
    rows = [_row("tc01"), _row("tc02"), _row("stale1", last_seen=48.0)]
    worst = ops.endpoint_health_score(rows, stale_hours=24.0)["worst"]["items"][0]
    assert worst["endpoint"] == "stale1"
    assert worst["score"] == 80  # 100 - 20 stale
    assert any("stale" in r and "48" in r for r in worst["reasons"])


@pytest.mark.unit
def test_patch_behind_deducts_and_is_cited():
    rows = [_row("tc01"), _row("tc02"), _row("lag", patch="2026-05")]
    worst = ops.endpoint_health_score(rows)["worst"]["items"][0]
    assert worst["endpoint"] == "lag"
    assert worst["score"] == 75  # 100 - 25 patch behind
    assert any("patch 2026-05" in r and "2026-06" in r for r in worst["reasons"])


@pytest.mark.unit
def test_agent_behind_deducts_and_is_cited():
    rows = [_row("tc01"), _row("tc02"), _row("lag", agent="12.5")]
    worst = ops.endpoint_health_score(rows)["worst"]["items"][0]
    assert worst["endpoint"] == "lag"
    assert worst["score"] == 85  # 100 - 15 agent behind
    assert any("agent 12.5" in r and "12.6" in r for r in worst["reasons"])


@pytest.mark.unit
def test_signals_stack_and_clamp_to_zero():
    rows = [_row("tc01"), _row("tc02")]
    rows.append(_row("worst", online=False, agent="9.0", patch="2020-01", last_seen=999.0))
    out = ops.endpoint_health_score(rows)
    worst = out["worst"]["items"][0]
    assert worst["endpoint"] == "worst"
    # 100 - 40 - 20 - 25 - 15 = 0, clamped at 0, band critical
    assert worst["score"] == 0
    assert worst["band"] == "critical"
    assert len(worst["reasons"]) == 4


@pytest.mark.unit
def test_fleet_majority_baseline_derived_when_none_passed():
    rows = [_row("tc01"), _row("tc02"), _row("lag", agent="12.5", patch="2026-05")]
    out = ops.endpoint_health_score(rows)
    assert out["baseline"]["source"] == "fleet-majority"
    assert out["baseline"]["agentVersion"] == "12.6"
    assert out["baseline"]["patchLevel"] == "2026-06"


@pytest.mark.unit
def test_provided_baseline_overrides_majority():
    rows = [_row("tc01"), _row("tc02")]  # majority is 2026-06, but nobody meets provided
    base = {"patchLevel": "2026-07", "agentVersion": "12.6"}
    out = ops.endpoint_health_score(rows, baseline=base)
    assert out["baseline"]["source"] == "provided"
    assert out["baseline"]["patchLevel"] == "2026-07"
    # both endpoints are behind the provided patch → both deducted
    assert all(
        "patch 2026-06 != baseline 2026-07" in " ".join(e["reasons"])
        for e in out["worst"]["items"]
    )


@pytest.mark.unit
def test_summary_bands_and_ordering():
    rows = [
        _row("healthy1"), _row("healthy2"),  # 100
        _row("degraded", online=False),  # 60 → degraded
        _row("critical", online=False, patch="old"),  # 60-25=35 → critical
    ]
    out = ops.endpoint_health_score(rows)
    assert out["endpointsEvaluated"] == 4
    assert out["summary"] == {"healthy": 2, "degraded": 1, "critical": 1}
    scores = [e["score"] for e in out["worst"]["items"]]
    assert scores == sorted(scores)  # worst-first (ascending score)
    assert out["worst"]["items"][0]["endpoint"] == "critical"


@pytest.mark.unit
def test_empty_input():
    out = ops.endpoint_health_score([])
    assert out["endpointsEvaluated"] == 0
    assert out["summary"] == {"healthy": 0, "degraded": 0, "critical": 0}
    assert out["worst"]["items"] == []
    assert out["baseline"]["agentVersion"] is None


@pytest.mark.unit
def test_tool_is_governed_low_risk_and_runs():
    from mcp_server.tools import inventory as inv

    fn = inv.endpoint_health_score
    assert getattr(fn, "_is_governed_tool", False) is True
    assert fn._risk_level == "low"
    result = fn(endpoints=[_row("tc01"), _row("tc02", online=False)])
    assert "error" not in result
    assert result["endpointsEvaluated"] == 2
    assert result["worst"]["items"][0]["endpoint"] == "tc02"
