"""Management-server dialects — adapt to a differently-shaped endpoint API.

endpoint-aiops normalises whatever a management server returns into one stable
shape. Different servers expose different **resource paths** and **field names**;
a ``Dialect`` captures both so the same tools work against any of them without
touching code — you describe the server's API in config, not in Python.

The built-in :data:`DEFAULT_DIALECT` ("generic") is a **neutral placeholder**, not
a real vendor's API: ``/endpoints`` on port 443 under ``/api/v2.0`` is a shape no
shipped management server actually serves. It exists so the ops layer has a
default, and it is only useful once you describe your server in a ``dialect:``
block. Configuring a target and leaving the dialect alone will not reach IGEL UMS
or anything else — the first probe 404s.

Because of that, dialects can also be selected **by name** from :data:`PRESETS`
(``dialect: igel-ums`` in ``config.yaml``), and a preset carries its transport
defaults (``default_port`` / ``default_api_path``) alongside its paths, so
selecting it fixes the port and API base path too. A dict form still works and
may name a ``preset:`` to layer overrides onto.

A path set to ``None`` means the server genuinely has **no such resource**.
Asking for it raises :class:`UnsupportedResource` — a teaching error — rather
than a request to a made-up URL. That distinction is the whole point: this file
previously encouraged guessing a path for every resource, and a guessed path is
indistinguishable from a real one until it 404s in production.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

# Normalised field → the candidate source keys to try, in order. The defaults
# match the built-in fallbacks the ops layer used before dialects existed.
_DEFAULT_FIELDS: dict[str, tuple[str, ...]] = {
    # inventory
    "id": ("id", "uuid", "mac"),
    "hostname": ("hostname", "name"),
    "os": ("os", "platform"),
    "osBuild": ("os_build", "build", "firmware"),
    "agentVersion": ("agent_version", "agent"),
    "patchLevel": ("patch_level", "patch"),
    "profileId": ("profile_id", "profile"),
    "online": ("online", "connected"),
    "lastSeenHours": ("last_seen_hours", "idle_hours"),
    # sessions
    "sessionEndpoint": ("endpoint_id", "hostname", "endpoint"),
    "user": ("user", "username"),
    "loginMs": ("login_ms", "login_duration_ms"),
    "bootMs": ("boot_ms", "boot_duration_ms"),
    "timestamp": ("timestamp", "ts"),
    "result": ("result", "status"),
}


class UnsupportedResource(KeyError):  # noqa: N818 — teaching error, reads as a statement
    """A resource this management server genuinely does not expose.

    Subclasses ``KeyError`` so existing ``except KeyError`` handlers keep
    working, but is distinguishable — a bare ``KeyError`` here would be
    reported by the CLI as "Missing required key or environment variable",
    sending the operator to hunt a config problem that does not exist. The
    real cause (this server has no such resource) would be buried in the detail.
    """


@dataclass(frozen=True)
class Dialect:
    """A management server's API shape: transport defaults, paths, field aliases.

    A path of ``None`` means the server has no such resource; :meth:`path_for`
    raises :class:`UnsupportedResource` instead of inventing a URL for it.
    """

    name: str = "generic"
    # Transport defaults a target inherits when it does not state its own.
    default_port: int = 443
    default_api_path: str = "/api/v2.0"
    endpoints_path: str | None = "/endpoints"
    endpoint_path: str | None = "/endpoints/{id}"
    sessions_path: str | None = "/sessions"
    version_path: str | None = "/version"
    profile_path: str | None = "/endpoints/{id}/profile"
    reboot_path: str | None = "/endpoints/{id}/reboot"
    # Envelope key a list response nests items under (e.g. "data"); None = bare array.
    list_key: str | None = None
    fields: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(_DEFAULT_FIELDS))

    def pick(self, raw: dict, field_name: str) -> Any:
        """First present value among the candidate source keys for ``field_name``."""
        for key in self.fields.get(field_name, ()):
            if isinstance(raw, dict) and key in raw and raw[key] is not None:
                return raw[key]
        return None

    def path_for(self, resource: str) -> str:
        """The path for ``resource``, or raise if this dialect does not expose it.

        ``resource`` is the attribute stem — ``"endpoints"``, ``"sessions"``,
        ``"version"``, ``"profile"``, ``"reboot"``, ``"endpoint"``.
        """
        path = getattr(self, f"{resource}_path", None)
        if path:
            return path
        raise UnsupportedResource(
            f"The '{self.name}' management server does not expose a "
            f"'{resource}' resource, so there is no endpoint to call. This is a "
            f"property of the server's API, not a configuration mistake — do not "
            f"go looking for a missing config key. If your server does expose one, "
            f"set '{resource}_path' in the target's dialect: block in config.yaml."
        )


DEFAULT_DIALECT = Dialect()

# IGEL Universal Management Suite, via its IGEL Management Interface (IMI) REST
# API. IMI is served at ``/umsapi/v3`` on port **8443** — NOT the generic
# ``/api/v2.0`` on 443, which is why an operator who configured a target and
# left the dialect alone got a 404 on the very first probe.
#
# ⚠️ MODELLED FROM IGEL'S PUBLISHED IMI DOCUMENTATION — NOT LIVE-VERIFIED.
# IGEL UMS has no free edition, so this preset has never been run against a real
# server. Paths marked below are the least certain. See docs/VERIFICATION.md,
# where this is recorded as UNKNOWN-pending-live rather than as known-good.
#
# ⚠️ AUTH: IMI uses HTTP Basic / a message-auth handshake, NOT the static Bearer
# token this tool sends. A live integration needs an auth adapter or a gateway
# that presents Bearer. The dialect maps paths and fields only.
IGEL_UMS_DIALECT = Dialect(
    name="igel-ums",
    default_port=8443,
    default_api_path="/umsapi/v3",
    endpoints_path="/thinclients",
    endpoint_path="/thinclients/{id}",
    # IMI exposes no login/boot session resource. None (not a guessed path) so
    # the login-storm tools say so instead of 404ing against an invented URL.
    sessions_path=None,
    version_path="/serverstatus",
    profile_path="/thinclients/{id}/profile",              # least certain
    reboot_path="/thinclients/{id}/commands/reboot",       # least certain
    list_key=None,  # IMI returns a bare array
    fields={**_DEFAULT_FIELDS,
            "id": ("id", "unitID", "mac"),
            "hostname": ("name", "unitName"),
            "os": ("productId", "firmwareType"),
            "osBuild": ("firmwareVersion", "firmware"),
            "agentVersion": ("agentVersion",),
            "patchLevel": ("patchLevel", "firmwareVersion"),
            "profileId": ("profileId", "configId"),
            "online": ("online", "connected"),
            "lastSeenHours": ("lastContactHours",)},
)

#: Dialects selectable by name from ``config.yaml`` (``dialect: igel-ums``).
PRESETS: dict[str, Dialect] = {
    "generic": DEFAULT_DIALECT,
    "igel-ums": IGEL_UMS_DIALECT,
}

# Only path/scalar overrides are applied wholesale; ``fields`` is merged per-field
# so an override can add aliases without dropping the defaults.
_PATH_KEYS = ("name", "default_port", "default_api_path", "endpoints_path",
              "endpoint_path", "sessions_path", "version_path", "profile_path",
              "reboot_path", "list_key")


def _base_for(spec: dict | str | None) -> Dialect:
    """The preset a spec layers on top of; the generic default when unnamed."""
    preset = spec if isinstance(spec, str) else (spec or {}).get("preset")
    if preset is None:
        return DEFAULT_DIALECT
    try:
        return PRESETS[str(preset)]
    except KeyError:
        raise UnsupportedResource(
            f"No built-in dialect preset named '{preset}'. Available: "
            f"{', '.join(sorted(PRESETS))}. Either pick one of those, or drop "
            f"'preset' and describe the server's paths directly in the dialect: "
            f"block."
        ) from None


def resolve(spec: dict | str | None) -> Dialect:
    """Build a Dialect from a config ``dialect:`` block or a preset name.

    ``spec`` may be a preset name (``"igel-ums"``), or a dict that sets any path
    key and/or a ``fields`` map, optionally naming a ``preset:`` to layer onto.
    For ``fields``, each named field's candidate list REPLACES that field's
    default (a server that renames a field states its own key); unnamed fields
    keep the base dialect's.
    """
    if not spec:
        return DEFAULT_DIALECT
    base = _base_for(spec)
    if isinstance(spec, str):
        return base
    changes: dict[str, Any] = {k: spec[k] for k in _PATH_KEYS if k in spec}
    fields_override = spec.get("fields")
    if isinstance(fields_override, dict):
        merged = dict(base.fields)
        for name, keys in fields_override.items():
            if isinstance(keys, (list, tuple)) and keys:
                merged[name] = tuple(str(k) for k in keys)
            elif isinstance(keys, str) and keys:
                merged[name] = (keys,)
        changes["fields"] = merged
    return replace(base, **changes)


__all__ = ["Dialect", "DEFAULT_DIALECT", "IGEL_UMS_DIALECT", "PRESETS",
           "UnsupportedResource", "resolve"]
