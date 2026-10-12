"""The egress policy: what tools-service may reach, for discovery and for calls alike.

Two checks. Before a request, the URL must be https to a host on the tenant's allow-list. When the connection opens,
the host is resolved once, every address must be allowed, and the connection goes to that checked address, so DNS
cannot rebind between the check and the connect. Private ranges are reachable only when the tenant lists them.

The listing rules come first. Hosts are bare lower-case DNS names. Ranges are private networks
in CIDR form; loopback, link-local and cloud-metadata addresses are never listable, because no listing makes them
safe to reach.
"""

from __future__ import annotations

import asyncio
import http.cookiejar
import ipaddress
import re
import socket
from collections.abc import Iterable
from contextvars import ContextVar
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

import httpcore
import httpx

from .store.egress import EgressStore

HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")
CGNAT = ipaddress.IPv4Network("100.64.0.0/10")


class EgressDenied(ValueError):
    """A host, range or address the policy refuses; the message names the host, never resolved addresses."""


def listable_host(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    if not HOSTNAME.match(host):
        raise EgressDenied(f"{value!r} is not a host name. List the name alone, e.g. api.example.com.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise EgressDenied(f"{value} is an address. List the host name; private addresses are listed as ranges.")


def listable_range(value: str) -> str:
    try:
        net = ipaddress.ip_network(value.strip(), strict=True)
    except ValueError as e:
        raise EgressDenied(f"{value!r} is not a network in CIDR form, e.g. 10.20.0.0/16.") from e
    if net.is_loopback or net.is_link_local or net.is_multicast or net.is_unspecified:
        raise EgressDenied(f"{net} is loopback, link-local or multicast, which tools-service never reaches.")
    cgnat = net.version == 4 and CGNAT.supernet_of(ipaddress.IPv4Network(str(net)))
    private = net.is_private or cgnat
    if not private:
        raise EgressDenied(f"{net} is public. Only private networks are listed; public hosts need no range.")
    return str(net)


# The policy every outbound request follows: discovery (OpenAPI fetch, MCP) and the http executor alike.

ALWAYS_DENIED = (
    ipaddress.ip_network("169.254.169.254/32"),
    ipaddress.ip_network("fd00:ec2::254/128"),
)
CURRENT_TENANT: ContextVar[str] = ContextVar("egress_tenant")


class Resolver(Protocol):
    async def resolve(self, host: str, port: int) -> list[str]: ...


class SystemResolver:
    async def resolve(self, host: str, port: int) -> list[str]:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return list(dict.fromkeys(str(info[4][0]) for info in infos))


class OverrideResolver:
    """Dev only (Settings refuses `egress_resolve` elsewhere): fixed answers for some names, DNS for the rest. An
    answer is `address` or `address:port`; the port replaces 443 when dialling, so a fake that cannot listen on 443
    is still reached through an ordinary https URL. The answers still pass the address check, so a fake reached this
    way must sit in a listed range."""

    def __init__(self, overrides: dict[str, str], fallback: Resolver | None = None) -> None:
        self.overrides: dict[str, tuple[str, int | None]] = {}
        for host, answer in overrides.items():
            address, sep, port = answer.rpartition(":") if answer.count(":") == 1 else ("", "", "")
            self.overrides[host.lower()] = (address, int(port)) if sep else (answer, None)
        self.fallback: Resolver = fallback or SystemResolver()

    async def resolve(self, host: str, port: int) -> list[str]:
        fixed = self.overrides.get(host.lower())
        return [fixed[0]] if fixed else await self.fallback.resolve(host, port)

    def dial_port(self, host: str, port: int) -> int:
        fixed = self.overrides.get(host.lower())
        return fixed[1] if fixed and fixed[1] else port


def address_allowed(address: str, ranges: list[str]) -> bool:
    """Loopback, link-local, multicast, unspecified and cloud-metadata addresses never; private, CGNAT and reserved
    ones only inside a listed range; public ones always (the host was already checked against the list)."""
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


class EgressPolicy:
    def __init__(self, store: EgressStore, resolver: Resolver | None = None) -> None:
        self.store = store
        self.resolver: Resolver = resolver or SystemResolver()

    async def check_url(self, tenant_id: str, url: str) -> str:
        """Before any request: https on the default port, to a host on the tenant's list. Returns the host."""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https":
            raise EgressDenied(f"{host or url} is not https; tools-service only calls https.")
        if parts.port not in (None, 443):
            raise EgressDenied(f"{host} port {parts.port} is not allowed; only 443.")
        if not await self.store.host_allowed(tenant_id, host):
            raise EgressDenied(f"{host} is not on the egress allow-list.")
        return host

    def dial_port(self, host: str, port: int) -> int:
        return self.resolver.dial_port(host, port) if isinstance(self.resolver, OverrideResolver) else port

    async def dial_address(self, tenant_id: str, host: str, port: int) -> str:
        """At connect time: resolve once and refuse unless every address is allowed. The caller connects to the
        address returned, never to the name again, so DNS cannot answer differently between check and connect."""
        if not await self.store.host_allowed(tenant_id, host):
            raise EgressDenied(f"{host} is not on the egress allow-list.")
        addresses = await self.resolver.resolve(host, port)
        ranges = await self.store.ranges(tenant_id)
        if not addresses or not all(address_allowed(a, ranges) for a in addresses):
            raise EgressDenied(f"{host} resolves to an address tools-service may not reach.")
        return addresses[0]


class EgressBackend(httpcore.AsyncNetworkBackend):
    """httpcore's network backend with the policy at the one place a connection is opened. TLS still verifies the
    hostname: httpcore takes the server name from the request, not from the address dialled."""

    def __init__(self, policy: EgressPolicy, inner: httpcore.AsyncNetworkBackend | None = None) -> None:
        self.policy = policy
        # httpcore exports AnyIOBackend without its base class in the stubs pyright reads.
        self.inner = inner or cast(httpcore.AsyncNetworkBackend, httpcore.AnyIOBackend())

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            address = await self.policy.dial_address(CURRENT_TENANT.get(), host, port)
        except OSError as e:
            # A name that does not resolve fails here, before httpcore maps errors; as its ConnectError it reaches
            # callers as httpx.ConnectError (a connect failure on our side), not as a raw socket error and a 500.
            raise httpcore.ConnectError(f"{host} did not resolve") from e
        port = self.policy.dial_port(host, port)
        return await self.inner.connect_tcp(address, port, timeout, local_address, socket_options)

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: Iterable[Any] | None = None
    ) -> httpcore.AsyncNetworkStream:
        raise EgressDenied("tools-service never connects to a local socket.")

    async def sleep(self, seconds: float) -> None:
        await self.inner.sleep(seconds)


class _NoCookies(http.cookiejar.DefaultCookiePolicy):
    """Refuses to store or send any cookie. The egress client is shared by every tenant, workflow and caller, so a
    Set-Cookie from one call would otherwise ride on the next call to that host, whoever makes it."""

    def set_ok(self, cookie: http.cookiejar.Cookie, request: Any) -> bool:
        return False

    def return_ok(self, cookie: http.cookiejar.Cookie, request: Any) -> bool:
        return False


def no_cookie_jar() -> http.cookiejar.CookieJar:
    return http.cookiejar.CookieJar(policy=_NoCookies())


def egress_client(
    policy: EgressPolicy, *, ca_file: str | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """The one client discovery and the executors call through. No environment proxies (a proxy would be dialled
    instead of the checked address), no redirects (a redirect would reach a URL nobody checked) and no cookie jar (an
    upstream's Set-Cookie is dropped; only an operation's own Cookie header is sent). `ca_file` adds an internal CA to
    the trusted ones. `transport` replaces the policy's connection pool in tests only."""
    if transport is None:
        ssl_context = httpx.create_ssl_context()
        if ca_file:
            ssl_context.load_verify_locations(cafile=ca_file)
        pooled = httpx.AsyncHTTPTransport(trust_env=False)
        # httpx exposes no network-backend option; the pool is replaced with one on the policy's backend.
        pooled._pool = httpcore.AsyncConnectionPool(  # pyright: ignore[reportPrivateUsage]
            ssl_context=ssl_context, network_backend=EgressBackend(policy)
        )
        transport = pooled
    return httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False, cookies=no_cookie_jar())
