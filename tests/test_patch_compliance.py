"""Tests for the patch_compliance SLA/compliance measure (pure fn + MCP tool).

Proves: a fleet at/above the SLA reads as meets_sla; a below-SLA fleet reports
the right non-compliant list and verdict; an explicit target overrides the
fleet-majority target; an empty fleet is insufficient with a 0.0 rate; and the
MCP tool carries the governance marker/risk tier and runs.
"""

import pytest


@pytest.mark.unit
def test_patch_compliance_meets_sla_fleet():
    from endpoint_aiops.ops import drift as ops

    endpoints = [
        {"hostname": "tc01", "patchLevel": "2026-06"},
        {"hostname": "tc02", "patchLevel": "2026-06"},
        {"hostname": "tc03", "patchLevel": "2026-06"},
        {"hostname": "tc04", "patchLevel": "2026-06"},
    ]
    out = ops.patch_compliance(endpoints, sla_pct=95.0)
    assert out["endpointsEvaluated"] == 4
    assert out["targetPatch"] == "2026-06"
    assert out["targetSource"] == "fleet-majority"
    assert out["complianceRatePct"] == 100.0
    assert out["compliantCount"] == 4
    assert out["verdict"] == "meets_sla"
    assert out["nonCompliant"] == []


@pytest.mark.unit
def test_patch_compliance_below_sla_fleet_lists_non_compliant():
    from endpoint_aiops.ops import drift as ops

    endpoints = [
        {"hostname": "tc01", "patchLevel": "2026-06"},
        {"hostname": "tc02", "patchLevel": "2026-06"},
        {"hostname": "tc03", "patchLevel": "2026-05"},
    ]
    out = ops.patch_compliance(endpoints, sla_pct=95.0)
    assert out["targetPatch"] == "2026-06"
    assert out["compliantCount"] == 2
    assert round(out["complianceRatePct"], 2) == 66.67
    assert out["verdict"] == "below_sla"
    assert out["nonCompliant"] == [{"endpoint": "tc03", "patchLevel": "2026-05"}]


@pytest.mark.unit
def test_patch_compliance_explicit_target_vs_majority():
    from endpoint_aiops.ops import drift as ops

    endpoints = [
        {"hostname": "tc01", "patchLevel": "2026-06"},
        {"hostname": "tc02", "patchLevel": "2026-06"},
    ]
    # Fleet-majority target: everyone is on 2026-06 → 100% compliant.
    majority = ops.patch_compliance(endpoints)
    assert majority["targetSource"] == "fleet-majority"
    assert majority["targetPatch"] == "2026-06"
    assert majority["verdict"] == "meets_sla"

    # Explicit target nobody is on → 0% compliant, below SLA.
    provided = ops.patch_compliance(endpoints, target_patch="2026-07")
    assert provided["targetSource"] == "provided"
    assert provided["targetPatch"] == "2026-07"
    assert provided["compliantCount"] == 0
    assert provided["complianceRatePct"] == 0.0
    assert provided["verdict"] == "below_sla"
    assert len(provided["nonCompliant"]) == 2


@pytest.mark.unit
def test_patch_compliance_empty_fleet_is_insufficient():
    from endpoint_aiops.ops import drift as ops

    out = ops.patch_compliance([])
    assert out["endpointsEvaluated"] == 0
    assert out["complianceRatePct"] == 0.0
    assert out["compliantCount"] == 0
    assert out["verdict"] == "insufficient"
    assert out["nonCompliant"] == []


@pytest.mark.unit
def test_patch_compliance_tool_is_governed_low_and_runs():
    from mcp_server.tools import drift as tools

    fn = tools.patch_compliance
    assert getattr(fn, "_is_governed_tool", False) is True
    assert fn._risk_level == "low"

    out = fn(
        endpoints=[
            {"hostname": "tc01", "patchLevel": "2026-06"},
            {"hostname": "tc02", "patchLevel": "2026-05"},
        ],
        target_patch="2026-06",
    )
    assert "error" not in out
    assert out["verdict"] == "below_sla"
    assert out["compliantCount"] == 1
    assert out["nonCompliant"][0]["endpoint"] == "tc02"
