"""What a log line says on stdout: one JSON object per record, whoever made it, with the ids and no secret."""

from __future__ import annotations

import asyncio
import io
import json
import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from ops_service_kit.http import install_error_handlers
from ops_service_kit.logging import REDACTED, add_context, configure_logging, get_logger
from ops_service_kit.request_timing import RequestTiming, _current, note_caller  # pyright: ignore[reportPrivateUsage]

SECRET = "eyJ-kit-test-token"
BEARER = f"Bearer {SECRET}"


@pytest.fixture
def out() -> Generator[io.StringIO]:
    stream = io.StringIO()
    root = logging.getLogger()
    level = root.level
    configure_logging(service="kit-test", stream=stream)
    yield stream
    root.setLevel(level)
    for h in [h for h in root.handlers if getattr(h, "stream", None) is stream]:
        root.removeHandler(h)


def lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_structlog_stdlib_and_uvicorn_records_are_each_one_json_line_with_secrets_removed(out: io.StringIO) -> None:
    get_logger("ops_kit.test").info("kit.saved", authorization=BEARER, owner="a.person@bank.example")
    logging.getLogger("some.library").warning("library said", extra={"authorization": BEARER})
    # uvicorn's access record, as uvicorn.protocols.http makes it: the encoded path with its query string.
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:5000",
        "GET",
        f"/v1/x?authorization=Bearer%20{SECRET}&api_key=sk1",
        "1.1",
        200,
    )
    ours, library, uvicorn = lines(out)
    for line in (ours, library, uvicorn):
        assert line["service.name"] == "kit-test" and line["level"] in {"info", "warning"} and line["ts"].endswith("Z")
    assert ours["event"] == "kit.saved" and ours["authorization"] == REDACTED and ours["owner"] == "[email]"
    assert library["event"] == "library said" and library["authorization"] == REDACTED
    assert uvicorn["logger"] == "uvicorn.access" and uvicorn["event"] == '127.0.0.1:5000 - "GET /v1/x HTTP/1.1" 200'
    assert SECRET not in out.getvalue() and "sk1" not in out.getvalue()


def test_a_line_carries_the_request_id_and_the_ids_a_registered_reader_finds(out: io.StringIO) -> None:
    remove = add_context(lambda: {"tenant_id": "tenant_kit", "team_id": None})
    token = _current.set(RequestTiming("req_kit_test_1"))
    try:
        get_logger("ops_kit.test").info("kit.in_request")
    finally:
        _current.reset(token)
        remove()
    get_logger("ops_kit.test").info("kit.outside")
    inside, outside = lines(out)
    assert (inside["request_id"], inside["tenant_id"], inside["team_id"]) == ("req_kit_test_1", "tenant_kit", None)
    assert outside["request_id"] is None


def test_a_value_json_cannot_encode_still_gives_one_line(out: io.StringIO) -> None:
    get_logger("ops_kit.test").error("kit.failed", path=Path("/srv/x"), exc_info=ValueError("no"))
    (line,) = lines(out)
    assert line["path"] == "/srv/x" and line["exception"] == "ValueError: no" and line["level"] == "error"


def test_configuring_twice_writes_each_line_once(out: io.StringIO) -> None:
    configure_logging(service="kit-test", stream=out)
    get_logger("ops_kit.test").info("kit.once")
    assert len(lines(out)) == 1


def test_each_request_writes_one_http_request_line_with_its_id_and_route_template(out: io.StringIO) -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/v1/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        note_caller("tenant_kit", "t1")  # as an auth dependency does once the caller is verified
        return {"id": item_id}

    async def call() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kit") as c:
            await c.get(
                "/v1/items/itm_1?api_key=sk-in-query", headers={"X-Request-Id": "req_kit_route_1", "X-Team-Id": "t1"}
            )

    asyncio.run(call())
    (line,) = [row for row in lines(out) if row["event"] == "http.request"]
    assert (line["request_id"], line["tenant_id"], line["team_id"]) == ("req_kit_route_1", "tenant_kit", "t1")
    assert line["http.route"] == "/v1/items/{item_id}" and line["http.response.status_code"] == 200
    assert "sk-in-query" not in out.getvalue() and "itm_1" not in out.getvalue()


def test_nested_secrets_and_personal_data_are_removed_and_counts_kept(out: io.StringIO) -> None:
    get_logger("ops_kit.test").warning(
        "kit.nested", call={"headers": {"Cookie": "sid=abc"}, "to": ["a.person@bank.example"]}, input_tokens=12
    )
    (line,) = lines(out)
    assert line["call"] == {"headers": {"Cookie": REDACTED}, "to": ["[email]"]} and line["input_tokens"] == 12
