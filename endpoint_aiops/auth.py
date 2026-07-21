"""Per-dialect authentication strategies.

A management server's **authentication scheme is part of its API shape**, in
exactly the way its resource paths are. So it is selected by the dialect
(:attr:`endpoint_aiops.dialect.Dialect.auth`) and resolved through this
registry — not by an ``if platform == ...`` branch inside the connection layer.
Adding a server that authenticates differently means adding a strategy here and
naming it from a dialect; the connection layer does not change.

Two strategies ship:

  * :class:`BearerAuth` (``"bearer"``) — a static long-lived API key sent as
    ``Authorization: Bearer <key>`` on every request. No handshake. This is the
    generic default and what the tool has always done.
  * :class:`ImiSessionAuth` (``"imi-session"``) — IGEL UMS's IGEL Management
    Interface: HTTP Basic on a ``POST /login``, which returns a ``JSESSIONID``
    that subsequent requests present as a cookie. Documented in IGEL's IMI
    manual and corroborated by real clients, but never run against an appliance
    by this project — see that class's provenance note.

A strategy has two phases so that a scheme needing a round-trip stays lazy:

  ``static_headers()``  applied to every request, no I/O — enough on its own for
                        a static-token scheme.
  ``authenticate()``    an optional login handshake, performed **at most once per
                        connection** and cached for the connection's lifetime
                        (see ``EndpointConnection._session_headers``, which
                        mirrors how Proxy-AIops caches its probed Data Plane API
                        generation). A strategy that needs no handshake returns
                        an empty mapping and costs nothing.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from typing import Any

#: A strategy performs its handshake through this: ``send(method, path, **kw)``
#: returns the parsed body and raises the connection layer's error type on
#: failure. Injecting it keeps strategies free of httpx and trivially testable.
Sender = Callable[..., Any]


class AuthSchemeError(Exception):
    """The configured auth scheme cannot be used as set up.

    A dedicated class because the alternative reads as the wrong problem: a
    missing Basic-auth username surfaced as a bare ``KeyError``/``ValueError``
    is rendered by the CLI as "Missing required key or environment variable",
    which sends the operator to hunt a config-file typo. The real cause is that
    this dialect authenticates differently than the one they configured for.
    """


class AuthStrategy:
    """How one family of management server expects to be authenticated."""

    #: Registry key, named by ``Dialect.auth``.
    name = "none"
    #: Human phrase for diagnostics: "this target is authenticating with {label}".
    label = "no authentication"
    #: What a server wanting this scheme looks like on the wire, for doctor.
    challenge_hint = ""

    def static_headers(self, target: Any) -> dict[str, str]:
        """Headers applied to every request. Must not perform I/O."""
        return {}

    def authenticate(self, send: Sender, target: Any) -> dict[str, str]:
        """Optional login handshake. Returns extra headers; may perform I/O.

        Called lazily, at most once per connection. The default is "no
        handshake needed".
        """
        return {}


class BearerAuth(AuthStrategy):
    """Static long-lived API key in ``Authorization: Bearer <key>``.

    The server issues the key in its web UI and it is sent directly — there is
    no token exchange, so nothing to cache and no extra round-trip.
    """

    name = "bearer"
    label = "a static Bearer token (Authorization: Bearer <api key>)"
    challenge_hint = "Bearer"

    def static_headers(self, target: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {target.api_key}"}


def _basic(username: str, password: str) -> str:
    """RFC 7617 ``Basic`` credentials."""
    raw = f"{username}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


class ImiSessionAuth(AuthStrategy):
    """IGEL UMS IMI: HTTP Basic on a login call, then a ``JSESSIONID`` cookie.

    **Provenance — read this before trusting it.** The scheme below is taken
    from IGEL's official *IGEL Management Interface* manual and is independently
    corroborated by three real-world clients (IGEL Community's PSIGEL
    ``New-UMSAPICookie``, the community curl HOWTO, and ControlUp's UMS script).
    That is a much stronger basis than the paths in this dialect, which are only
    doc-modelled. It is still **not live-verified by this project**: IGEL UMS has
    no free edition, so nothing here has been observed on the wire by us. Read it
    as "documented and corroborated, never executed" — see docs/VERIFICATION.md.

    The flow, all confirmed in the manual:

      * ``POST {api_path}/login`` with HTTP **Basic** credentials and no body.
      * The response returns the session id twice — as a ``Set-Cookie:
        JSESSIONID=...`` and in the JSON body as ``{"message": "JSESSIONID=..."}``.
        This reads the body field, because a caller-supplied transport is not
        required to expose response headers.
      * Subsequent requests present ``Cookie: JSESSIONID=<id>``. Basic is not
        re-sent. The session has a 30-minute *sliding* expiry, so a connection
        making regular calls keeps it alive; see :meth:`authenticate` on what
        happens when it does lapse.

    Note the ``message`` value already contains the literal ``JSESSIONID=``
    prefix — it is a complete ``name=value`` pair, not a bare id. Prefixing it
    again yields ``Cookie: JSESSIONID=JSESSIONID=...``, which is exactly why
    PSIGEL splits the value on ``=`` and the curl HOWTO cuts 12 characters.
    :func:`_session_cookie` handles both spellings rather than assuming one.
    """

    name = "imi-session"
    label = "an IMI session (HTTP Basic login, then a JSESSIONID cookie)"
    challenge_hint = "Basic"

    #: Login path, relative to the target's api_path (``/umsapi/v3``).
    login_path = "/login"
    #: JSON field carrying the session id. The manual documents exactly one.
    session_key = "message"
    #: Cookie name IMI's session id is presented under.
    cookie_name = "JSESSIONID"

    def static_headers(self, target: Any) -> dict[str, str]:
        """No static credential: the session comes from :meth:`authenticate`.

        Deliberately does *not* fall back to a Bearer token. A wrong scheme that
        half-works is harder to diagnose than one that fails at the login call
        with a message naming the scheme.
        """
        return {}

    def _credentials(self, target: Any) -> str:
        username = getattr(target, "username", "") or ""
        if not username:
            raise AuthSchemeError(
                f"Target '{target.name}' uses the '{self.name}' auth scheme, which logs in "
                f"with HTTP Basic and therefore needs a username as well as a secret — but "
                f"no 'username' is set on the target. IMI authenticates as a UMS "
                f"administrator account, not with an API key. Add 'username: <ums-admin>' "
                f"to this target in config.yaml; the password stays in the encrypted store "
                f"('endpoint-aiops secret set {target.name}'). The account needs at least "
                f"Read/Browse permission at the Devices level — with too few permissions "
                f"IMI returns empty lists rather than an error."
            )
        return _basic(username, target.api_key)

    def authenticate(self, send: Sender, target: Any) -> dict[str, str]:
        """Log in once and return the session header for the connection's life.

        The session is cached by the connection, and IMI's 30-minute expiry is
        sliding, so an idle connection can outlive its session. That surfaces as
        a 401 on a later read rather than here — the 401 message names the
        scheme in use, which is what points at this rather than at credentials.
        Re-connecting starts a fresh session.
        """
        body = send(
            "POST",
            self.login_path,
            headers={"Authorization": self._credentials(target)},
        )
        cookie = _session_cookie(body, self.session_key, self.cookie_name)
        if not cookie:
            raise AuthSchemeError(
                f"Logged in to '{target.name}' at {self.login_path} but the response "
                f"carried no '{self.session_key}' field holding a {self.cookie_name}. "
                f"Refusing to continue unauthenticated — doing so would surface as a "
                f"confusing 401 on some later read instead of here. If your UMS returns a "
                f"different shape, please report it as an issue with the actual response."
            )
        return {"Cookie": cookie}


def _session_cookie(body: Any, session_key: str, cookie_name: str) -> str:
    """Build the ``Cookie`` value from IMI's login body, tolerating both spellings.

    IMI documents ``{"message": "JSESSIONID=<hex>"}`` — already a complete
    ``name=value`` pair. Passing that through a naive ``f"{name}={value}"``
    double-prefixes it. Accepts a bare id too, so a server returning just the
    hex still works.
    """
    if not isinstance(body, Mapping):
        return ""
    value = body.get(session_key)
    if not isinstance(value, str) or not value.strip():
        return ""
    value = value.strip()
    if value.startswith(f"{cookie_name}="):
        return value
    return f"{cookie_name}={value}"


#: Auth strategies selectable by a dialect's ``auth`` field.
STRATEGIES: dict[str, AuthStrategy] = {
    BearerAuth.name: BearerAuth(),
    ImiSessionAuth.name: ImiSessionAuth(),
}


def for_dialect(dialect: Any) -> AuthStrategy:
    """The auth strategy a dialect declares, or raise naming the valid ones."""
    name = getattr(dialect, "auth", BearerAuth.name)
    try:
        return STRATEGIES[name]
    except KeyError:
        raise AuthSchemeError(
            f"Dialect '{getattr(dialect, 'name', '?')}' names auth scheme '{name}', which "
            f"is not implemented. Available: {', '.join(sorted(STRATEGIES))}."
        ) from None


__all__ = [
    "AuthSchemeError",
    "AuthStrategy",
    "BearerAuth",
    "ImiSessionAuth",
    "STRATEGIES",
    "for_dialect",
]
