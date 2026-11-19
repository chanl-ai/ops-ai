"""The bases for a body or reply in an outside system's wire format (OpenAI's snake_case), by failure mode: a field
renamed to camelCase in the document or on the wire; an unknown key accepted; the route walk counting the model as
untyped; and a conversion from a plain `extra="forbid"` model changing the service's OpenAPI document."""

import json

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, ValidationError

from ops_service_kit.contract import boundaries
from ops_service_kit.http import ExternalIn, ExternalOut, install_error_handlers, operation_id


class Usage(ExternalOut):
    prompt_tokens: int
    total_tokens: int


class Ask(ExternalIn):
    max_tokens: int


def bare() -> FastAPI:
    api = FastAPI(generate_unique_id_function=operation_id)
    install_error_handlers(api)
    return api


def app() -> FastAPI:
    api = bare()

    @api.post("/v1/usage", tags=["usage"], response_model=Usage)
    async def usage(ask: Ask) -> dict[str, int]:
        return {"prompt_tokens": 3, "total_tokens": 3}

    return api


async def test_names_stay_as_declared_in_the_document_on_the_wire_and_in_the_walk() -> None:
    api = app()
    doc = api.openapi()["components"]["schemas"]
    assert set(doc["Usage"]["properties"]) == {"prompt_tokens", "total_tokens"}
    assert set(doc["Ask"]["properties"]) == {"max_tokens"}
    assert boundaries(api) == []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(api), base_url="http://test") as client:
        r = await client.post("/v1/usage", json={"max_tokens": 5})
        assert r.status_code == 200 and r.json() == {"prompt_tokens": 3, "total_tokens": 3}
        # The camelCase spelling is an unknown field to an outside format, so it answers 400.
        assert (await client.post("/v1/usage", json={"maxTokens": 5})).status_code == 400


def test_a_reply_with_an_unknown_key_fails() -> None:
    with pytest.raises(ValidationError):
        Usage.model_validate({"prompt_tokens": 1, "total_tokens": 1, "cached_tokens": 0})


def test_converting_a_plain_forbid_model_leaves_the_document_byte_identical() -> None:
    # The same names as the converted models, so only the base differs between the two documents.
    class Usage(BaseModel):
        model_config = ConfigDict(extra="forbid")
        prompt_tokens: int
        total_tokens: int

    class Ask(BaseModel):
        model_config = ConfigDict(extra="forbid")
        max_tokens: int

    before = bare()

    @before.post("/v1/usage", tags=["usage"], response_model=Usage)
    async def usage(ask: Ask) -> dict[str, int]:
        return {"prompt_tokens": 3, "total_tokens": 3}

    assert json.dumps(app().openapi(), sort_keys=True) == json.dumps(before.openapi(), sort_keys=True)
