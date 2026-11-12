"""Which network addresses a service may reach for a URL someone typed in, and a fetch that holds to it.

`address_allowed` is the one rule: loopback, link-local, multicast, unspecified and cloud-metadata addresses never;
private, CGNAT and reserved ones only inside a range the caller lists; public ones always. tools-service applies it to
every outbound tool call, platform-service to identity-provider metadata and OIDC discovery.

`fetch_public` resolves the host once, checks every answer, and connects to the address it checked, naming the host
only in the Host header and the TLS server name. Connecting by name after the check would let a DNS answer that
changes between the check and the connection (rebinding) reach an address the check refused. Each redirect is checked
the same way.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx

CGNAT = ipaddress.IPv4Network("100.64.0.0/10")
ALWAYS_DENIED = (
    ipaddress.ip_network("169.254.169.254/32"),
    ipaddress.ip_network("fd00:ec2::254/128"),
)


def address_allowed(address: str, ranges: Iterable[str] = ()) -> bool:
    """Whether `address` may be reached: never loopback, link-local, multicast, unspecified or cloud metadata;
    private, CGNAT and reserved only inside one of `ranges` (CIDR); public always."""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return False
    if any(ip in net for net in ALWAYS_DENIED):
        return False
    cgnat = ip.version == 4 and ipaddress.IPv4Address(int(ip)) in CGNAT
    if ip.is_private or ip.is_reserved or cgnat:
        return any(ip in ipaddress.ip_network(r) for r in ranges)
    return True


class Resolver(Protocol):
    async def resolve(self, host: str, port: int) -> list[str]: ...


class SystemResolver:
    """The operating system's resolver."""

    async def resolve(self, host: str, port: int) -> list[str]:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return list(dict.fromkeys(str(info[4][0]) for info in infos))


class AddressRefused(ValueError):
    """The URL is not https, or its host resolves to an address the rule refuses. The message names the host only."""


class FetchFailed(ValueError):
    """The fetch did not return a usable document: an error status, too many redirects, too large, or no answer."""


@dataclass(frozen=True)
class PublicFetch:
    """How a service fetches a URL someone typed in. `ranges` lists private networks that may be reached;
    `require_https` is off only in dev and tests, where the fake identity provider serves plain http."""

    resolver: Resolver = field(default_factory=SystemResolver)
    ranges: tuple[str, ...] = ()
    require_https: bool = True
    max_bytes: int = 256 * 1024
    max_redirects: int = 3
    timeout_s: float = 5.0

    async def checked_address(self, url: str) -> tuple[str, str, int]:
        """The (host, address, port) a fetch of `url` connects to. Raises AddressRefused."""
        parts = urlsplit(url)
        if parts.scheme != "https" and (self.require_https or parts.scheme != "http"):
            raise AddressRefused("The address must start with https://.")
        host = (parts.hostname or "").lower()
        if not host:
            raise AddressRefused("The address names no host.")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            answers = await self.resolver.resolve(host, port)
        except OSError as e:
            raise AddressRefused(f"{host} could not be found.") from e
        if not answers or not all(address_allowed(a, self.ranges) for a in answers):
            raise AddressRefused(f"{host} is not a public address.")
        return host, answers[0], port

    async def get(self, client: httpx.AsyncClient, url: str) -> bytes:
        """The body of `url`, fetched through `client` to the checked address. Raises AddressRefused or FetchFailed."""
        for _ in range(self.max_redirects + 1):
            host, address, port = await self.checked_address(url)
            parts = urlsplit(url)
            netloc = f"[{address}]" if ":" in address else address
            target = parts._replace(netloc=f"{netloc}:{port}").geturl()
            try:
                async with client.stream(
                    "GET",
                    target,
                    headers={"Host": parts.netloc},
                    extensions={"sni_hostname": host},
                    follow_redirects=False,
                    timeout=self.timeout_s,
                ) as r:
                    if r.is_redirect:
                        location = r.headers.get("location")
                        if not location:
                            raise FetchFailed(f"{host} answered a redirect with no address.")
                        url = urljoin(url, location)
                        continue
                    if r.status_code != 200:
                        raise FetchFailed(f"{host} answered {r.status_code}.")
                    body = bytearray()
                    async for chunk in r.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_bytes:
                            raise FetchFailed(f"The document is larger than {self.max_bytes // 1024} KB.")
                    return bytes(body)
            except httpx.HTTPError as e:
                raise FetchFailed(f"{host} did not answer.") from e
        raise FetchFailed(f"More than {self.max_redirects} redirects.")
