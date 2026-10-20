"""The engine's fault-injection settings break crash recovery on purpose (uc-081's negative run); a deployment that is
not dev or test must refuse to start with them."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from ops_service_kit.settings import Settings

PROD = {
    "environment": "production",
    "auth_mode": "platform",
    "review_key": SecretStr("k" * 32),
    "secrets_key": SecretStr("a" * 64),
}


@pytest.mark.parametrize("fault", [{"engine_fault_ignore_recorded": True}, {"engine_fault_kill_after_node": "lookup"}])
def test_fault_settings_are_refused_outside_dev_and_test(fault: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="engine_fault_"):
        Settings(**PROD, **fault)  # pyright: ignore[reportArgumentType]
    assert Settings(environment="dev", **fault).environment == "dev"  # pyright: ignore[reportArgumentType]


def test_a_production_deployment_without_faults_starts() -> None:
    assert Settings(**PROD).engine_fault_ignore_recorded is False  # pyright: ignore[reportArgumentType]
