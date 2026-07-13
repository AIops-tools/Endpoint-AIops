"""Shared helpers for endpoint-management ops modules.

Endpoint-management REST list endpoints return a bare JSON array; a few wrap
results in ``{"data": [...]}``. ``as_list`` normalises both. All API-returned
text reaches the caller only after ``sanitize()`` (output hygiene).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from endpoint_aiops.governance import sanitize


def _seg(value: Any) -> str:
    """URL-encode one path segment so agent-supplied ids cannot alter the path.

    ``quote(..., safe="")`` also encodes ``/``, so an id like ``../reboot``
    becomes ``..%2Freboot`` instead of traversing to a different resource.
    """
    return quote(str(value), safe="")


def as_list(data: Any, list_key: str | None = None) -> list[dict]:
    """Normalise a list payload to a list of dicts.

    A bare JSON array passes through; a dict is unwrapped via ``list_key`` (a
    dialect's envelope key) when given, else the conventional ``data`` key.
    """
    if isinstance(data, dict):
        items = data.get(list_key if list_key else "data", [])
    else:
        items = data
    return [i for i in (items or []) if isinstance(i, dict)]


def dialect_of(conn: Any):
    """The connection's target dialect, or the generic default for a bare/mock conn.

    Only a genuine ``Dialect`` is honoured — a ``MagicMock`` connection auto-creates
    a truthy ``target.dialect_obj``, so we type-check rather than truth-test.
    """
    from endpoint_aiops.dialect import DEFAULT_DIALECT, Dialect

    candidate = getattr(getattr(conn, "target", None), "dialect_obj", None)
    return candidate if isinstance(candidate, Dialect) else DEFAULT_DIALECT


def s(value: Any, limit: int = 128) -> str:
    """Sanitize an arbitrary value to a bounded, injection-safe string."""
    return sanitize(str(value if value is not None else ""), limit)
