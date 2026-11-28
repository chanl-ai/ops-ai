"""platform-service's token holds the account admin cell (settings:manage) only in dev, where models-service seeds a
new account's models from it; outside dev a leaked platform token cannot change an account's model setup."""

from __future__ import annotations

import pytest

from ops_service_kit.settings import Settings


def test_platform_holds_settings_manage_in_dev_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPS_ENVIRONMENT", raising=False)
    monkeypatch.delenv("OPS_SERVICE_SCOPES", raising=False)
    held = {env: "settings:manage" in Settings(environment=env).service_scopes["platform"] for env in ("dev", "test")}
    assert held == {"dev": True, "test": False}
