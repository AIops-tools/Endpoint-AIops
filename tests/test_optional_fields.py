"""Absent fields come back as null, not as an empty string.

An empty string reads as "this field exists and is empty"; a missing field is a
different fact. Collapsing the two hides information from any consumer, and a
smaller local model will confidently invent the difference. These tests pin the
contract end-to-end: helper, ops layer, and the CLI rendering that has to cope
with a null.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from endpoint_aiops.cli import app
from endpoint_aiops.governance import opt_str
from endpoint_aiops.ops import inventory as inv
from endpoint_aiops.ops import sessions as sess

runner = CliRunner()


@pytest.mark.unit
def test_opt_str_distinguishes_absent_from_empty():
    assert opt_str(None) is None, "absent must stay absent"
    assert opt_str("") == "", "a genuinely empty value is not the same as absent"
    assert opt_str("tc01", 64) == "tc01"


@pytest.mark.unit
def test_opt_str_still_sanitizes_and_truncates():
    assert opt_str("a\x00b") == "ab"  # control character stripped
    # A cut announces itself: the ellipsis is the only signal a reader gets
    # that what they are looking at is not the whole value.
    assert opt_str("abcdef", 3) == "ab\u2026"
    assert opt_str("abc", 3) == "abc"  # exactly at the cap is not truncated


@pytest.mark.unit
def test_opt_str_accepts_non_string_values():
    assert opt_str(42) == "42"


@pytest.mark.unit
def test_inventory_reports_absent_fields_as_none():
    """An endpoint record with no hostname/patch level reports null, not ''."""
    conn = MagicMock()
    conn.get.return_value = [{"id": "tc01"}]  # hostname/os/patch_level absent
    row = inv.list_endpoints(conn)[0]
    assert row["id"] == "tc01"
    assert row["hostname"] is None
    assert row["patchLevel"] is None
    assert row["osBuild"] is None


@pytest.mark.unit
def test_inventory_keeps_empty_string_when_source_is_empty():
    """An explicitly empty upstream value is preserved as '' — not turned into null."""
    conn = MagicMock()
    conn.get.return_value = [{"id": "tc01", "hostname": ""}]
    assert inv.list_endpoints(conn)[0]["hostname"] == ""


@pytest.mark.unit
def test_inventory_never_drops_the_key_itself():
    """Keys are always present; only their value may be null.

    Omitting a key entirely is worse than a null — the consumer cannot tell the
    field was even considered.
    """
    conn = MagicMock()
    conn.get.return_value = [{}]
    row = inv.list_endpoints(conn)[0]
    for key in ("id", "hostname", "os", "osBuild", "agentVersion",
                "patchLevel", "profileId", "online", "lastSeenHours"):
        assert key in row, f"{key} must be present even when the source omitted it"


@pytest.mark.unit
def test_sessions_report_absent_fields_as_none():
    conn = MagicMock()
    conn.get.return_value = [{"endpoint_id": "tc01"}]  # no user/timestamp
    row = sess.list_sessions(conn)[0]
    assert row["endpoint"] == "tc01"
    assert row["user"] is None
    assert row["timestamp"] is None
    assert row["result"] == "ok", "result always has a value, unlike the rest"


@pytest.mark.unit
def test_login_storm_survives_null_timestamps():
    """A null timestamp must not crash the analysis — it is simply untimed."""
    rows = [
        {"endpoint": "tc01", "user": None, "loginMs": 1000.0, "bootMs": None,
         "timestamp": None, "result": "ok"},
        {"endpoint": "tc02", "user": "u", "loginMs": 2000.0, "bootMs": None,
         "timestamp": "2026-07-12T08:00:00Z", "result": "ok"},
    ]
    out = sess.login_storm(rows)
    assert out["totalSessions"] == 2
    assert out["storms"]["items"] == []
    assert out["slowestByLogin"]["items"][0]["endpoint"] == "tc02"


@pytest.mark.unit
def test_drift_analysis_survives_null_inventory_fields():
    """Drift over rows whose fields are null must not raise on comparison."""
    from endpoint_aiops.ops import drift as dr

    rows = [
        {"hostname": "tc01", "patchLevel": "2026-06", "agentVersion": None},
        {"hostname": "tc02", "patchLevel": None, "agentVersion": None},
    ]
    out = dr.config_drift(rows, fields=["patchLevel"])
    assert out["driftedCount"] == 1
    assert out["driftedEndpoints"]["items"][0]["endpoint"] == "tc02"
    assert out["driftedEndpoints"]["items"][0]["deviations"][0]["actual"] is None


@pytest.mark.unit
def test_health_score_survives_null_fields():
    from endpoint_aiops.ops import inventory as ops

    rows = [{"hostname": None, "id": "tc01", "online": True,
             "agentVersion": None, "patchLevel": None, "lastSeenHours": None}]
    out = ops.endpoint_health_score(rows)
    assert out["endpointsEvaluated"] == 1
    assert out["worst"]["items"][0]["endpoint"] == "tc01"


@pytest.mark.unit
def test_cli_renders_rows_with_null_fields(monkeypatch):
    """The CLI must survive a null field rather than crashing on render."""
    import endpoint_aiops.cli.endpoint as endpoint_cli

    conn = MagicMock()
    conn.get.return_value = [{"id": "tc01"}]  # every other field absent
    monkeypatch.setattr(endpoint_cli, "get_connection", lambda target=None: (conn, object()))

    result = runner.invoke(app, ["endpoint", "list"])
    assert result.exit_code == 0, result.output
    assert "tc01" in result.output
    assert "null" in result.output, "an absent field must render as null, not ''"
