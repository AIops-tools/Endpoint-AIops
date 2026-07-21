"""Connection management for an endpoint-management REST API.

Thin httpx wrapper with per-target session reuse. **Authentication is chosen by
the target's dialect**, not hardcoded here — see :mod:`endpoint_aiops.auth`:

  * ``bearer`` (generic default) — the server issues a long-lived **API key**
    in its web UI and every request carries ``Authorization: Bearer <api_key>``.
    No token-exchange handshake, so the key is sent directly.
  * ``imi-session`` (IGEL UMS) — an HTTP Basic login yielding a session that
    later requests present. Performed once per connection and cached.

  ``base_url`` already includes the API base path, so callers pass resource
  paths like ``/endpoints`` or ``/sessions``.

A 401/403 is translated into a message that distinguishes **wrong scheme** from
**wrong credentials** (using the server's ``WWW-Authenticate`` challenge when it
sends one). Those have different fixes, and a dialect whose scheme does not match
the server fails every request — reporting that as "check your API key" sends the
operator to rotate a key that was never the problem.

All non-2xx responses are translated centrally into ``EndpointApiError`` with a
teaching message — REST-wrapper skills translate HTTP errors at the connection
layer from the first version rather than leaking raw tracebacks.

The httpx client is injectable for tests: pass ``client=`` to
``EndpointConnection`` to substitute a mock that implements ``request`` / ``close``.
"""

from __future__ import annotations

from typing import Any

import httpx

from endpoint_aiops import auth
from endpoint_aiops.config import AppConfig, TargetConfig, load_config

_TIMEOUT = 30.0


class EndpointApiError(Exception):
    """An endpoint-management REST API call failed; carries a teaching message + status code."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        path: str = "",
        challenge: str = "",
        auth_scheme: str = "",
    ) -> None:
        self.status_code = status_code
        self.path = path
        #: The server's ``WWW-Authenticate`` header, when it sent one. Retained
        #: so a caller (doctor) can tell "wrong credentials" from "wrong scheme".
        self.challenge = challenge
        #: Name of the auth strategy that was used for the failed request.
        self.auth_scheme = auth_scheme
        super().__init__(message)


def _challenge_of(resp: Any) -> str:
    """The response's ``WWW-Authenticate`` header, tolerating header-less doubles.

    The injectable-client contract only promises ``request`` / ``close``, so a
    test double or a minimal transport need not expose ``headers``. A missing
    header is simply "the server did not tell us", which the message layer
    already handles — it must not turn into an AttributeError on the error path.
    """
    headers = getattr(resp, "headers", None)
    if headers is None:
        return ""
    try:
        return headers.get("WWW-Authenticate", "") or ""
    except Exception:  # noqa: BLE001 — an exotic mapping must not break error reporting
        return ""


def _scheme_names(challenge: str) -> list[str]:
    """Auth scheme tokens advertised in a ``WWW-Authenticate`` header.

    ``Basic realm="UMS", Negotiate`` → ``["Basic", "Negotiate"]``. Only the
    leading token of each comma-separated challenge is a scheme name; the rest
    are parameters, so a naive split would report ``realm="UMS"`` as a scheme.
    """
    names = []
    for part in challenge.split(","):
        token = part.strip().split(" ", 1)[0].strip()
        if token and "=" not in token:
            names.append(token)
    return names


def _auth_failure_message(
    status: int, path: str, snippet: str, auth_label: str, challenge: str
) -> str:
    """Explain a 401/403, distinguishing a wrong scheme from wrong credentials.

    These are different problems with different fixes and must not read alike.
    A dialect whose auth scheme does not match the server rejects *every*
    request, and phrasing that as "check your credentials" sends the operator
    to rotate a perfectly good API key. When the server tells us what it wants
    (``WWW-Authenticate``) and that disagrees with what we sent, say so plainly.
    """
    wanted = _scheme_names(challenge)
    offered = ", ".join(wanted)
    base = (
        f"Authentication failed ({status}) on {path}. This target is "
        f"authenticating with {auth_label}."
    )
    if wanted:
        return (
            f"{base} The server answered with 'WWW-Authenticate: {challenge.strip()}', "
            f"so it is asking for {offered}. If that disagrees with the scheme above, the "
            f"credentials are not the problem — the target's dialect is: a dialect selects "
            f"the auth scheme, so set 'dialect:' to one whose scheme the server accepts "
            f"(igel-ums logs in with HTTP Basic; the generic default sends a Bearer token) "
            f"before rotating any keys. {snippet}"
        )
    return (
        f"{base} The server sent no WWW-Authenticate header, so it did not say which "
        f"scheme it wants and this cannot tell a wrong scheme from wrong credentials. "
        f"Check both: that the secret is valid and the account is permitted, AND that "
        f"the target's 'dialect:' matches the product — a dialect selects the auth "
        f"scheme, and the wrong one is rejected on every request. {snippet}"
    )


def _teaching_message(
    status: int, path: str, body: str, auth_label: str = "", challenge: str = ""
) -> str:
    """Map a non-2xx status to an actionable, teaching error message."""
    snippet = body[:200].strip()
    if status in (401, 403):
        return _auth_failure_message(
            status, path, snippet, auth_label or "an unnamed scheme", challenge
        )
    if status == 404:
        return (
            f"Resource not found (404) on {path}. The id may be stale — list the "
            f"parent collection first to get a current id. {snippet}"
        )
    if status == 422:
        return (
            f"Validation error (422) on {path}. Endpoint rejected the request body "
            f"— check required fields and value formats. {snippet}"
        )
    if status in (500, 502, 503, 504):
        return (
            f"Endpoint server error ({status}) on {path}. The middleware may be "
            f"busy or restarting; retry shortly. {snippet}"
        )
    return f"Endpoint API error ({status}) on {path}. {snippet}"


class EndpointConnection:
    """A single authenticated session against one endpoint-management REST API target.

    Authentication is delegated to the target dialect's strategy
    (:func:`endpoint_aiops.auth.for_dialect`) — this class knows *that* there is
    a scheme, never *which*. A scheme needing a login handshake performs it
    lazily on the first real request and the resulting headers are cached for
    the connection's lifetime, the same shape Proxy-AIops uses to cache its
    probed Data Plane API generation: a static-token scheme costs no extra
    request, a session scheme costs exactly one per connection.
    """

    def __init__(self, target: TargetConfig, client: Any | None = None) -> None:
        self._target = target
        self._auth = auth.for_dialect(target.dialect_obj)
        self._client = client or httpx.Client(
            base_url=target.base_url,
            verify=target.verify_ssl,
            timeout=_TIMEOUT,
            headers={
                **self._auth.static_headers(target),
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        # Headers from the auth handshake; None = not attempted yet. Probed once
        # and cached, never re-sent through _ensure_session on every call.
        self._session_headers: dict[str, str] | None = None

    @property
    def target(self) -> TargetConfig:
        return self._target

    @property
    def auth_strategy(self) -> Any:
        """The dialect's auth strategy — used by ``doctor`` to name the scheme."""
        return self._auth

    def _ensure_session(self) -> dict[str, str]:
        """Run the dialect's login handshake once; cache it for this connection."""
        if self._session_headers is None:
            self._session_headers = dict(self._auth.authenticate(self._send, self._target))
        return self._session_headers

    def _send(self, method: str, path: str, **kwargs: Any) -> Any:
        """Transport without the session layer — the handshake itself uses this."""
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise EndpointApiError(
                f"Could not reach the management server at {self._target.base_url} "
                f"({method} {path}): {exc}. Check the host/port and that the "
                f"management REST API is reachable.",
                path=path,
            ) from exc
        if not (200 <= resp.status_code < 300):
            challenge = _challenge_of(resp)
            raise EndpointApiError(
                _teaching_message(
                    resp.status_code, path, resp.text,
                    auth_label=self._auth.label,
                    challenge=challenge,
                ),
                status_code=resp.status_code,
                path=path,
                challenge=challenge,
                auth_scheme=self._auth.name,
            )
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Issue a request and return parsed JSON, translating errors centrally."""
        session = self._ensure_session()
        if session:
            kwargs["headers"] = {**session, **(kwargs.get("headers") or {})}
        return self._send(method, path, **kwargs)

    def probe(self, path: str) -> Any:
        """GET ``path`` **without** running the dialect's login handshake.

        Exists so ``doctor`` can separate "the server is reachable" from "we can
        authenticate to it" — two failures with completely different fixes. It
        matters most on IGEL UMS, whose version path (``/serverstatus``) is its
        one unauthenticated endpoint: reaching it proves the host answers and
        proves nothing at all about credentials. Going through the normal path
        would log in first and let a green reachability check quietly stand in
        for an auth check that never ran.
        """
        return self._send("GET", path)

    def authenticate(self) -> None:
        """Run the dialect's login handshake now. Idempotent (cached per connection)."""
        self._ensure_session()

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    def close(self) -> None:
        self._client.close()


class ConnectionManager:
    """Manages connections to multiple Endpoint targets with session reuse."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._connections: dict[str, EndpointConnection] = {}

    @classmethod
    def from_config(cls, config: AppConfig | None = None) -> ConnectionManager:
        cfg = config or load_config()
        return cls(cfg)

    def connect(self, target_name: str | None = None) -> EndpointConnection:
        """Connect to a target by name, or the default target."""
        target = (
            self._config.get_target(target_name)
            if target_name
            else self._config.default_target
        )
        cached = self._connections.get(target.name)
        if cached is not None:
            return cached
        conn = EndpointConnection(target)
        self._connections[target.name] = conn
        return conn

    def disconnect(self, target_name: str) -> None:
        conn = self._connections.pop(target_name, None)
        if conn is not None:
            conn.close()

    def disconnect_all(self) -> None:
        for name in list(self._connections):
            self.disconnect(name)

    def list_targets(self) -> list[str]:
        return [t.name for t in self._config.targets]

    def list_connected(self) -> list[str]:
        return list(self._connections.keys())
