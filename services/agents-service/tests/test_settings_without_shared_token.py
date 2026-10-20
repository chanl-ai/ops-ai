"""The shared static service token is gone (c-045): every internal call uses a per-service Ed25519 token, so outside
dev no service may demand a secret nothing reads, and one left over in an environment changes nothing."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from ops_service_kit.settings import Settings


def production() -> Settings:
    return Settings(
        environment="production",
        auth_mode="platform",
        review_key=SecretStr("r" * 40),
        secrets_key=SecretStr("ab" * 32),
    )


def test_production_settings_start_without_a_shared_service_token() -> None:
    assert not hasattr(production(), "service_token")


def test_a_leftover_shared_token_in_the_environment_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_SERVICE_TOKEN", "left-over-from-before")
    assert not hasattr(production(), "service_token")
