"""Login/boot session MCP tools: raw listing + the login-storm analysis (read-only)."""

from typing import Any, Optional

from endpoint_aiops.governance import governed_tool
from endpoint_aiops.ops import sessions as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def session_list(since_hours: int = 24, target: Optional[str] = None) -> list:
    """[READ] Recent login/boot sessions (endpoint, user, login_ms, boot_ms, result).

    Args:
        since_hours: Look-back window in hours (1..720, default 24).
        target: Endpoint-management target name from config; omit for the default.
    """
    return ops.list_sessions(_get_connection(target), since_hours=since_hours)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def login_storm_analysis(
    since_hours: int = 24,
    window_s: float = 300.0,
    min_concurrent: int = 10,
    slow_login_ms: float = 30000.0,
    slow_boot_ms: float = 90000.0,
    sessions: Optional[list[dict[str, Any]]] = None,
    target: Optional[str] = None,
) -> dict:
    """[READ] Detect login storms + rank the slowest login/boot contributors.

    Answers "is this a morning login storm, and which endpoints/users are
    dragging login and boot times?" Groups logins into storm episodes (>=
    min_concurrent within a window_s sliding window) and flags sessions slower
    than the thresholds — every flag is reported with its number, not a verdict.
    Pass 'sessions' for pure analysis, or a target to pull live via session_list.

    Args:
        since_hours: Live look-back window when sessions is omitted (default 24).
        window_s: Sliding window that defines "concurrent" logins (default 300).
        min_concurrent: Logins within a window that constitute a storm (default 10).
        slow_login_ms: Login duration (ms) flagged as slow (default 30000).
        slow_boot_ms: Boot duration (ms) flagged as slow (default 90000).
        sessions: Injected session records — {endpoint, user, login_ms, boot_ms,
            timestamp (ISO-8601), result}; skips live collection.
        target: Endpoint-management target name from config; omit for the default.

    Returns dict: {totalSessions, stormCount, storms:[{start, end, count,
        peakConcurrent, spanS, distinctUsers, distinctEndpoints, avgLoginMs}],
        slowLoginCount, slowestByLogin[], slowestByBoot[], failedLogins,
        thresholds}.

    Example: login_storm_analysis(sessions=[{"endpoint":"tc01","user":"a",
        "login_ms":42000,"timestamp":"2026-07-12T08:00:00Z"}, ...]).
    """
    if sessions is None:
        sessions = ops.list_sessions(_get_connection(target), since_hours=since_hours)
    return ops.login_storm(
        sessions,
        window_s=window_s,
        min_concurrent=min_concurrent,
        slow_login_ms=slow_login_ms,
        slow_boot_ms=slow_boot_ms,
    )
