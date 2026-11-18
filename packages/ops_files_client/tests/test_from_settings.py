"""The client a service builds from its settings, by failure mode: a call reaching files-service without the tenant,
team or scopes in its token, at another address than the files endpoint, or with a wait other than the endpoint's."""

from __future__ import annotations

import base64
import json
from functools import partial
from typing import Any

import httpx
import pytest

from ops_files_client import FilesClient
from ops_files_client.testing import FakeFilesService
from ops_service_kit.settings import Settings


def _claims(request: httpx.Request) -> dict[str, Any]:
    body = request.headers["Authorization"].removeprefix("Bearer ").split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


@pytest.mark.asyncio
async def test_a_client_from_settings_calls_the_files_endpoint_as_the_service_for_the_tenant_and_team(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, seen = FakeFilesService(), list[httpx.Request]()

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return fake.handle(request)

    # The network is the edge: every client built in this test answers from the fake files-service.
    monkeypatch.setattr(httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handle)))
    settings = Settings(environment="dev", files_url="http://files.internal:8750")
    client = FilesClient.from_settings(settings, service="kb")
    # Bytes go up on the client's own connection; a JSON call goes through the service client.
    stored = await client.write(
        "t1", "team-a", b"hello", name="a.txt", mime="text/plain", purpose="knowledge_source", uploaded_by="u1"
    )
    assert (await client.get("t1", "team-a", stored.file.id)).name == "a.txt"
    for request in seen:
        claims = _claims(request)
        assert str(request.url).startswith("http://files.internal:8750/v1/files")
        assert (claims["sub"], claims["aud"], claims["tenant_id"], claims["team_id"]) == (
            "service:kb",
            "files",
            "t1",
            "team-a",
        )
        assert sorted(claims["scopes"]) == ["files:create", "files:edit", "files:view"]
        assert request.extensions["timeout"]["read"] == 30.0
    assert len(seen) == 2
