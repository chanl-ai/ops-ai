"""The shared static service token is gone: every internal call uses a per-service Ed25519 token, so outside
dev no service may demand a secret nothing reads."""

from __future__ import annotations

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
