"""Management-server dialects — configurable paths + field aliases (pure)."""

from pathlib import Path

import pytest
import yaml

from endpoint_aiops.config import TargetConfig
from endpoint_aiops.dialect import DEFAULT_DIALECT, Dialect, resolve
from endpoint_aiops.ops import inventory, sessions

_OVERLAY = Path(__file__).resolve().parent.parent / "deploy" / "igel-ums" / "dialect.yaml"


class _Conn:
    """Minimal connection stub carrying a target dialect + canned GET responses."""

    def __init__(self, target, responses):
        self.target = target
        self._responses = responses

    def get(self, path, **_kw):
        return self._responses[path]


def _target(dialect):
    return TargetConfig(name="t", host="h", dialect=dialect)


@pytest.mark.unit
def test_default_dialect_matches_legacy_shape():
    assert resolve(None) is DEFAULT_DIALECT
    assert DEFAULT_DIALECT.endpoints_path == "/endpoints"
    assert DEFAULT_DIALECT.endpoint_path == "/endpoints/{id}"
    # legacy field fallbacks preserved
    assert DEFAULT_DIALECT.pick({"uuid": "x"}, "id") == "x"
    assert DEFAULT_DIALECT.pick({"connected": True}, "online") is True


@pytest.mark.unit
def test_resolve_overrides_paths_and_merges_fields():
    d = resolve({"name": "custom", "endpoints_path": "/thinclients",
                 "fields": {"id": ["unitID"]}})
    assert isinstance(d, Dialect)
    assert d.endpoints_path == "/thinclients"
    assert d.pick({"unitID": "tc1"}, "id") == "tc1"       # overridden
    assert d.pick({"name": "TC-1"}, "hostname") == "TC-1"  # default kept


@pytest.mark.unit
def test_list_endpoints_uses_dialect_paths_and_fields():
    target = _target({"endpoints_path": "/thinclients",
                      "fields": {"id": ["unitID"], "hostname": ["unitName"]}})
    conn = _Conn(target, {"/thinclients": [
        {"unitID": "tc1", "unitName": "Reception", "online": True},
    ]})
    rows = inventory.list_endpoints(conn)
    assert rows[0]["id"] == "tc1" and rows[0]["hostname"] == "Reception"
    assert rows[0]["online"] is True


@pytest.mark.unit
def test_get_endpoint_formats_dialect_path():
    target = _target({"endpoint_path": "/thinclients/{id}", "fields": {"id": ["unitID"]}})
    conn = _Conn(target, {"/thinclients/abc": {"unitID": "abc", "name": "X"}})
    assert inventory.get_endpoint(conn, "abc")["id"] == "abc"


@pytest.mark.unit
def test_sessions_use_dialect_path_and_envelope():
    target = _target({"sessions_path": "/usage", "list_key": "items",
                      "fields": {"sessionEndpoint": ["tc"], "loginMs": ["login"]}})
    conn = _Conn(target, {"/usage": {"items": [{"tc": "tc1", "login": 42000}]}})
    rows = sessions.list_sessions(conn)
    assert rows[0]["endpoint"] == "tc1" and rows[0]["loginMs"] == 42000.0


@pytest.mark.unit
def test_default_conn_without_target_falls_back_to_generic():
    # A bare object with no .target must not crash — generic default applies.
    conn = _Conn(None, {"/endpoints": [{"id": "e1", "hostname": "h1"}]})
    conn.target = None
    assert inventory.list_endpoints(conn)[0]["id"] == "e1"


@pytest.mark.unit
def test_igel_ums_overlay_dialect_resolves():
    """The deploy overlay is a valid dialect the package can consume (no vendor code in the pkg)."""
    raw = yaml.safe_load(_OVERLAY.read_text("utf-8"))
    spec = raw["targets"][0]["dialect"]
    d = resolve(spec)
    assert d.name == "igel-ums"
    assert d.endpoints_path == "/thinclients"
    assert d.pick({"unitID": "42"}, "id") == "42"
    assert d.pick({"firmwareVersion": "12.6"}, "osBuild") == "12.6"
