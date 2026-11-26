"""agents-service and its worker publish and run workflow steps, and a tool step runs only through the tool gateway, so
neither starts without OPS_GATEWAY_URL: a deployment that runs always has the gateway its publish check reads."""

from __future__ import annotations

from types import ModuleType

import pytest

from ops_agents.api import __main__ as api_main
from ops_agents.api import worker


def _booted(*_: object, **__: object) -> None:
    raise AssertionError("booted past the gateway check without OPS_GATEWAY_URL")


@pytest.mark.parametrize("module", [api_main, worker], ids=["agents-service", "worker"])
def test_boot_without_a_gateway_stops_naming_the_variable(module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    # The step after the checks opens the database; stopped here, a boot that skipped the check never serves.
    monkeypatch.setattr(module, "require_current_schema", _booted)
    monkeypatch.delenv("OPS_GATEWAY_URL", raising=False)
    monkeypatch.delenv("OPS_ALLOW_NO_GATEWAY", raising=False)
    monkeypatch.setenv("OPS_AUTH_MODE", "dev")
    with pytest.raises(SystemExit, match="OPS_GATEWAY_URL must be set"):
        module.main()
