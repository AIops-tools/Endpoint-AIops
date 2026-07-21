"""CLI confirmed-write path — past dry-run, through governance, onto disk.

The CLI write commands delegate real execution to the ``@governed_tool``
functions in ``mcp_server.tools``. These tests drive a write command PAST the
dry-run branch and the double-confirm prompts and assert the call really went
through the governed path (audit row on disk) — the regression test for the
"CLI writes were unaudited" line-wide fix.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

import endpoint_aiops.governance.audit as audit_mod
import endpoint_aiops.governance.policy as policy_mod
import endpoint_aiops.governance.undo as undo_mod


@pytest.fixture
def gov_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ENDPOINT_AIOPS_HOME", str(tmp_path))
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()
    yield tmp_path
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()


def _audit_tools(db_path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute("SELECT tool FROM audit_log ORDER BY id")]
    finally:
        conn.close()


def _mock_conn() -> MagicMock:
    conn = MagicMock(name="conn")
    conn.get.return_value = {"id": "tc01", "hostname": "tc01", "online": True,
                             "last_seen_hours": 0.1}
    conn.post.return_value = {}
    return conn


def _no_mutating_call(conn) -> None:
    """No mutating verb reached the server, whatever else happened.

    EndpointConnection's surface is get/post/delete plus the generic
    ``request(method, path)`` escape hatch — so the escape hatch is checked by
    verb rather than assumed unused. Asserting on methods the transport does
    not have would pass vacuously against a MagicMock.
    """
    conn.post.assert_not_called()
    conn.delete.assert_not_called()
    used = [c.args[0].upper() for c in conn.request.call_args_list if c.args]
    assert not [m for m in used if m != "GET"], f"mutating request(): {used}"


@pytest.mark.unit
def test_cli_endpoint_reboot_dry_run_reads_and_audits_but_never_writes(gov_home, monkeypatch):
    """A dry_run MAY read; it must never write.

    The older "dry_run does zero I/O and leaves no trace" assumption was never a
    stated rule and is wrong on its face: a preview that cannot read cannot
    answer "would this be refused?", nor say whether the endpoint it is about to
    reboot is even online — which for an operation with no inverse is the whole
    point of asking first. So the read is expected, the audit row is expected
    (MCP previews were always audited — the CLI silently not auditing was the
    outlier), and only the MUTATING call is forbidden.
    """
    from endpoint_aiops.cli import app

    conn = _mock_conn()
    import mcp_server.tools.remediation as gov

    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    result = CliRunner().invoke(app, ["endpoint", "reboot", "tc01", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output  # human banner preserved, not raw JSON
    assert conn.get.called  # it DID read, to resolve the path and the state
    _no_mutating_call(conn)
    assert _audit_tools(gov_home / "audit.db") == ["endpoint_reboot"]


@pytest.mark.unit
def test_cli_endpoint_reboot_dry_run_reports_the_real_online_state(gov_home, monkeypatch):
    """The preview carries what the tool actually read, not a hardcoded string."""
    from endpoint_aiops.cli import app

    conn = _mock_conn()
    conn.get.return_value = {"id": "tc01", "hostname": "tc01", "online": False,
                             "last_seen_hours": 72.5}
    import mcp_server.tools.remediation as gov

    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    result = CliRunner().invoke(app, ["endpoint", "reboot", "tc01", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "currently_online = False" in result.output
    assert "72.5" in result.output


@pytest.mark.unit
def test_cli_endpoint_reboot_dry_run_records_no_undo_token(gov_home, monkeypatch):
    """A preview changed nothing, so there is nothing to reverse."""
    from endpoint_aiops.cli import app

    conn = _mock_conn()
    import mcp_server.tools.remediation as gov

    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    CliRunner().invoke(app, ["endpoint", "reboot", "tc01", "--dry-run"])
    if (gov_home / "undo.db").exists():
        rows = sqlite3.connect(gov_home / "undo.db").execute(
            "SELECT undo_tool FROM undo_log"
        ).fetchall()
        assert rows == [], f"dry-run registered a phantom undo: {rows}"


@pytest.mark.unit
def test_cli_endpoint_reboot_dry_run_on_a_server_without_reboot_refuses_nonzero(
    gov_home, monkeypatch
):
    """A management server with no reboot resource must refuse the PREVIEW too.

    Otherwise the preview promises a reboot that the write then rejects — and a
    caller reading a green banner followed by a refusal treats the refusal as
    transient and retries.
    """
    from endpoint_aiops.cli import app
    from endpoint_aiops.dialect import Dialect
    from endpoint_aiops.ops import _util

    conn = _mock_conn()
    import mcp_server.tools.remediation as gov

    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    monkeypatch.setattr(_util, "dialect_of", lambda c: Dialect(name="no-reboot",
                                                               reboot_path=None))
    result = CliRunner().invoke(app, ["endpoint", "reboot", "tc01", "--dry-run"])
    assert result.exit_code == 1
    assert "does not expose a 'reboot' resource" in result.output
    assert "DRY-RUN" not in result.output  # no green banner for a refusal
    # str(KeyError) repr-quotes its message; the flattened-dict path must strip
    # them exactly as cli_errors does on the exception path.
    assert 'Error: "' not in result.output
    _no_mutating_call(conn)


@pytest.mark.unit
def test_cli_endpoint_assign_profile_dry_run_reads_and_audits_but_never_writes(
    gov_home, monkeypatch
):
    """A dry_run MAY read; it must never write."""
    from endpoint_aiops.cli import app

    conn = _mock_conn()
    import mcp_server.tools.remediation as gov

    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    result = CliRunner().invoke(
        app, ["endpoint", "assign-profile", "tc01", "p9", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    _no_mutating_call(conn)
    assert _audit_tools(gov_home / "audit.db") == ["endpoint_assign_profile"]


@pytest.mark.unit
def test_cli_undo_apply_dry_run_of_an_unknown_token_refuses_nonzero(gov_home):
    """An unknown undo id is a refusal, not a preview of 'inverse: ?'.

    Before the reroute this printed a green banner naming the inverse tool as
    '?' — a preview of an operation that does not exist.
    """
    from endpoint_aiops.cli import app

    result = CliRunner().invoke(app, ["undo", "apply", "nope-not-a-token", "--dry-run"])
    assert result.exit_code == 1
    assert "Unknown undo id" in result.output
    assert "DRY-RUN" not in result.output


@pytest.mark.unit
def test_cli_endpoint_reboot_confirmed_goes_through_governance(gov_home, monkeypatch):
    """Confirmed CLI write must execute via the governed twin: the API call runs
    AND an audit row lands in audit.db (this is what the reroute fix bought)."""
    from endpoint_aiops.cli import app

    conn = _mock_conn()
    import mcp_server.tools.remediation as gov

    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    result = CliRunner().invoke(app, ["endpoint", "reboot", "tc01"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    assert conn.post.called
    assert _audit_tools(gov_home / "audit.db") == ["endpoint_reboot"]


@pytest.mark.unit
def test_cli_endpoint_reboot_aborts_without_double_confirm(gov_home, monkeypatch):
    from endpoint_aiops.cli import app

    conn = _mock_conn()
    import mcp_server.tools.remediation as gov

    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    result = CliRunner().invoke(app, ["endpoint", "reboot", "tc01"], input="y\nn\n")
    assert result.exit_code != 0
    assert not conn.get.called and not conn.post.called
    assert not (gov_home / "audit.db").exists()
