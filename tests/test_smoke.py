"""Smoke + ops tests for endpoint-aiops.

Proves: every module imports, the CLI Typer app builds and --help works, the
MCP server exposes the expected tools, EVERY MCP tool carries the harness
marker ``_is_governed_tool``, the pure analyses (login storm, config/patch
drift) shape correctly, and the write tools (undo capture, BEFORE-state, risk
tiers, dry-run gating) behave. No real management server is needed — the
connection is a MagicMock.
"""

import asyncio
import importlib
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

EXPECTED_TOOLS = {
    # inventory
    "overview", "endpoint_list", "endpoint_get", "endpoint_health_score",
    # sessions
    "session_list", "login_storm_analysis",
    # drift
    "drift_report", "patch_status", "patch_compliance",
    # remediation (writes)
    "endpoint_assign_profile", "endpoint_reboot",
}

WRITE_TOOLS = {"endpoint_assign_profile", "endpoint_reboot"}


@pytest.mark.unit
def test_all_modules_import():
    for name in (
        "endpoint_aiops",
        "endpoint_aiops.config",
        "endpoint_aiops.connection",
        "endpoint_aiops.doctor",
        "endpoint_aiops.secretstore",
        "endpoint_aiops.ops.inventory",
        "endpoint_aiops.ops.sessions",
        "endpoint_aiops.ops.drift",
        "endpoint_aiops.ops.remediation",
        "endpoint_aiops.cli",
        "endpoint_aiops.cli._root",
        "endpoint_aiops.cli._common",
        "endpoint_aiops.cli.init",
        "endpoint_aiops.cli.secret",
        "endpoint_aiops.cli.endpoint",
        "endpoint_aiops.cli.session",
        "endpoint_aiops.cli.drift",
        "endpoint_aiops.cli.overview",
        "endpoint_aiops.cli.doctor",
        "mcp_server.server",
        "mcp_server._shared",
        "mcp_server.tools.inventory",
        "mcp_server.tools.sessions",
        "mcp_server.tools.drift",
        "mcp_server.tools.remediation",
    ):
        importlib.import_module(name)


@pytest.mark.unit
def test_version_matches_pyproject():
    """__version__ is single-sourced from package metadata; it must track
    pyproject.toml so a release bump can never ship a stale self-report."""
    import tomllib
    from pathlib import Path

    import endpoint_aiops

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text("utf-8"))["project"]["version"]
    assert endpoint_aiops.__version__ == expected


@pytest.mark.unit
def test_cli_app_builds_and_help_works():
    from endpoint_aiops.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for sub in ("endpoint", "session", "drift", "secret", "init", "overview", "doctor", "mcp"):
        assert sub in result.output


@pytest.mark.unit
def test_cli_leaf_help_triggers_lazy_imports():
    """Recurse into leaf commands so any broken lazy import surfaces."""
    from endpoint_aiops.cli import app

    runner = CliRunner()
    for cmd in (
        ["endpoint", "--help"], ["session", "--help"], ["drift", "--help"],
        ["secret", "--help"], ["doctor", "--help"],
        ["endpoint", "list", "--help"], ["endpoint", "get", "--help"],
        ["endpoint", "assign-profile", "--help"], ["endpoint", "reboot", "--help"],
        ["session", "list", "--help"], ["session", "storm", "--help"],
        ["drift", "report", "--help"], ["drift", "patch", "--help"],
        ["secret", "list", "--help"], ["secret", "set", "--help"],
        ["overview", "--help"], ["init", "--help"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"


@pytest.mark.unit
def test_mcp_list_tools_exposes_expected_tools():
    from mcp_server.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"


@pytest.mark.unit
def test_every_mcp_tool_is_governed_by_harness():
    """Every registered tool callable must carry the @governed_tool marker."""
    from mcp_server import _shared

    tool_objs = _shared.mcp._tool_manager._tools
    assert EXPECTED_TOOLS <= set(tool_objs), "tool registry incomplete"
    assert len(tool_objs) == 13, (
        "tool count changed — update README/SKILL/server.json too"
    )
    for name, tool in tool_objs.items():
        fn = getattr(tool, "fn", None)
        assert fn is not None, f"{name} has no fn"
        assert getattr(fn, "_is_governed_tool", False), (
            f"{name} is not wrapped with @governed_tool (harness marker missing)"
        )


@pytest.mark.unit
def test_write_tools_have_correct_risk_tiers():
    """Reversible profile change = high; reboot (no undo) = medium."""
    from mcp_server.tools import remediation as rem

    assert rem.endpoint_assign_profile._risk_level == "high"
    assert rem.endpoint_reboot._risk_level == "medium"


@pytest.mark.unit
def test_assign_profile_records_undo_token_via_harness(monkeypatch):
    """assign_profile through the harness records an inverse (reassign prior)."""
    import endpoint_aiops.governance.undo as undo_mod
    from mcp_server.tools import remediation as rem

    conn = MagicMock(name="conn")
    conn.get.return_value = {"id": "tc01", "hostname": "tc01", "profile_id": "prof-old"}
    conn.post.return_value = {}
    monkeypatch.setattr(rem, "_get_connection", lambda target=None: conn)

    recorded = {}

    class _Store:
        def record(self, *, skill, tool, undo_descriptor, orig_params):
            recorded["descriptor"] = undo_descriptor
            return "undo-123"

    monkeypatch.setattr(undo_mod, "get_undo_store", lambda: _Store())

    result = rem.endpoint_assign_profile(endpoint_id="tc01", profile_id="prof-new")
    assert "error" not in result
    assert recorded["descriptor"]["tool"] == "endpoint_assign_profile"
    assert recorded["descriptor"]["params"]["profile_id"] == "prof-old"  # the prior
    assert result.get("_undo_id") == "undo-123"


@pytest.mark.unit
def test_assign_profile_captures_before_state():
    """assign_profile records the prior profile for undo/audit."""
    from endpoint_aiops.ops import remediation as ops

    conn = MagicMock(name="conn")
    conn.get.return_value = {"id": "tc01", "hostname": "tc01", "profile_id": "prof-old"}
    conn.post.return_value = {}
    result = ops.assign_profile(conn, "tc01", "prof-new")
    assert result["action"] == "assign_profile"
    assert result["priorState"]["profileId"] == "prof-old"
    conn.post.assert_called_once_with(
        "/endpoints/tc01/profile", json={"profile_id": "prof-new"}
    )


@pytest.mark.unit
def test_path_traversal_id_is_url_encoded():
    """An id containing '../' must never yield a raw '../' in the request path."""
    from endpoint_aiops.ops import inventory, remediation

    conn = MagicMock(name="conn")
    conn.get.return_value = {"id": "x", "hostname": "x", "profile_id": "prof-old"}
    conn.post.return_value = {}

    inventory.get_endpoint(conn, "../admin")
    (path,), _ = conn.get.call_args
    assert "../" not in path
    assert path == "/endpoints/..%2Fadmin"

    remediation.reboot_endpoint(conn, "../admin")
    (path,), _ = conn.post.call_args
    assert "../" not in path
    assert path == "/endpoints/..%2Fadmin/reboot"

    remediation.assign_profile(conn, "../admin", "prof-new")
    (path,), kwargs = conn.post.call_args
    assert "../" not in path
    assert path == "/endpoints/..%2Fadmin/profile"
    assert kwargs == {"json": {"profile_id": "prof-new"}}


@pytest.mark.unit
def test_dry_run_gates_destructive_cli():
    """endpoint reboot --dry-run must not touch the connection."""
    from endpoint_aiops.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["endpoint", "reboot", "tc01", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.output


@pytest.mark.unit
def test_login_storm_detects_episode_and_ranks_slow():
    """A burst of concurrent logins is one storm; the slowest login ranks first."""
    from endpoint_aiops.ops import sessions as ops

    base = "2026-07-12T08:0{m}:{s:02d}Z"
    rows = []
    for i in range(12):  # 12 logins, 20s apart → span 220s < 300s window
        m, s = divmod(i * 20, 60)
        rows.append({
            "endpoint": f"tc{i:02d}", "user": f"u{i}",
            "login_ms": 5000 + i * 100,
            "timestamp": base.format(m=m, s=s),
        })
    rows[3]["login_ms"] = 61000          # a clear slow outlier
    rows[7]["result"] = "failed"
    out = ops.login_storm(rows, window_s=300, min_concurrent=10)
    assert out["totalSessions"] == 12
    assert out["stormCount"] == 1
    storm = out["storms"]["items"][0]
    assert storm["count"] == 12 and storm["distinctEndpoints"] == 12
    assert out["slowestByLogin"]["items"][0]["endpoint"] == "tc03"   # 61000 ms wins
    assert out["slowLoginCount"] == 1                       # only tc03 > 30s
    assert out["failedLogins"] == 1


@pytest.mark.unit
def test_login_storm_no_storm_below_threshold():
    from endpoint_aiops.ops import sessions as ops

    rows = [
        {"endpoint": "tc01", "login_ms": 4000, "timestamp": "2026-07-12T08:00:00Z"},
        {"endpoint": "tc02", "login_ms": 4200, "timestamp": "2026-07-12T09:00:00Z"},
    ]
    out = ops.login_storm(rows, window_s=300, min_concurrent=10)
    assert out["stormCount"] == 0 and out["totalSessions"] == 2


@pytest.mark.unit
def test_config_drift_fleet_majority_baseline():
    """With no baseline, the majority value is the intended state; laggards drift."""
    from endpoint_aiops.ops import drift as ops

    endpoints = [
        {"hostname": "tc01", "agentVersion": "12.6", "patchLevel": "2026-06"},
        {"hostname": "tc02", "agentVersion": "12.6", "patchLevel": "2026-06"},
        {"hostname": "tc03", "agentVersion": "12.5", "patchLevel": "2026-05"},
    ]
    out = ops.config_drift(endpoints)
    assert out["baselineSource"] == "fleet-majority"
    assert out["baseline"]["agentVersion"] == "12.6"
    assert out["driftedCount"] == 1 and out["compliantCount"] == 2
    assert out["driftedEndpoints"]["items"][0]["endpoint"] == "tc03"


@pytest.mark.unit
def test_config_drift_explicit_baseline():
    from endpoint_aiops.ops import drift as ops

    endpoints = [
        {"hostname": "tc01", "patchLevel": "2026-06"},
        {"hostname": "tc02", "patchLevel": "2026-06"},
    ]
    out = ops.config_drift(endpoints, baseline={"patchLevel": "2026-07"}, fields=["patchLevel"])
    assert out["baselineSource"] == "provided"
    assert out["driftedCount"] == 2   # nobody is on 2026-07


@pytest.mark.unit
def test_patch_status_behind_target():
    from endpoint_aiops.ops import drift as ops

    endpoints = [
        {"hostname": "tc01", "patchLevel": "2026-06"},
        {"hostname": "tc02", "patchLevel": "2026-05"},
    ]
    out = ops.patch_status(endpoints, target_patch="2026-06")
    assert out["targetPatch"] == "2026-06" and out["behindCount"] == 1
    assert out["behind"]["items"][0]["endpoint"] == "tc02"


@pytest.mark.unit
def test_fleet_overview_is_resilient_to_partial_failure():
    """A failing inventory call yields an error field, not a raised traceback."""
    from endpoint_aiops.ops import inventory as ops

    conn = MagicMock(name="conn")
    conn.get.side_effect = RuntimeError("inventory boom")
    out = ops.fleet_overview(conn)
    assert "error" in out


@pytest.mark.unit
def test_fleet_overview_shapes_online_and_spread():
    from endpoint_aiops.ops import inventory as ops

    conn = MagicMock(name="conn")
    conn.get.return_value = [
        {"id": "tc01", "hostname": "tc01", "online": True, "agent_version": "12.6",
         "patch_level": "2026-06", "last_seen_hours": 0.1},
        {"id": "tc02", "hostname": "tc02", "online": False, "agent_version": "12.6",
         "patch_level": "2026-06", "last_seen_hours": 48},
    ]
    out = ops.fleet_overview(conn)
    assert out["total"] == 2 and out["online"] == 1 and out["offline"] == 1
    assert out["stale"] == ["tc02"]
    assert out["agentVersionSpread"]["12.6"] == 2


@pytest.mark.unit
def test_connection_bearer_auth_and_error_translation(monkeypatch):
    """EndpointConnection sends Bearer auth and translates non-2xx to EndpointApiError."""
    from endpoint_aiops.config import TargetConfig
    from endpoint_aiops.connection import EndpointApiError, EndpointConnection

    monkeypatch.setenv("ENDPOINT_NAS1_APIKEY", "secret-key")
    target = TargetConfig(name="nas1", host="ums.local", verify_ssl=False)

    class _Resp:
        def __init__(self, status, payload=None, content=b"{}"):
            self.status_code = status
            self._payload = payload or {}
            self.content = content
            self.text = "body"

        def json(self):
            return self._payload

    class _Client:
        def request(self, method, path, **k):
            if path == "/notfound":
                return _Resp(404, content=b"x")
            return _Resp(200, {"version": "1.2.3"}, content=b"{}")

        def close(self):
            pass

    conn = EndpointConnection(target, client=_Client())
    assert conn.get("/version")["version"] == "1.2.3"
    with pytest.raises(EndpointApiError) as ei:
        conn.get("/notfound")
    assert ei.value.status_code == 404
    assert "not found" in str(ei.value).lower()
