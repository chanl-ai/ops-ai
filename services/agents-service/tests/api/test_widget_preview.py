"""The console's "Preview as a person" (c-158 follow-up): a signed-in editor of a deployment gets a widget session
bound to the console's origin, recorded on the deployment's key audit. One test per way the preview could open a
door a page or a server does not have."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

from tests.api import test_write_approval_policy as platform_stub
from tests.api.test_widget_embed import (
    BUILDER,
    EMBED,
    OPS_KEY,
    SETTINGS,
    VIEWER,
    deploy,
    introspect,
)
from tests.api.test_write_approval_policy import _client  # pyright: ignore[reportPrivateUsage]

CONSOLE = "http://localhost:3016"


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(platform_stub, "introspect", introspect)
    async for c in _client(SETTINGS.model_copy(update={"console_url": CONSOLE}), platform=True):
        yield c


async def test_an_editor_previews_on_the_consoles_origin_and_it_is_audited(client: AsyncClient) -> None:
    dep = await deploy(client)
    res = await client.post(f"/v1/widget-deployments/{dep['id']}/preview-session", headers=BUILDER)
    assert res.status_code == 201, res.text
    token = res.json()["data"]["session"]
    # The embed app frames the chat in the console and speaks for the session's origin, the console's.
    opened = await client.post(f"/v1/widget/{dep['id']}/threads", headers={"X-Widget-Session": token, "Origin": EMBED})
    assert opened.status_code == 201, opened.text
    audit = (await client.get(f"/v1/widget-deployments/{dep['id']}/keys/audit", headers=BUILDER)).json()["data"]
    assert [a["action"] for a in audit] == ["preview"], audit


async def test_a_preview_session_is_for_the_console_only_not_a_bank_page(client: AsyncClient) -> None:
    dep = await deploy(client)
    token = (await client.post(f"/v1/widget-deployments/{dep['id']}/preview-session", headers=BUILDER)).json()["data"]
    elsewhere = await client.post(
        f"/v1/widget/{dep['id']}/threads",
        headers={"X-Widget-Session": token["session"], "Origin": "https://evil.example"},
    )
    assert elsewhere.status_code == 403, elsewhere.text


async def test_only_an_editor_with_their_own_sign_in_previews(client: AsyncClient) -> None:
    dep = await deploy(client)
    viewer = await client.post(f"/v1/widget-deployments/{dep['id']}/preview-session", headers=VIEWER)
    key = await client.post(f"/v1/widget-deployments/{dep['id']}/preview-session", headers=OPS_KEY)
    assert viewer.status_code in (403, 404), viewer.text
    assert key.status_code == 403 and key.json()["error"]["code"] == "api_key_refused", key.text


async def test_the_console_reads_a_deployments_config_for_its_preview_other_pages_not(client: AsyncClient) -> None:
    dep = await deploy(client)
    url = f"/v1/widget/{dep['id']}/config?tenant=acme"
    console = await client.get(url, headers={"Origin": CONSOLE})
    other = await client.get(url, headers={"Origin": "https://evil.example"})
    assert console.status_code == 200 and console.json()["data"]["deploymentName"], console.text
    assert other.status_code == 403, other.text


async def test_the_preview_frame_gets_one_cors_header_on_the_config_read(monkeypatch: pytest.MonkeyPatch) -> None:
    # The console's origin is also on the app's CORS list, so both CORS layers would answer it; a browser refuses a
    # response that names the allowed origin twice, and the preview's loader then reads nothing.
    monkeypatch.setattr(platform_stub, "introspect", introspect)
    settings = SETTINGS.model_copy(update={"console_url": CONSOLE, "cors_origins": [CONSOLE]})
    async for c in _client(settings, platform=True):
        dep = await deploy(c)
        res = await c.get(f"/v1/widget/{dep['id']}/config", params={"tenant": "acme"}, headers={"Origin": CONSOLE})
        assert res.status_code == 200, res.text
        assert res.headers.get_list("access-control-allow-origin") == [CONSOLE]
