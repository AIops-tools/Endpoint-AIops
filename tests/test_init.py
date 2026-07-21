"""Tests for the ``endpoint-aiops init`` onboarding wizard.

The wizard is driven end-to-end through Typer's CliRunner with every path
(config.yaml, secrets.enc) isolated under tmp_path. The master
password comes from ENDPOINT_AIOPS_MASTER_PASSWORD (the non-interactive path)
and the hidden API-key prompt is patched at the getpass boundary.
"""

from __future__ import annotations

import getpass as getpass_mod

import pytest
import yaml
from typer.testing import CliRunner

import endpoint_aiops.cli.init as init_mod
import endpoint_aiops.config as config_mod
import endpoint_aiops.doctor as doctor_mod
import endpoint_aiops.secretstore as ss

MASTER_PW = "init-master-pw"
API_KEY = "endpoint-api-key-0123"

# Wizard answers: name, host, accept default dialect (generic), accept default
# scheme (https), accept default port, accept TLS-verify default (True), no
# second target, decline the trailing doctor run.
WIZARD_INPUT = "fleet1\nmgmt.example.com\n\n\n\n\nn\nn\n"

# Same, but choosing the igel-ums dialect — which authenticates with HTTP Basic
# and therefore prompts for a UMS administrator username the generic path does
# not ask for. The password arrives via the patched getpass.
IGEL_INPUT = "fleet1\nums.example.com\nigel-ums\n\n\n\nums-admin\nn\nn\n"


@pytest.fixture
def init_home(tmp_path, monkeypatch):
    """Isolate config + secret store + governance home under tmp_path."""
    config_file = tmp_path / "config.yaml"
    secrets_file = tmp_path / "secrets.enc"
    monkeypatch.setenv("ENDPOINT_AIOPS_HOME", str(tmp_path))
    monkeypatch.setenv("ENDPOINT_AIOPS_MASTER_PASSWORD", MASTER_PW)
    monkeypatch.setattr(init_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(init_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", config_file)
    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", secrets_file)
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(ss, "_cached", None)
    # The hidden API-key prompt bypasses CliRunner stdin.
    monkeypatch.setattr(getpass_mod, "getpass", lambda prompt="": API_KEY)
    return tmp_path


def _run_init(input_text: str = WIZARD_INPUT):
    from endpoint_aiops.cli import app

    return CliRunner().invoke(app, ["init"], input=input_text)


@pytest.mark.unit
def test_init_writes_config_with_entered_values(init_home):
    result = _run_init()
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))
    assert raw["targets"] == [
        {
            "name": "fleet1",
            "host": "mgmt.example.com",
            "port": 443,
            "scheme": "https",
            "verify_ssl": True,  # accepted TLS confirm default=True must land
            "api_path": "/api/v2.0",
            "dialect": "generic",  # written explicitly — never left implicit
        }
    ]


@pytest.mark.unit
def test_init_tls_confirm_can_be_declined_for_lab_certs(init_home):
    result = _run_init("fleet1\nmgmt.example.com\n\n\n\nn\nn\nn\n")
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))
    assert raw["targets"][0]["verify_ssl"] is False


@pytest.mark.unit
def test_init_stores_secret_encrypted_not_in_config(init_home):
    result = _run_init()
    assert result.exit_code == 0, result.output
    # API key is readable back through the secret store API...
    assert ss.SecretStore.unlock(MASTER_PW).get("fleet1") == API_KEY
    # ...and never lands in plaintext in config.yaml or secrets.enc.
    assert API_KEY not in (init_home / "config.yaml").read_text("utf-8")
    assert API_KEY not in (init_home / "secrets.enc").read_text("utf-8")


@pytest.mark.unit
def test_init_writes_no_policy_rules(init_home):
    """The skill no longer authorizes, so init seeds no rules.yaml — a fresh
    install delivers full functionality and leaves permission to the account."""
    result = _run_init()
    assert result.exit_code == 0, result.output
    assert not (init_home / "rules.yaml").exists()


@pytest.mark.unit
def test_init_accepting_doctor_confirm_runs_doctor(init_home, monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(doctor_mod, "run_doctor", lambda: calls.append(True) or 0)
    # Empty last answer accepts the confirm's default=True.
    result = _run_init("fleet1\nmgmt.example.com\n\n\n\n\nn\n\n")
    assert result.exit_code == 0, result.output
    assert calls == [True]


@pytest.mark.unit
def test_init_overwrite_existing_target(init_home):
    result = _run_init()
    assert result.exit_code == 0, result.output
    # Same name again: confirm overwrite, new host, accept defaults.
    result = _run_init("fleet1\ny\nmgmt2.example.com\n\n\n\n\nn\nn\n")
    assert result.exit_code == 0, result.output
    raw = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))
    assert [t["host"] for t in raw["targets"]] == ["mgmt2.example.com"]


@pytest.mark.unit
def test_init_igel_preset_writes_igel_port_and_api_path(init_home):
    """Choosing igel-ums must configure IMI's real transport, not the placeholder."""
    result = _run_init(IGEL_INPUT)
    assert result.exit_code == 0, result.output
    target = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))["targets"][0]
    assert target["dialect"] == "igel-ums"
    assert target["port"] == 8443
    assert target["api_path"] == "/umsapi/v3"


@pytest.mark.unit
def test_init_names_the_dialect_it_configured(init_home):
    """The wizard must say which dialect it set up, not leave it implicit."""
    result = _run_init(IGEL_INPUT)
    assert "igel-ums" in result.output


@pytest.mark.unit
def test_init_warns_that_generic_is_a_placeholder(init_home):
    result = _run_init()
    assert "placeholder" in result.output


@pytest.mark.unit
def test_init_reprompts_on_an_unknown_dialect(init_home):
    result = _run_init("fleet1\nmgmt.example.com\nnot-a-dialect\n\n\n\n\nn\nn\n")
    assert result.exit_code == 0, result.output
    assert "Unknown dialect" in result.output
    target = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))["targets"][0]
    assert target["dialect"] == "generic"


@pytest.mark.unit
def test_init_can_select_plain_http(init_home):
    """The scheme knob must survive the wizard (bug class 8: no connection knob)."""
    result = _run_init("fleet1\nmgmt.example.com\n\nhttp\n\n\nn\nn\n")
    assert result.exit_code == 0, result.output
    target = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))["targets"][0]
    assert target["scheme"] == "http"


@pytest.mark.unit
def test_init_asks_for_a_username_on_a_basic_auth_dialect(init_home):
    """igel-ums logs in with a UMS account, so 'API key' is the wrong prompt."""
    result = _run_init(IGEL_INPUT)
    assert result.exit_code == 0, result.output
    assert "UMS administrator username" in result.output
    assert "Read/Browse permission at the Devices level" in result.output
    target = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))["targets"][0]
    assert target["username"] == "ums-admin"


@pytest.mark.unit
def test_init_omits_username_for_the_bearer_dialect(init_home):
    """A static-token dialect has no username; the key is the whole credential."""
    result = _run_init()
    assert result.exit_code == 0, result.output
    assert "UMS administrator username" not in result.output
    target = yaml.safe_load((init_home / "config.yaml").read_text("utf-8"))["targets"][0]
    assert "username" not in target
