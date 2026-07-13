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
from endpoint_aiops.secretstore import SecretStoreError, get_secret, has_store

if TYPE_CHECKING:
    from endpoint_aiops.dialect import Dialect

CONFIG_DIR = ops_home()
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

DEFAULT_API_PATH = "/api/v2.0"

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
        except SecretStoreError:
            pass  # fall through to legacy env var
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
    never the config file. ``host`` is the management server; ``port`` defaults to
    the HTTPS port 443; ``api_path`` is the REST base path (``/api/v2.0``).
    """

    name: str
    host: str
    port: int = 443
    verify_ssl: bool = True
    api_path: str = DEFAULT_API_PATH
    # Optional per-target management-server dialect (resource paths + field
    # aliases). None = the built-in generic shape. See endpoint_aiops.dialect.
    dialect: dict | None = None

    @property
    def api_key(self) -> str:
        return _resolve_secret(self.name)

    @property
    def base_url(self) -> str:
        return f"https://{self.host}:{self.port}{self.api_path}"

    @property
    def dialect_obj(self) -> Dialect:
        """Resolved Dialect for this target (generic default when unset)."""
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
            port=t.get("port", 443),
            verify_ssl=t.get("verify_ssl", True),
            api_path=t.get("api_path", DEFAULT_API_PATH),
            dialect=t.get("dialect"),
        )
        for t in raw.get("targets", [])
    )

    return AppConfig(targets=targets)
