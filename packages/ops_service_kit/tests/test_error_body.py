"""The error body every service answers a refusal with, by failure mode: a refused call says neither what kind of
failure it was nor whether trying again helps, so each caller keeps its own table of what a status means."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ops_service_kit.errors import Forbidden
from ops_service_kit.http import install_error_handlers


def test_a_refusal_says_its_kind_and_whether_a_retry_helps() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/runs")
    async def runs() -> None:  # pyright: ignore[reportUnusedFunction]
        raise Forbidden("Your role may not read this team's runs.")

    answered = TestClient(app).get("/runs")
    error = answered.json()["error"]
    assert (answered.status_code, error["code"]) == (403, "forbidden"), error
    assert (error.get("kind"), error.get("retryable")) == ("refused", False), error
