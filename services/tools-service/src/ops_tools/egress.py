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
import os
import re
import socket
import ssl
import tempfile
from collections.abc import Iterable
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
# The request extension that names the tenant an outbound request is made for. Every request through the egress
# client carries it (`for_tenant`); the transport dials with that tenant's allow-list, and refuses a request without.
TENANT_EXTENSION = "ops_tenant"


# The request extension carrying a client certificate to present (c-330): an object with `fingerprint`, `cert_pem`,
# `key_pem` and `ca_pem` (ops_tools.auth.ClientCertificate).
CERTIFICATE_EXTENSION = "ops_client_certificate"


def for_tenant(tenant_id: str, certificate: Any = None) -> dict[str, Any]:
    """The `extensions` an outbound request passes so the egress transport dials for `tenant_id`, presenting
    `certificate` on the TLS handshake when one is given."""
    return {TENANT_EXTENSION: tenant_id, **({CERTIFICATE_EXTENSION: certificate} if certificate is not None else {})}


def certificate_context(
    base_ca_file: str | None, cert_pem: str | None, key_pem: str | None, ca_pem: str | None
) -> ssl.SSLContext:
    """A TLS context trusting `ca_pem` too and, given both, presenting the client certificate. `load_cert_chain` reads
    files only, so the key is written to a temporary file readable by this process alone and removed before this
    returns."""
    context = httpx.create_ssl_context()
    if base_ca_file:
        context.load_verify_locations(cafile=base_ca_file)
    if ca_pem:
        context.load_verify_locations(cadata=ca_pem)
    if not cert_pem or not key_pem:
        return context
    fd, path = tempfile.mkstemp(prefix="ops-cert-", suffix=".pem")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(cert_pem.strip() + "\n" + key_pem.strip() + "\n")
        context.load_cert_chain(path)
    finally:
        os.unlink(path)
    return context


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

    def __init__(self, policy: EgressPolicy, tenant_id: str, inner: httpcore.AsyncNetworkBackend | None = None) -> None:
        self.policy = policy
        self.tenant_id = tenant_id
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
            address = await self.policy.dial_address(self.tenant_id, host, port)
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


class EgressTransport(httpx.AsyncBaseTransport):
    """One connection pool per tenant, each dialling through that tenant's allow-list, picked by the tenant the request
    names (`for_tenant`). A connection opened for one tenant is never reused for another, and a request that names
    no tenant is refused before anything is dialled."""

    def __init__(
        self,
        policy: EgressPolicy,
        ssl_context: Any,
        *,
        network: httpcore.AsyncNetworkBackend | None = None,
        ca_file: str | None = None,
    ) -> None:
        """`network` replaces the sockets each tenant's backend dials through, in tests only. `ca_file` is the internal
        CA a client-certificate pool trusts as well."""
        self.policy = policy
        self.ssl_context = ssl_context
        self.network = network
        self.ca_file = ca_file
        self.pools: dict[str, httpx.AsyncHTTPTransport] = {}
        # A pool per tenant and client certificate (c-330): a connection that presented a certificate is never reused
        # for a call that did not ask for it, nor one for another certificate.
        self.certificate_pools: dict[tuple[str, str], httpx.AsyncHTTPTransport] = {}

    def _pooled(self, tenant_id: str, context: Any) -> httpx.AsyncHTTPTransport:
        pooled = httpx.AsyncHTTPTransport(trust_env=False)
        # httpx exposes no network-backend option; the pool is replaced with one on the policy's backend.
        pooled._pool = httpcore.AsyncConnectionPool(  # pyright: ignore[reportPrivateUsage]
            ssl_context=context, network_backend=EgressBackend(self.policy, tenant_id, self.network)
        )
        return pooled

    def _pool(self, tenant_id: str, certificate: Any = None) -> httpx.AsyncHTTPTransport:
        if certificate is None:
            if tenant_id not in self.pools:
                self.pools[tenant_id] = self._pooled(tenant_id, self.ssl_context)
            return self.pools[tenant_id]
        key = (tenant_id, str(certificate.fingerprint))
        if key not in self.certificate_pools:
            context = certificate_context(self.ca_file, certificate.cert_pem, certificate.key_pem, certificate.ca_pem)
            self.certificate_pools[key] = self._pooled(tenant_id, context)
        return self.certificate_pools[key]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        tenant_id = request.extensions.get(TENANT_EXTENSION)
        if not tenant_id:
            raise EgressDenied("An outbound request names no tenant, so no allow-list applies; nothing is dialled.")
        return await self._pool(str(tenant_id), request.extensions.get(CERTIFICATE_EXTENSION)).handle_async_request(
            request
        )

    async def aclose(self) -> None:
        for pool in [*self.pools.values(), *self.certificate_pools.values()]:
            await pool.aclose()


def egress_client(
    policy: EgressPolicy, *, ca_file: str | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """The one client discovery and the executors call through; each request names its tenant (`for_tenant`). No
    environment proxies (a proxy would be dialled instead of the checked address), no redirects (a redirect would reach
    a URL nobody checked) and no cookie jar (an upstream's Set-Cookie is dropped; only an operation's own Cookie header
    is sent). `ca_file` adds an internal CA to the trusted ones. `transport` replaces the pools in tests only."""
    if transport is None:
        transport = egress_transport(policy, ca_file=ca_file)
    return httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False, cookies=no_cookie_jar())


def egress_transport(policy: EgressPolicy, *, ca_file: str | None = None) -> EgressTransport:
    """The transport an outbound client dials through, for a client built with its own base URL and hooks (Graph,
    c-228); `ca_file` as for `egress_client`."""
    ssl_context = httpx.create_ssl_context()
    if ca_file:
        ssl_context.load_verify_locations(cafile=ca_file)
    return EgressTransport(policy, ssl_context, ca_file=ca_file)
