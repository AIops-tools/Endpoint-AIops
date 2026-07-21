"""Configuration management for Endpoint AIops.

Loads connection targets and settings from a YAML config file. The secret (the
Endpoint API key / Bearer token) is NEVER stored in the config file and never on
disk in plaintext: it lives in the encrypted store
``~/.endpoint-aiops/secrets.enc`` (see :mod:`endpoint_aiops.secretstore`). For
backward compatibility a legacy plaintext env var (``ENDPOINT_<TARGET>_APIKEY``)
is still honoured as a fallback, with a warning nudging migration to the
encrypted store.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from endpoint_aiops.governance.paths import ops_home
from endpoint_aiops.secretstore import (
    MasterPasswordError,
    SecretStoreError,
    get_secret,
    has_store,
)

if TYPE_CHECKING:
    from endpoint_aiops.dialect import Dialect

CONFIG_DIR = ops_home()
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

# NOTE: there is deliberately no module-level DEFAULT_API_PATH here any more.
# A fixed "/api/v2.0" default was the bug: it is a shape no shipped management
# server serves, and it silently overrode the API base path of any dialect that
# knew better (IGEL UMS serves IMI at /umsapi/v3 on 8443). The per-dialect
# ``Dialect.default_api_path`` is the single source of that default now — keep
# it that way rather than reintroducing a constant that outranks the dialect.

# Legacy env-var prefix/suffix; also used by the migration helper.
SECRET_ENV_PREFIX = "ENDPOINT_"  # nosec B105 — env-var name, not a secret
SECRET_ENV_SUFFIX = "_APIKEY"  # nosec B105 — env-var name, not a secret

_log = logging.getLogger("endpoint-aiops.config")


def _secret_env_key(name: str) -> str:
    """Legacy per-target API-key env var name, e.g. ENDPOINT_NAS1_APIKEY."""
    return f"{SECRET_ENV_PREFIX}{name.upper().replace('-', '_')}{SECRET_ENV_SUFFIX}"


def _resolve_secret(name: str) -> str:
    """Return a target's API key: encrypted store first, then legacy env var."""
    if has_store():
        try:
            return get_secret(name)
        except MasterPasswordError:
            # A wrong or missing master password is NOT "this target has no
            # secret". Falling through resurfaced it as "No API key for target
            # X", sending the operator to add a credential that is already
            # there. MasterPasswordError subclasses SecretStoreError, so the
            # broad catch below would swallow it — re-raise first.
            raise
        except SecretStoreError:
            pass  # no secret stored for this target — try the legacy env var
    legacy = os.environ.get(_secret_env_key(name))
    if legacy:
        _log.warning(
            "Using plaintext env var %s. Migrate to the encrypted store with "
            "'endpoint-aiops secret migrate'.",
            _secret_env_key(name),
        )
        return legacy
    raise OSError(
        f"No API key for target '{name}'. Add one with "
        f"'endpoint-aiops secret set {name}' (stored encrypted), or run "
        f"'endpoint-aiops init'."
    )


@dataclass(frozen=True)
class TargetConfig:
    """A connection target for an endpoint-management REST API.

    The API key is sourced from the encrypted secret store (see ``api_key``),
    never the config file. ``host`` is the management server. ``port`` and
    ``api_path`` default to **the dialect's** transport defaults rather than a
    fixed 443 + ``/api/v2.0``: a preset such as ``igel-ums`` serves IMI at
    ``/umsapi/v3`` on 8443, and hardcoding the generic pair meant selecting that
    server still produced a 404 on the first probe.
    """

    name: str
    host: str
    port: int = 0
    verify_ssl: bool = True
    api_path: str = ""
    scheme: str = "https"
    """Transport scheme — ``https`` (default) or ``http``.

    Defaults to ``https``, so nothing changes for an existing config. It exists
    because a self-hosted management server often sits on plain HTTP behind a
    reverse proxy, and the URL was previously hardcoded to ``https://`` with no
    way to override it — which made such an instance simply unreachable, with a
    TLS record-layer error as the only clue.
    """

    username: str = ""
    """Account name for dialects that log in with HTTP Basic (e.g. ``igel-ums``).

    Not a secret and therefore in the config file, with the password in the
    encrypted store — the same split Proxy-AIops uses for the HAProxy Data
    Plane API. Unused by the ``bearer`` scheme, where the API key alone is the
    whole credential.
    """

    # Per-target management-server dialect: a preset name (``"igel-ums"``) or a
    # dict of resource paths + field aliases, optionally naming a ``preset``.
    # None = the built-in generic placeholder. See endpoint_aiops.dialect.
    dialect: dict | str | None = None

    def __post_init__(self) -> None:
        if self.scheme not in ("https", "http"):
            raise ValueError(
                f"Target '{self.name}': scheme must be 'https' or 'http', "
                f"got '{self.scheme}'."
            )
        dialect = self.dialect_obj
        if not self.port:
            object.__setattr__(self, "port", dialect.default_port)
        if not self.api_path:
            object.__setattr__(self, "api_path", dialect.default_api_path)

    @property
    def api_key(self) -> str:
        return _resolve_secret(self.name)

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}{self.api_path}"

    @property
    def dialect_obj(self) -> Dialect:
        """Resolved Dialect for this target (generic placeholder when unset)."""
        from endpoint_aiops.dialect import resolve

        return resolve(self.dialect)


@dataclass(frozen=True)
class AppConfig:
    """Top-level application config."""

    targets: tuple[TargetConfig, ...] = ()

    def get_target(self, name: str) -> TargetConfig:
        for t in self.targets:
            if t.name == name:
                return t
        available = ", ".join(t.name for t in self.targets) or "(none)"
        raise KeyError(f"Target '{name}' not found. Available: {available}")

    @property
    def default_target(self) -> TargetConfig:
        if not self.targets:
            raise ValueError("No targets configured. Check config.yaml")
        return self.targets[0]


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load config from YAML; the API key comes from the encrypted store."""
    path = config_path or CONFIG_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Run 'endpoint-aiops init' to set up a target and store its API key "
            f"encrypted, or create {CONFIG_FILE} with a 'targets' list."
        )

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    targets = tuple(
        TargetConfig(
            name=t["name"],
            host=t["host"],
            # 0 / "" mean "unset" — __post_init__ fills them from the dialect, so
            # a preset's own port and API base path are not silently overwritten.
            port=t.get("port", 0),
            verify_ssl=t.get("verify_ssl", True),
            api_path=t.get("api_path", ""),
            scheme=t.get("scheme", "https"),
            username=t.get("username", ""),
            dialect=t.get("dialect"),
        )
        for t in raw.get("targets", [])
    )

    return AppConfig(targets=targets)
