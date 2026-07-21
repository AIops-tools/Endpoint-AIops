"""Per-dialect authentication strategies + how the connection layer uses them.

The point of these tests is that the *dialect* selects the scheme. Correcting
IGEL's paths while still sending it a Bearer token left the real blocker in
place, so the regressions worth guarding are: the right scheme is chosen, the
handshake happens exactly once, and a scheme mismatch is reported as a scheme
mismatch rather than as bad credentials.
"""

from __future__ import annotations

import base64

import pytest

from endpoint_aiops.auth import (
    STRATEGIES,
    AuthSchemeError,
    BearerAuth,
    ImiSessionAuth,
    for_dialect,
)
from endpoint_aiops.config import TargetConfig
from endpoint_aiops.connection import EndpointApiError, EndpointConnection
from endpoint_aiops.dialect import DEFAULT_DIALECT, IGEL_UMS_DIALECT, resolve


class _Resp:
    def __init__(self, status=200, payload=None, content=b"{}", headers=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.content = content
        self.text = "body"
        self.headers = headers or {}

    def json(self):
        return self._payload


class _Client:
    """Records every call so a handshake can be counted, not just observed."""

    def __init__(self, routes=None, default=None):
        self.calls = []
        self._routes = routes or {}
        self._default = default or _Resp(200, {"ok": True})

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs.get("headers") or {}))
        return self._routes.get(path, self._default)

    def close(self):
        pass


def _target(name="t", dialect=None, username="", **kw):
    return TargetConfig(name=name, host="h", dialect=dialect, username=username, **kw)


# ── the dialect selects the scheme ─────────────────────────────────────────


@pytest.mark.unit
def test_generic_dialect_keeps_bearer():
    assert DEFAULT_DIALECT.auth == "bearer"
    assert isinstance(for_dialect(DEFAULT_DIALECT), BearerAuth)


@pytest.mark.unit
def test_igel_dialect_selects_imi_session_not_bearer():
    """The whole fix: IGEL must not be sent a static Bearer token."""
    assert IGEL_UMS_DIALECT.auth == "imi-session"
    assert isinstance(for_dialect(IGEL_UMS_DIALECT), ImiSessionAuth)


@pytest.mark.unit
def test_auth_scheme_is_overridable_from_a_config_dialect_block():
    assert resolve({"preset": "igel-ums", "auth": "bearer"}).auth == "bearer"


@pytest.mark.unit
def test_unknown_auth_scheme_names_the_available_ones():
    with pytest.raises(AuthSchemeError) as ei:
        for_dialect(resolve({"auth": "no-such-scheme"}))
    message = str(ei.value)
    assert "no-such-scheme" in message
    for name in STRATEGIES:
        assert name in message


# ── bearer ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_bearer_sends_static_header_and_performs_no_handshake(monkeypatch):
    monkeypatch.setenv("ENDPOINT_T_APIKEY", "secret-key")
    client = _Client()
    conn = EndpointConnection(_target(), client=client)
    conn.get("/endpoints")
    assert [c[0] for c in client.calls] == ["GET"]  # no login round-trip
    assert conn.auth_strategy.static_headers(_target()) == {
        "Authorization": "Bearer secret-key"
    }


# ── IMI session ────────────────────────────────────────────────────────────


def _imi_target(monkeypatch, username="ums-admin", password="W00t"):
    monkeypatch.setenv("ENDPOINT_IMI_APIKEY", password)
    return _target(name="imi", dialect="igel-ums", username=username)


@pytest.mark.unit
def test_imi_logs_in_with_basic_then_sends_session_cookie(monkeypatch):
    target = _imi_target(monkeypatch)
    client = _Client(
        routes={
            "/login": _Resp(200, {"message": "JSESSIONID=DEADBEEF"}),
            "/endpoints": _Resp(200, [{"id": "e1"}]),
        }
    )
    conn = EndpointConnection(target, client=client)
    conn.get("/thinclients")

    login_method, login_path, login_headers = client.calls[0]
    assert (login_method, login_path) == ("POST", "/login")
    expected = base64.b64encode(b"ums-admin:W00t").decode()
    assert login_headers["Authorization"] == f"Basic {expected}"

    _, _, read_headers = client.calls[1]
    assert read_headers["Cookie"] == "JSESSIONID=DEADBEEF"


@pytest.mark.unit
def test_imi_does_not_double_prefix_the_session_cookie(monkeypatch):
    """IMI's ``message`` already reads ``JSESSIONID=<hex>``.

    Formatting it as ``f"JSESSIONID={value}"`` yields
    ``JSESSIONID=JSESSIONID=<hex>`` — which is exactly why the reference
    clients split the value on ``=``.
    """
    target = _imi_target(monkeypatch)
    client = _Client(routes={"/login": _Resp(200, {"message": "JSESSIONID=ABC123"})})
    conn = EndpointConnection(target, client=client)
    conn.get("/thinclients")
    assert client.calls[1][2]["Cookie"] == "JSESSIONID=ABC123"
    assert "JSESSIONID=JSESSIONID" not in client.calls[1][2]["Cookie"]


@pytest.mark.unit
def test_imi_accepts_a_bare_session_id_too(monkeypatch):
    """A server returning just the hex must still produce a valid cookie."""
    target = _imi_target(monkeypatch)
    client = _Client(routes={"/login": _Resp(200, {"message": "ABC123"})})
    conn = EndpointConnection(target, client=client)
    conn.get("/thinclients")
    assert client.calls[1][2]["Cookie"] == "JSESSIONID=ABC123"


@pytest.mark.unit
def test_imi_handshake_runs_once_and_is_cached_for_the_connection(monkeypatch):
    target = _imi_target(monkeypatch)
    client = _Client(routes={"/login": _Resp(200, {"message": "JSESSIONID=X"})})
    conn = EndpointConnection(target, client=client)
    conn.get("/a")
    conn.get("/b")
    conn.get("/c")
    assert [c[1] for c in client.calls].count("/login") == 1


@pytest.mark.unit
def test_imi_without_username_names_the_scheme_not_a_missing_config_key(monkeypatch):
    """A bare KeyError here renders as 'Missing required key' — the wrong hunt."""
    target = _imi_target(monkeypatch, username="")
    conn = EndpointConnection(target, client=_Client())
    with pytest.raises(AuthSchemeError) as ei:
        conn.get("/thinclients")
    message = str(ei.value)
    assert "imi-session" in message
    assert "username" in message
    assert "Devices level" in message  # the empty-list permission trap


@pytest.mark.unit
def test_imi_refuses_to_continue_when_login_returns_no_session(monkeypatch):
    """Proceeding unauthenticated would surface as a 401 on an unrelated read."""
    target = _imi_target(monkeypatch)
    client = _Client(routes={"/login": _Resp(200, {"unexpected": "shape"})})
    conn = EndpointConnection(target, client=client)
    with pytest.raises(AuthSchemeError) as ei:
        conn.get("/thinclients")
    assert "message" in str(ei.value)
    assert [c[1] for c in client.calls] == ["/login"]  # the read never happened


# ── 401 diagnosis: wrong scheme vs wrong credentials ───────────────────────


@pytest.mark.unit
def test_401_with_challenge_points_at_the_dialect_not_the_credentials(monkeypatch):
    monkeypatch.setenv("ENDPOINT_T_APIKEY", "k")
    client = _Client(
        default=_Resp(401, headers={"WWW-Authenticate": 'Basic realm="UMS"'})
    )
    conn = EndpointConnection(_target(), client=client)
    with pytest.raises(EndpointApiError) as ei:
        conn.get("/endpoints")
    message = str(ei.value)
    assert "Bearer token" in message  # what we sent
    assert "Basic" in message  # what the server asked for
    assert "dialect" in message
    assert ei.value.challenge == 'Basic realm="UMS"'
    assert ei.value.auth_scheme == "bearer"


@pytest.mark.unit
def test_401_without_challenge_says_it_cannot_tell_the_two_apart(monkeypatch):
    monkeypatch.setenv("ENDPOINT_T_APIKEY", "k")
    conn = EndpointConnection(_target(), client=_Client(default=_Resp(401)))
    with pytest.raises(EndpointApiError) as ei:
        conn.get("/endpoints")
    assert "no WWW-Authenticate" in str(ei.value)


@pytest.mark.unit
def test_challenge_parsing_ignores_parameters():
    """``realm="UMS"`` is a parameter, not a scheme; reporting it would mislead."""
    from endpoint_aiops.connection import _scheme_names

    assert _scheme_names('Basic realm="UMS", Negotiate') == ["Basic", "Negotiate"]
    assert _scheme_names("") == []


# ── probe: reachability without authenticating ─────────────────────────────


@pytest.mark.unit
def test_probe_does_not_run_the_login_handshake(monkeypatch):
    """doctor's reachability hop must not stand in for an auth check.

    On IGEL UMS the version path (/serverstatus) is the one unauthenticated
    endpoint, so a probe that logged in first would let a green tick imply
    credentials work when they were never presented.
    """
    target = _imi_target(monkeypatch)
    client = _Client(routes={"/serverstatus": _Resp(200, {"version": "12.4"})})
    conn = EndpointConnection(target, client=client)
    assert conn.probe("/serverstatus")["version"] == "12.4"
    assert [c[1] for c in client.calls] == ["/serverstatus"]  # no /login
