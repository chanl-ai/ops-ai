"""A fetch of a typed-in URL reaches public addresses only, and connects to the address it checked."""

from __future__ import annotations

import httpx
import pytest

from ops_service_kit.public_address import AddressRefused, PublicFetch

PUBLIC = "93.184.216.34"


class Answers:
    """A resolver that gives each host its scripted answers in turn, the last one repeating."""

    def __init__(self, **hosts: list[str]) -> None:
        self.hosts = {h.replace("_", "."): list(a) for h, a in hosts.items()}
        self.asked: list[str] = []

    async def resolve(self, host: str, port: int) -> list[str]:
        self.asked.append(host)
        answers = self.hosts[host]
        return [answers.pop(0)] if len(answers) > 1 else answers


def _client(seen: list[httpx.Request], redirect_to: str | None = None) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if redirect_to and len(seen) == 1:
            return httpx.Response(302, headers={"location": redirect_to})
        return httpx.Response(200, content=b"<md/>")

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


@pytest.mark.parametrize("address", ["10.1.2.3", "169.254.169.254", "127.0.0.1", "::1", "100.64.0.9"])
async def test_a_host_that_resolves_inside_the_network_is_refused(address: str) -> None:
    seen: list[httpx.Request] = []
    fetch = PublicFetch(resolver=Answers(idp_example_com=[address]))
    async with _client(seen) as client:
        with pytest.raises(AddressRefused):
            await fetch.get(client, "https://idp.example.com/metadata")
    assert seen == []


async def test_a_redirect_to_an_inside_address_is_refused() -> None:
    seen: list[httpx.Request] = []
    fetch = PublicFetch(resolver=Answers(idp_example_com=[PUBLIC], inside_example_com=["10.0.0.5"]))
    async with _client(seen, redirect_to="https://inside.example.com/x") as client:
        with pytest.raises(AddressRefused):
            await fetch.get(client, "https://idp.example.com/metadata")
    assert len(seen) == 1


async def test_the_connection_goes_to_the_checked_address_when_dns_changes_its_answer() -> None:
    seen: list[httpx.Request] = []
    # Public when checked, private on any later lookup: a connection made by name would reach the private one.
    fetch = PublicFetch(resolver=Answers(idp_example_com=[PUBLIC, "10.0.0.5"]))
    async with _client(seen) as client:
        assert await fetch.get(client, "https://idp.example.com/metadata") == b"<md/>"
    assert seen[0].url.host == PUBLIC
    assert seen[0].headers["host"] == "idp.example.com"
    assert seen[0].extensions["sni_hostname"] == "idp.example.com"


async def test_plain_http_is_refused() -> None:
    fetch = PublicFetch(resolver=Answers(idp_example_com=[PUBLIC]))
    async with _client([]) as client:
        with pytest.raises(AddressRefused):
            await fetch.get(client, "http://idp.example.com/metadata")
