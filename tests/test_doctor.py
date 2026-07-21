"""Tests for ``run_doctor`` — environment and connectivity diagnostics.

Everything is redirected to a tmp dir (config, secret store) and the
connection layer is faked at the ``ConnectionManager`` boundary, so no test
ever touches a real management server or ``~/.endpoint-aiops``.
"""

from __future__ import annotations

import pytest
import yaml
from rich.console import Console

import endpoint_aiops.auth as auth
import endpoint_aiops.config as config_mod
import endpoint_aiops.connection as connection_mod
import endpoint_aiops.doctor as doctor_mod
import endpoint_aiops.secretstore as ss
from endpoint_aiops.doctor import run_doctor

MASTER_PW = "test-master-pw"


@pytest.fixture
def doctor_home(tmp_path, monkeypatch):
    """Isolate config + secret store paths under tmp_path."""
    config_file = tmp_path / "config.yaml"
    env_file = tmp_path / ".env"
    secrets_file = tmp_path / "secrets.enc"
    monkeypatch.setenv("ENDPOINT_AIOPS_HOME", str(tmp_path))
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(config_mod, "ENV_FILE", env_file)
    monkeypatch.setattr(doctor_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(doctor_mod, "ENV_FILE", env_file)
    monkeypatch.setattr(doctor_mod, "SECRETS_FILE", secrets_file)
    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", secrets_file)
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", env_file)
    monkeypatch.setattr(ss, "_cached", None)
    # Wide console so long messages don't wrap mid-assertion.
    monkeypatch.setattr(doctor_mod, "_console", Console(width=500))
    monkeypatch.delenv("ENDPOINT_FLEET1_APIKEY", raising=False)
    return tmp_path


def _write_config(tmp_path, targets: list[dict]) -> None:
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"targets": targets}), "utf-8")


def _seed_secret(monkeypatch, name: str = "fleet1", value: str = "api-key-1") -> None:
    monkeypatch.setenv("ENDPOINT_AIOPS_MASTER_PASSWORD", MASTER_PW)
    ss.SecretStore.unlock(MASTER_PW).set(name, value)


_TARGET = {"name": "fleet1", "host": "mgmt.example.com", "port": 443}


class _FakeConn:
    """Stands in for EndpointConnection across doctor's three-step check.

    ``probe`` is the un-authenticated reachability hop, ``authenticate`` the
    login handshake, ``get`` the authenticated read — doctor must exercise all
    three, so a fake that only answered ``get`` would let an auth regression
    through.
    """

    def __init__(self, target, *, endpoints=None, auth_error=None) -> None:
        self.target = target
        self.auth_strategy = auth.for_dialect(target.dialect_obj)
        self._endpoints = [{"id": "e1"}] if endpoints is None else endpoints
        self._auth_error = auth_error
        self.authenticated = False

    def probe(self, path):
        assert path == self.target.dialect_obj.version_path
        return {"version": "24.04.1"}

    def authenticate(self):
        if self._auth_error is not None:
            raise self._auth_error
        self.authenticated = True

    def get(self, path):
        assert path == self.target.dialect_obj.endpoints_path
        return self._endpoints


class _HealthyManager:
    """Stands in for ConnectionManager: every connect() succeeds."""

    def __init__(self, config) -> None:
        self._config = config

    def connect(self, name):
        return _FakeConn(self._config.get_target(name))


class _UnreachableManager:
    """Stands in for ConnectionManager: every connect() fails."""

    def __init__(self, config) -> None:
        self._config = config

    def connect(self, name):
        raise ConnectionError("HTTPS connection to 'mgmt.example.com' refused")


@pytest.mark.unit
def test_doctor_missing_config_fails_with_init_hint(doctor_home, capsys):
    assert run_doctor() == 1
    out = capsys.readouterr().out
    assert "Config file missing" in out
    assert "endpoint-aiops init" in out


@pytest.mark.unit
def test_doctor_config_load_failure_reported_not_raised(doctor_home, capsys):
    (doctor_home / "config.yaml").write_text("targets: [unclosed", "utf-8")
    assert run_doctor() == 1
    assert "Config load failed" in capsys.readouterr().out


@pytest.mark.unit
def test_doctor_no_targets_configured(doctor_home, capsys):
    _write_config(doctor_home, [])
    assert run_doctor() == 1
    assert "No targets configured" in capsys.readouterr().out


@pytest.mark.unit
def test_doctor_all_healthy_exit_zero(doctor_home, monkeypatch, capsys):
    _write_config(doctor_home, [_TARGET])
    _seed_secret(monkeypatch)
    monkeypatch.setattr(connection_mod, "ConnectionManager", _HealthyManager)
    assert run_doctor() == 0
    out = capsys.readouterr().out
    assert "Config file present" in out
    assert "1 target(s) configured" in out
    assert "Encrypted secret store present" in out
    assert "API key present for 'fleet1'" in out
    assert "Reached 'fleet1' (mgmt.example.com)" in out
    assert "management server 24.04.1" in out
    assert "Authenticated to 'fleet1'" in out


@pytest.mark.unit
def test_doctor_skip_auth_skips_connectivity(doctor_home, monkeypatch, capsys):
    _write_config(doctor_home, [_TARGET])
    _seed_secret(monkeypatch)

    def _boom(config):  # doctor must not even construct a manager
        raise AssertionError("ConnectionManager should not be used with --skip-auth")

    monkeypatch.setattr(connection_mod, "ConnectionManager", _boom)
    assert run_doctor(skip_auth=True) == 0
    out = capsys.readouterr().out
    assert "Skipping connectivity check" in out
    assert "Reached" not in out
    assert "Authenticated" not in out


@pytest.mark.unit
def test_doctor_unreachable_target_exit_one(doctor_home, monkeypatch, capsys):
    _write_config(doctor_home, [_TARGET])
    _seed_secret(monkeypatch)
    monkeypatch.setattr(connection_mod, "ConnectionManager", _UnreachableManager)
    assert run_doctor() == 1
    out = capsys.readouterr().out
    assert "could not build a connection" in out
    assert "refused" in out


@pytest.mark.unit
def test_doctor_no_secret_store_and_no_api_key(doctor_home, capsys):
    _write_config(doctor_home, [_TARGET])
    assert run_doctor(skip_auth=True) == 1
    out = capsys.readouterr().out
    assert "No secret store yet" in out
    assert "No API key for target 'fleet1'" in out


@pytest.mark.unit
def test_doctor_legacy_env_file_warns_migrate(doctor_home, monkeypatch, capsys):
    _write_config(doctor_home, [_TARGET])
    (doctor_home / ".env").write_text("ENDPOINT_FLEET1_APIKEY=legacy\n", "utf-8")
    monkeypatch.setenv("ENDPOINT_FLEET1_APIKEY", "legacy")
    assert run_doctor(skip_auth=True) == 0
    out = capsys.readouterr().out
    assert "legacy plaintext .env" in out
    assert "secret migrate" in out


@pytest.mark.unit
def test_doctor_warns_on_loose_secret_permissions(doctor_home, monkeypatch, capsys):
    _write_config(doctor_home, [_TARGET])
    _seed_secret(monkeypatch)
    (doctor_home / "secrets.enc").chmod(0o644)
    assert run_doctor(skip_auth=True) == 0
    assert "should be 600" in capsys.readouterr().out


@pytest.mark.unit
def test_cli_doctor_command_exits_with_doctor_code(doctor_home, monkeypatch):
    from typer.testing import CliRunner

    from endpoint_aiops.cli import app

    _write_config(doctor_home, [_TARGET])
    _seed_secret(monkeypatch)
    result = CliRunner().invoke(app, ["doctor", "--skip-auth"])
    assert result.exit_code == 0
    assert "Skipping connectivity check" in result.output


# ── auth is checked separately from reachability, and named precisely ───────


class _ManagerOf:
    """Stands in for ConnectionManager, yielding one prepared _FakeConn."""

    def __init__(self, conn_factory):
        self._factory = conn_factory

    def __call__(self, config):
        self._config = config
        return self

    def connect(self, name):
        return self._factory(self._config.get_target(name))


@pytest.mark.unit
def test_doctor_names_the_scheme_it_is_authenticating_with(doctor_home, monkeypatch, capsys):
    _write_config(doctor_home, [_TARGET])
    _seed_secret(monkeypatch)
    monkeypatch.setattr(connection_mod, "ConnectionManager", _HealthyManager)
    assert run_doctor() == 0
    out = capsys.readouterr().out
    assert "dialect 'generic'" in out
    assert "Bearer token" in out


@pytest.mark.unit
def test_doctor_reports_a_rejected_scheme_as_a_dialect_problem(doctor_home, monkeypatch, capsys):
    """A 401 naming a different scheme must not read as 'bad credentials'."""
    rejected = connection_mod.EndpointApiError(
        "nope", status_code=401, path="/endpoints",
        challenge='Basic realm="UMS"', auth_scheme="bearer",
    )
    _write_config(doctor_home, [_TARGET])
    _seed_secret(monkeypatch)
    monkeypatch.setattr(
        connection_mod, "ConnectionManager",
        _ManagerOf(lambda t: _FakeConn(t, auth_error=rejected)),
    )
    assert run_doctor() == 1
    out = capsys.readouterr().out
    assert "authentication rejected (401)" in out
    assert "Basic" in out                      # what the server wants
    assert "dialect is" in out and "rotating keys" in out


@pytest.mark.unit
def test_doctor_reports_an_unusable_scheme_config(doctor_home, monkeypatch, capsys):
    from endpoint_aiops.auth import AuthSchemeError

    _write_config(doctor_home, [_TARGET])
    _seed_secret(monkeypatch)
    monkeypatch.setattr(
        connection_mod, "ConnectionManager",
        _ManagerOf(lambda t: _FakeConn(t, auth_error=AuthSchemeError("needs a username"))),
    )
    assert run_doctor() == 1
    out = capsys.readouterr().out
    assert "auth scheme not usable as configured" in out
    assert "needs a username" in out


@pytest.mark.unit
def test_doctor_warns_that_an_empty_fleet_may_be_a_permissions_problem(
    doctor_home, monkeypatch, capsys
):
    """IMI returns [] rather than 403 for an under-privileged account.

    An empty list that means 'you cannot see these' must not be reported as a
    clean, empty fleet — that is the line's bug class 3 arriving from upstream.
    """
    _write_config(doctor_home, [_TARGET])
    _seed_secret(monkeypatch)
    monkeypatch.setattr(
        connection_mod, "ConnectionManager", _ManagerOf(lambda t: _FakeConn(t, endpoints=[])),
    )
    assert run_doctor() == 0  # authenticated fine; this is a warning, not a failure
    out = capsys.readouterr().out
    assert "returned no endpoints" in out
    assert "Read/Browse at the Devices level" in out


@pytest.mark.unit
def test_doctor_does_not_warn_when_endpoints_come_back(doctor_home, monkeypatch, capsys):
    _write_config(doctor_home, [_TARGET])
    _seed_secret(monkeypatch)
    monkeypatch.setattr(connection_mod, "ConnectionManager", _HealthyManager)
    assert run_doctor() == 0
    assert "returned no endpoints" not in capsys.readouterr().out
