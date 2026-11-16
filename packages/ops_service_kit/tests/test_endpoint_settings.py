"""Other services as settings, by failure mode: a process starting without an address it needs, a deploy that names
only addresses losing its endpoints, and a forgotten sign-in setting opening a service."""

from __future__ import annotations

import pytest

from ops_service_kit.settings import ENDPOINTS, Settings


@pytest.fixture(autouse=True)
def _no_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENDPOINTS:
        for env in (f"OPS_{name.upper()}_URL", f"OPS_{name.upper()}__URL"):
            monkeypatch.delenv(env, raising=False)
    monkeypatch.delenv("OPS_AUTH_MODE", raising=False)
    monkeypatch.delenv("OPS_ENVIRONMENT", raising=False)


def test_require_exits_naming_every_unset_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_KB_URL", "http://kb:8740")
    settings = Settings()
    settings.require("kb")
    with pytest.raises(SystemExit) as stopped:
        settings.require("agents", "kb", "platform_internal")
    message = str(stopped.value)
    assert "OPS_AGENTS_URL" in message and "OPS_PLATFORM_INTERNAL_URL" in message
    assert "OPS_KB_URL" not in message
    # Read later instead of required at start, the unset address is still named and never this machine.
    with pytest.raises(ValueError, match="OPS_AGENTS_URL is not set"):
        settings.endpoint("agents")


def test_an_address_alone_and_an_endpoint_set_whole_both_reach_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every deploy file names OPS_<X>_URL; the endpoint's own timeout and retries sit beside it when a site sets them.
    monkeypatch.setenv("OPS_AGENTS_URL", "http://agents:8700/")
    monkeypatch.setenv("OPS_AGENTS__TIMEOUT_S", "3")
    monkeypatch.setenv("OPS_TOOLS__URL", "http://tools:8720")
    monkeypatch.setenv("OPS_TOOLS__RETRIES", "0")
    monkeypatch.setenv("OPS_DB__SIZE", "9")
    settings = Settings()
    agents, tools = settings.endpoint("agents"), settings.endpoint("tools")
    assert (agents.base, agents.timeout_s, agents.retries) == ("http://agents:8700", 3.0, 2)
    assert (tools.base, tools.timeout_s, tools.retries) == ("http://tools:8720", 10.0, 0)
    # Code that still reads the address sees the endpoint.
    assert settings.tools_url == "http://tools:8720"
    assert (settings.db.size, settings.db.overflow) == (9, 10)


def test_a_service_with_no_sign_in_setting_signs_its_callers_in(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().auth_mode == "platform"
    assert Settings().identity_endpoints == ("platform_internal",)
    # Production with nothing else set keeps every caller signed in, and refuses the dev user when asked for it.
    monkeypatch.setenv("OPS_ENVIRONMENT", "production")
    assert Settings().auth_mode == "platform"
    monkeypatch.setenv("OPS_AUTH_MODE", "dev")
    with pytest.raises(ValueError, match="auth_mode 'dev' is refused"):
        Settings()


def test_models_and_platform_are_endpoints_from_the_addresses_every_deploy_already_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A caller of models-service or platform-service's public port reads its timeout from settings, not a literal;
    # a model call waits on a model, so its endpoint's default is longer than the other services'.
    monkeypatch.setenv("OPS_MODELS_URL", "http://models:8730")
    monkeypatch.setenv("OPS_PLATFORM_URL", "http://platform:8710")
    monkeypatch.setenv("OPS_PLATFORM__TIMEOUT_S", "4")
    settings = Settings()
    models, platform = settings.endpoint("models"), settings.endpoint("platform")
    assert (models.base, models.timeout_s, models.retries) == ("http://models:8730", 120.0, 2)
    assert (platform.base, platform.timeout_s) == ("http://platform:8710", 4.0)
    monkeypatch.setenv("OPS_MODELS__TIMEOUT_S", "30")
    assert Settings().endpoint("models").timeout_s == 30.0
    monkeypatch.delenv("OPS_PLATFORM_URL")
    monkeypatch.delenv("OPS_PLATFORM__TIMEOUT_S")
    with pytest.raises(ValueError, match="OPS_PLATFORM_URL is not set"):
        Settings().endpoint("platform")


def test_the_runner_reads_its_fetch_timeout_and_every_wait_on_a_guest_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A wait the runner passes to a join or a fetch is a setting, so an operator can widen it without a code change.
    monkeypatch.setenv("OPS_RUNNER_FETCH_TIMEOUT_S", "300")
    monkeypatch.setenv("OPS_RUNNER_WAITS__GRACE_S", "5")
    settings = Settings()
    waits = settings.runner_waits
    assert settings.runner_fetch_timeout_s == 300.0
    assert (waits.tick_s, waits.grace_s, waits.open_poll_s, waits.read_poll_s) == (0.1, 5.0, 0.005, 0.01)
    monkeypatch.setenv("OPS_RUNNER_WAITS__READ_POLL_S", "0")
    with pytest.raises(ValueError, match="greater than 0"):
        Settings()
