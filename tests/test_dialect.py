"""Management-server dialects — configurable paths + field aliases (pure)."""

from pathlib import Path

import pytest
import yaml

from endpoint_aiops.config import TargetConfig
from endpoint_aiops.dialect import (
    DEFAULT_DIALECT,
    Dialect,
    UnsupportedResource,
    resolve,
)
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


# ── IGEL preset + resource-absence (bug class 7: an invented API shape) ──────


@pytest.mark.unit
def test_igel_preset_is_selectable_by_name():
    """An operator must not have to reverse-engineer IGEL's shape from scratch."""
    d = resolve("igel-ums")
    assert d.name == "igel-ums"
    assert d.endpoints_path == "/thinclients"
    assert d.version_path == "/serverstatus"


@pytest.mark.unit
def test_igel_preset_carries_imi_transport_defaults():
    """IMI is /umsapi/v3 on 8443 — the generic /api/v2.0 on 443 404s on IGEL."""
    d = resolve("igel-ums")
    assert d.default_port == 8443
    assert d.default_api_path == "/umsapi/v3"


@pytest.mark.unit
def test_generic_placeholder_keeps_its_legacy_transport_defaults():
    assert DEFAULT_DIALECT.default_port == 443
    assert DEFAULT_DIALECT.default_api_path == "/api/v2.0"


@pytest.mark.unit
def test_igel_preset_maps_imi_field_names():
    d = resolve("igel-ums")
    assert d.pick({"unitID": "42"}, "id") == "42"
    assert d.pick({"unitName": "Reception"}, "hostname") == "Reception"
    assert d.pick({"firmwareVersion": "12.6"}, "osBuild") == "12.6"


@pytest.mark.unit
def test_igel_has_no_sessions_resource_and_says_so():
    """IMI exposes no session resource. Absent must not be faked into a URL."""
    d = resolve("igel-ums")
    with pytest.raises(UnsupportedResource) as ei:
        d.path_for("sessions")
    assert "does not expose" in str(ei.value)


@pytest.mark.unit
def test_unsupported_resource_does_not_read_as_a_missing_config_key(capsys):
    """The CLI labels bare KeyErrors 'Missing required key' — this must dodge it.

    Regression for the cicd-aiops bug: a correct diagnosis under a wrong
    headline sent operators hunting a config problem that did not exist.
    """
    import typer

    from endpoint_aiops.cli._common import cli_errors

    assert issubclass(UnsupportedResource, KeyError)  # legacy handlers keep working

    @cli_errors
    def boom():
        resolve("igel-ums").path_for("sessions")

    with pytest.raises(typer.Exit):
        boom()
    out = capsys.readouterr().out
    assert "Missing required key" not in out
    assert "does not expose" in out
    assert not out.count('\\"')  # KeyError's repr quotes are stripped


@pytest.mark.unit
def test_session_read_on_igel_teaches_instead_of_calling_an_invented_path():
    target = _target("igel-ums")
    conn = _Conn(target, {})
    with pytest.raises(UnsupportedResource):
        sessions.list_sessions(conn)


@pytest.mark.unit
def test_preset_can_be_layered_with_overrides():
    """A site whose IMI differs states only the delta, keeping the rest."""
    d = resolve({"preset": "igel-ums", "sessions_path": "/usage",
                 "fields": {"user": ["lastUser"]}})
    assert d.endpoints_path == "/thinclients"      # from the preset
    assert d.path_for("sessions") == "/usage"      # overridden
    assert d.pick({"lastUser": "amy"}, "user") == "amy"
    assert d.pick({"unitID": "42"}, "id") == "42"  # preset fields survive


@pytest.mark.unit
def test_unknown_preset_name_is_a_teaching_error():
    with pytest.raises(UnsupportedResource) as ei:
        resolve("igel-umms")
    assert "igel-ums" in str(ei.value)  # names the available presets


@pytest.mark.unit
def test_generic_dialect_still_exposes_every_resource():
    """The legacy shape is unchanged for anyone already relying on it."""
    for resource in ("endpoints", "endpoint", "sessions", "version",
                     "profile", "reboot"):
        assert DEFAULT_DIALECT.path_for(resource)
