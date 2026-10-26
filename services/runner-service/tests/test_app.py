"""POST /v1/runs: only a service may run code, the deployment's caps hold over what the caller asks, and a run with
no call token cannot call tools."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ops_identity import dev_service_signer, mint_service_token
from ops_runner.app import LimitsIn, capped, create_runner_app
from ops_runner.wasm import WasmPython
from ops_service_kit.settings import Settings


def client(runtime: WasmPython) -> TestClient:
    settings = Settings(environment="dev")
    return TestClient(create_runner_app(runtime, settings=settings, tools=None))


def service() -> dict[str, str]:
    token = mint_service_token(dev_service_signer(), service="tools", audience="runner", tenant_id="local", ttl_s=3600)
    return {"Authorization": f"Bearer {token}"}


def test_a_run_needs_a_service_token(runtime: WasmPython) -> None:
    r = client(runtime).post("/v1/runs", json={"source": "def main(i):\n    return 1"})
    assert r.status_code == 401


def test_a_run_answers_its_output_and_timings(runtime: WasmPython) -> None:
    r = client(runtime).post(
        "/v1/runs",
        json={"source": "def main(i):\n    return {'over': i['amount'] > 100}", "input": {"amount": 150}},
        headers=service(),
    )
    data = r.json()["data"]
    assert r.status_code == 200 and data["ok"] and data["output"] == {"over": True}
    assert data["createMs"] >= 0 and data["executeMs"] >= 0


def test_without_a_call_token_a_call_is_refused(runtime: WasmPython) -> None:
    r = client(runtime).post("/v1/runs", json={"source": "def main(i):\n    return ops.call('x')"}, headers=service())
    assert r.json()["data"]["error"]["code"] == "calls_unavailable"


def test_the_deployment_caps_hold_over_what_is_asked() -> None:
    settings = Settings(runner_max_memory_mb=512, runner_max_time_s=30, runner_max_calls=50)
    limits = capped(LimitsIn(memory_mb=4096, time_s=600, calls=1000), settings)
    assert (limits.memory_mb, limits.time_s, limits.calls) == (512, 30, 50)
