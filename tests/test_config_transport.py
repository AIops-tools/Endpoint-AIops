"""Target transport resolution: scheme knob + dialect-driven port / API base path.

Two defects are pinned here:

  * **Bug class 7** — ``api_path`` and ``port`` were hardcoded to ``/api/v2.0``
    on 443, a shape no shipped management server serves. Selecting the IGEL
    dialect must move the transport to IMI's real ``/umsapi/v3`` on 8443,
    otherwise the very first probe 404s.
  * **Bug class 8** — the URL was hardcoded to ``https://`` with no knob, so a
    management server behind a plain-HTTP reverse proxy was simply unreachable.
"""

from __future__ import annotations

import pytest
import yaml

from endpoint_aiops.config import TargetConfig, load_config


@pytest.mark.unit
def test_generic_target_keeps_the_legacy_transport():
    """Existing configs must be untouched by the dialect-driven defaults."""
    t = TargetConfig(name="t", host="h")
    assert t.port == 443
    assert t.api_path == "/api/v2.0"
    assert t.base_url == "https://h:443/api/v2.0"


@pytest.mark.unit
def test_igel_dialect_moves_the_transport_to_imi():
    t = TargetConfig(name="t", host="ums.local", dialect="igel-ums")
    assert t.port == 8443
    assert t.api_path == "/umsapi/v3"
    assert t.base_url == "https://ums.local:8443/umsapi/v3"


@pytest.mark.unit
def test_an_explicit_port_and_api_path_win_over_the_dialect():
    """An operator who states the transport is not second-guessed."""
    t = TargetConfig(name="t", host="ums.local", dialect="igel-ums",
                     port=9443, api_path="/custom/v1")
    assert t.base_url == "https://ums.local:9443/custom/v1"


@pytest.mark.unit
def test_scheme_defaults_to_https():
    assert TargetConfig(name="t", host="h").scheme == "https"


@pytest.mark.unit
def test_scheme_http_reaches_a_reverse_proxied_server():
    t = TargetConfig(name="t", host="h", scheme="http")
    assert t.base_url == "http://h:443/api/v2.0"


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["ftp", "HTTPS", "", "https://"])
def test_an_invalid_scheme_is_rejected_with_the_reason(bad):
    with pytest.raises(ValueError, match="must be 'https' or 'http'"):
        TargetConfig(name="t", host="h", scheme=bad)


@pytest.mark.unit
def test_load_config_reads_scheme_and_dialect(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"targets": [
        {"name": "ums1", "host": "ums.local", "dialect": "igel-ums", "scheme": "http"},
    ]}), "utf-8")
    target = load_config(path).targets[0]
    assert target.scheme == "http"
    assert target.base_url == "http://ums.local:8443/umsapi/v3"


@pytest.mark.unit
def test_load_config_without_scheme_stays_https(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"targets": [
        {"name": "f1", "host": "h", "port": 8080, "api_path": "/x"},
    ]}), "utf-8")
    target = load_config(path).targets[0]
    assert target.base_url == "https://h:8080/x"
