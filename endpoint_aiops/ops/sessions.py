"""Endpoint login / boot sessions — read + the login-storm analysis (pure).

``list_sessions`` reads recent login/boot records from the endpoint-management
server. ``login_storm`` is the signature analysis: given those records (or any
injected list), it answers the VDI/thin-client operator's first question during
a morning "everyone logs in at once" incident — *is this a login storm, and
which endpoints/users are dragging login and boot times?*

``login_storm`` is a pure function (no I/O): pass it session records and it
returns storm episodes + the slowest contributors. It is deliberately a
transparent heuristic — storms are grouped by a sliding time window and slow
sessions are flagged by a millisecond threshold, both reported with their
numbers so an operator can see *why* something was flagged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from endpoint_aiops.dialect import DEFAULT_DIALECT
from endpoint_aiops.ops._util import as_list, dialect_of, s

# Analysis is bounded so a huge export can never blow up latency or output.
MAX_SESSIONS = 20000
MAX_ROWS = 25

# Defaults: a "storm" is >= 10 logins inside a 5-minute window; a login taking
# longer than 30s (or boot > 90s) is "slow". All three are caller-overridable.
DEFAULT_WINDOW_S = 300.0
DEFAULT_MIN_CONCURRENT = 10
DEFAULT_SLOW_LOGIN_MS = 30000.0
DEFAULT_SLOW_BOOT_MS = 90000.0


def list_sessions(conn: Any, since_hours: int = 24) -> list[dict]:
    """[READ] Recent login/boot sessions from the management server."""
    hours = max(1, min(int(since_hours), 24 * 30))
    d = dialect_of(conn)
    raw = conn.get(d.sessions_path, params={"since_hours": hours})
    return [_normalise(r, d) for r in as_list(raw, d.list_key)]


def _normalise(raw: dict, dialect: Any = None) -> dict:
    """Fold one raw session record into the stable analysis shape (dialect-mapped)."""
    d = dialect or DEFAULT_DIALECT
    return {
        "endpoint": s(d.pick(raw, "sessionEndpoint")),
        "user": s(d.pick(raw, "user")),
        "loginMs": _num(d.pick(raw, "loginMs")),
        "bootMs": _num(d.pick(raw, "bootMs")),
        "timestamp": s(d.pick(raw, "timestamp")),
        "result": s(d.pick(raw, "result") or "ok"),
    }


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _epoch(ts: str) -> float | None:
    """Parse an ISO-8601 timestamp to epoch seconds; None if unparseable."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _episodes(times: list[float], window_s: float, min_concurrent: int) -> list[tuple[int, int]]:
    """Merge every ``window_s``-wide flood window into episode index ranges.

    ``times`` must be sorted ascending. A window anchored at event *i* covers
    events *i..j* while ``times[j] - times[i] < window_s``; the window floods
    when it holds >= ``min_concurrent`` events. Overlapping flood windows merge
    into one episode (an inclusive ``(start, end)`` index range).
    """
    n = len(times)
    ranges: list[tuple[int, int]] = []
    for i in range(n):
        j = i
        while j + 1 < n and times[j + 1] - times[i] < window_s:
            j += 1
        if j - i + 1 >= min_concurrent:
            ranges.append((i, j))
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _peak_concurrent(times: list[float], lo: int, hi: int, window_s: float) -> int:
    """Max events inside any ``window_s`` window within the episode span."""
    peak = 0
    for i in range(lo, hi + 1):
        j = i
        while j + 1 <= hi and times[j + 1] - times[i] < window_s:
            j += 1
        peak = max(peak, j - i + 1)
    return peak


def _avg(values: list[float]) -> float | None:
    nums = [v for v in values if isinstance(v, (int, float))]
    return round(sum(nums) / len(nums), 1) if nums else None


def login_storm(
    sessions: list[dict],
    window_s: float = DEFAULT_WINDOW_S,
    min_concurrent: int = DEFAULT_MIN_CONCURRENT,
    slow_login_ms: float = DEFAULT_SLOW_LOGIN_MS,
    slow_boot_ms: float = DEFAULT_SLOW_BOOT_MS,
) -> dict:
    """[READ] Detect login storms and rank the slowest login/boot contributors.

    Pure analysis over ``sessions`` ({endpoint, user, loginMs, bootMs,
    timestamp, result}); records may come from ``list_sessions`` or be injected.
    Returns storm *episodes* (each with peak concurrency, distinct users/
    endpoints, and average login time), the slowest endpoints by login and boot
    time, a count of failed logins, and the thresholds used — nothing is
    flagged without its number.
    """
    rows = [_normalise(r) if "loginMs" not in r else r for r in (sessions or [])][:MAX_SESSIONS]
    total = len(rows)

    timed = sorted(
        ((_epoch(r.get("timestamp", "")), r) for r in rows),
        key=lambda pair: (pair[0] is None, pair[0] or 0.0),
    )
    times = [t for t, _ in timed if t is not None]
    ordered = [r for t, r in timed if t is not None]

    episodes = []
    for lo, hi in _episodes(times, window_s, min_concurrent):
        members = ordered[lo : hi + 1]
        episodes.append({
            "start": members[0].get("timestamp"),
            "end": members[-1].get("timestamp"),
            "count": len(members),
            "peakConcurrent": _peak_concurrent(times, lo, hi, window_s),
            "spanS": round(times[hi] - times[lo], 1),
            "distinctUsers": len({m.get("user") for m in members if m.get("user")}),
            "distinctEndpoints": len({m.get("endpoint") for m in members if m.get("endpoint")}),
            "avgLoginMs": _avg([m.get("loginMs") for m in members]),
        })

    slow_logins = sorted(
        (r for r in rows if isinstance(r.get("loginMs"), (int, float))),
        key=lambda r: r["loginMs"],
        reverse=True,
    )
    slow_boots = sorted(
        (r for r in rows if isinstance(r.get("bootMs"), (int, float))),
        key=lambda r: r["bootMs"],
        reverse=True,
    )
    failed = [r for r in rows if str(r.get("result", "")).lower() in {"fail", "failed", "error"}]

    return {
        "totalSessions": total,
        "stormCount": len(episodes),
        "storms": episodes[:MAX_ROWS],
        "slowLoginCount": sum(1 for r in slow_logins if r["loginMs"] >= slow_login_ms),
        "slowestByLogin": [_contrib(r, "loginMs") for r in slow_logins[:MAX_ROWS]],
        "slowestByBoot": [_contrib(r, "bootMs") for r in slow_boots[:MAX_ROWS]],
        "failedLogins": len(failed),
        "thresholds": {
            "windowS": window_s,
            "minConcurrent": min_concurrent,
            "slowLoginMs": slow_login_ms,
            "slowBootMs": slow_boot_ms,
        },
    }


def _contrib(row: dict, metric: str) -> dict:
    return {
        "endpoint": row.get("endpoint"),
        "user": row.get("user"),
        metric: row.get(metric),
        "timestamp": row.get("timestamp"),
    }
