"""Management-server dialects — adapt to a differently-shaped endpoint API.

endpoint-aiops normalises whatever a management server returns into one stable
shape. Different servers expose different **resource paths** and **field names**;
a ``Dialect`` captures both so the same tools work against any of them without
touching code — you describe the server's API in config, not in Python.

The built-in :data:`DEFAULT_DIALECT` ("generic") reproduces the out-of-the-box
behaviour exactly. A per-target ``dialect:`` block in ``config.yaml`` overrides
only the keys it names (paths and/or field aliases), so a vendor-specific mapping
is pure configuration — see the ``deploy/`` overlays for a worked example. This
package ships no vendor-specific dialect; it stays vendor-neutral.
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


@dataclass(frozen=True)
class Dialect:
    """A management server's API shape: resource paths + response field aliases."""

    name: str = "generic"
    endpoints_path: str = "/endpoints"
    endpoint_path: str = "/endpoints/{id}"
    sessions_path: str = "/sessions"
    version_path: str = "/version"
    profile_path: str = "/endpoints/{id}/profile"
    reboot_path: str = "/endpoints/{id}/reboot"
    # Envelope key a list response nests items under (e.g. "data"); None = bare array.
    list_key: str | None = None
    fields: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(_DEFAULT_FIELDS))

    def pick(self, raw: dict, field_name: str) -> Any:
        """First present value among the candidate source keys for ``field_name``."""
        for key in self.fields.get(field_name, ()):
            if isinstance(raw, dict) and key in raw and raw[key] is not None:
                return raw[key]
        return None


DEFAULT_DIALECT = Dialect()

# Only path/scalar overrides are applied wholesale; ``fields`` is merged per-field
# so an override can add aliases without dropping the defaults.
_PATH_KEYS = ("name", "endpoints_path", "endpoint_path", "sessions_path",
              "version_path", "profile_path", "reboot_path", "list_key")


def resolve(spec: dict | None) -> Dialect:
    """Build a Dialect from a config ``dialect:`` block, over the generic default.

    ``spec`` may set any path key and/or a ``fields`` map. For ``fields``, each
    named field's candidate list REPLACES that field's default (a server that
    renames a field states its own key); unnamed fields keep their defaults.
    """
    if not spec:
        return DEFAULT_DIALECT
    changes: dict[str, Any] = {k: spec[k] for k in _PATH_KEYS if k in spec}
    fields_override = spec.get("fields")
    if isinstance(fields_override, dict):
        merged = dict(_DEFAULT_FIELDS)
        for name, keys in fields_override.items():
            if isinstance(keys, (list, tuple)) and keys:
                merged[name] = tuple(str(k) for k in keys)
            elif isinstance(keys, str) and keys:
                merged[name] = (keys,)
        changes["fields"] = merged
    return replace(DEFAULT_DIALECT, **changes)


__all__ = ["Dialect", "DEFAULT_DIALECT", "resolve"]
