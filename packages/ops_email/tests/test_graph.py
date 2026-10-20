"""GraphMailSource, by failure mode: a next or delta link on another host receives the mailbox's bearer token."""

from __future__ import annotations

import httpx
import pytest

from ops_email import GraphMailSource, GraphToken


async def test_a_link_off_the_graph_host_is_refused_before_any_token_is_sent() -> None:
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url.host))
        return httpx.Response(200, json={"access_token": "t", "expires_in": 3600, "value": []})

    http = httpx.AsyncClient(base_url="https://graph.microsoft.com", transport=httpx.MockTransport(answer))
    token = GraphToken(
        http, login_url="https://login.microsoftonline.com", tenant="t", client_id="c", secret="s", scope="x"
    )
    source = GraphMailSource(http, token, "levy@contoso.example")
    for link in ("https://evil.example/v1.0/users/levy@contoso.example/messages/delta", "http://graph.microsoft.com/x"):
        with pytest.raises(ValueError):
            await source.delta(link)
    assert asked == [], asked
    await source.delta("https://graph.microsoft.com/v1.0/users/levy@contoso.example/mailFolders/inbox/messages/delta")
    assert asked == ["login.microsoftonline.com", "graph.microsoft.com"], asked
