"""The egress policy: what tools-service may reach, for discovery and for calls alike.

Two checks. Before a request, the URL must be https to a host on the tenant's allow-list. When the connection opens,
the host is resolved once, every address must be allowed, and the connection goes to that checked address, so DNS
cannot rebind between the check and the connect. Private ranges are reachable only when the tenant lists them.

A host passes the first check when the tenant lists it, when the request is a plugin's own and the plugin declares it
(`for_tenant(..., hosts=)`), or when the account's `egressNewHosts` policy is `any_public`. None of these changes the
second check: an address that is private, loopback, link-local or cloud metadata is refused whatever named the host.

The listing rules come first. Hosts are bare lower-case DNS names. Ranges are private networks
in CIDR form; loopback, link-local and cloud-metadata addresses are never listable, because no listing makes them
safe to reach.
"""

from __future__ import annotations

import http.cookiejar
import ipaddress
import os
import re
import ssl
import tempfile
import time
from collections.abc import Callable, Iterable
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

import httpcore
import httpx

from ops_identity import ServiceCallError, ServiceUnreachable
from ops_service_kit.public_address import CGNAT, Resolver, SystemResolver, address_allowed

from .store.egress import EgressStore

HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")


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

# Said to people, on the Connect window and the tool page: what is wrong and who fixes it, with no network terms.
NOT_ALLOWED = "{host} is not an allowed address yet. The Security team allows it on the Egress page in Settings."

# The request extension that names the tenant an outbound request is made for. Every request through the egress
# client carries it (`for_tenant`); the transport dials with that tenant's allow-list, and refuses a request without.
TENANT_EXTENSION = "ops_tenant"


# The request extension carrying a client certificate to present: an object with `fingerprint`, `cert_pem`,
# `key_pem` and `ca_pem` (ops_tools.auth.ClientCertificate).
CERTIFICATE_EXTENSION = "ops_client_certificate"
# The request extension naming the hosts a plugin declares, which its own requests reach without the tenant listing
# them. Set only by this service's code for a plugin's calls and sign-ins, never from a caller's input.
HOSTS_EXTENSION = "ops_plugin_hosts"


def for_tenant(tenant_id: str, certificate: Any = None, hosts: Iterable[str] = ()) -> dict[str, Any]:
    """The `extensions` an outbound request passes so the egress transport dials for `tenant_id`, presenting
    `certificate` on the TLS handshake when one is given, and reaching `hosts` (a plugin's own) unlisted."""
    out: dict[str, Any] = {TENANT_EXTENSION: tenant_id}
    if certificate is not None:
        out[CERTIFICATE_EXTENSION] = certificate
    if scoped := plugin_hosts(hosts):
        out[HOSTS_EXTENSION] = scoped
    return out


def plugin_hosts(hosts: Iterable[str]) -> frozenset[str]:
    """The host names of `hosts` a plugin's request may reach unlisted: names only, never an address."""
    out: set[str] = set()
    for h in hosts:
        try:
            out.add(listable_host(h))
        except EgressDenied:
            continue
    return frozenset(out)


NewHostsMode = Literal["ask_security", "builders", "any_public", "block"]
NEW_HOSTS_MODES: tuple[NewHostsMode, ...] = ("ask_security", "builders", "any_public", "block")
NEW_HOSTS_FRESH_S = 5.0


class Platform(Protocol):
    async def get(self, path: str, *, tenant: str) -> Any: ...


class NewHosts:
    """The account's `egressNewHosts` policy, read from platform-service with this service's `settings:view` token and
    kept NEW_HOSTS_FRESH_S seconds. A policy that cannot be read counts as `ask_security`, the default, so an outage
    never opens public hosts nor lets a builder list one."""

    def __init__(self, platform: Platform, clock: Callable[[], float] = time.monotonic) -> None:
        self.platform = platform
        self.clock = clock
        self._kept: dict[str, tuple[float, NewHostsMode]] = {}

    async def mode(self, tenant_id: str) -> NewHostsMode:
        kept = self._kept.get(tenant_id)
        if kept is not None and self.clock() - kept[0] < NEW_HOSTS_FRESH_S:
            return kept[1]
        try:
            data = await self.platform.get("/v1/policies/egressNewHosts", tenant=tenant_id)
            value = data.get("value")
        except (ServiceCallError, ServiceUnreachable, KeyError, TypeError, ValueError, AttributeError):
            return "ask_security"
        mode: NewHostsMode = value if value in NEW_HOSTS_MODES else "ask_security"
        self._kept[tenant_id] = (self.clock(), mode)
        return mode


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


def _is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


class EgressPolicy:
    def __init__(self, store: EgressStore, resolver: Resolver | None = None, new_hosts: NewHosts | None = None) -> None:
        """`new_hosts` is the account's egressNewHosts policy; without it every unlisted host is refused."""
        self.store = store
        self.resolver: Resolver = resolver or SystemResolver()
        self.new_hosts = new_hosts

    async def host_passes(self, tenant_id: str, host: str, also: frozenset[str] = frozenset()) -> bool:
        """Whether a host name passes the list check: one of `also` (the calling plugin's own hosts), listed by the
        tenant, or any host name at all under `any_public`. An address typed as the host never passes unlisted."""
        if host in also or await self.store.host_allowed(tenant_id, host):
            return True
        if self.new_hosts is None or not HOSTNAME.match(host) or _is_address(host):
            return False
        return await self.new_hosts.mode(tenant_id) == "any_public"

    async def check_url(self, tenant_id: str, url: str, also: Iterable[str] = ()) -> str:
        """Before any request: https on the default port, to a host that passes `host_passes`. Returns the host."""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https":
            raise EgressDenied(f"{host or url} is not https; tools-service only calls https.")
        if parts.port not in (None, 443):
            raise EgressDenied(f"{host} port {parts.port} is not allowed; only 443.")
        if not await self.host_passes(tenant_id, host, plugin_hosts(also)):
            raise EgressDenied(NOT_ALLOWED.format(host=host))
        return host

    def dial_port(self, host: str, port: int) -> int:
        return self.resolver.dial_port(host, port) if isinstance(self.resolver, OverrideResolver) else port

    async def dial_address(self, tenant_id: str, host: str, port: int, also: frozenset[str] = frozenset()) -> str:
        """At connect time: resolve once and refuse unless every address is allowed. The caller connects to the
        address returned, never to the name again, so DNS cannot answer differently between check and connect."""
        if not await self.host_passes(tenant_id, host, also):
            raise EgressDenied(NOT_ALLOWED.format(host=host))
        addresses = await self.resolver.resolve(host, port)
        ranges = await self.store.ranges(tenant_id)
        if not addresses or not all(address_allowed(a, ranges) for a in addresses):
            raise EgressDenied(f"{host} resolves to an address tools-service may not reach.")
        return addresses[0]


class EgressBackend(httpcore.AsyncNetworkBackend):
    """httpcore's network backend with the policy at the one place a connection is opened. TLS still verifies the
    hostname: httpcore takes the server name from the request, not from the address dialled."""

    def __init__(
        self,
        policy: EgressPolicy,
        tenant_id: str,
        inner: httpcore.AsyncNetworkBackend | None = None,
        also: frozenset[str] = frozenset(),
    ) -> None:
        """`also` is the plugin's own hosts, for a pool that serves only that plugin's requests."""
        self.policy = policy
        self.tenant_id = tenant_id
        self.also = also
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
            address = await self.policy.dial_address(self.tenant_id, host, port, self.also)
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
    no tenant is refused before anything is dialled. A plugin's requests, which name its hosts, get a pool of their own
    per tenant and host set, so a connection that reached a plugin's host unlisted serves no other request."""

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
        # A pool per tenant and client certificate: a connection that presented a certificate is never reused
        # for a call that did not ask for it, nor one for another certificate.
        self.certificate_pools: dict[tuple[str, str], httpx.AsyncHTTPTransport] = {}
        self.plugin_pools: dict[tuple[str, str, frozenset[str]], httpx.AsyncHTTPTransport] = {}

    def _pooled(self, tenant_id: str, context: Any, also: frozenset[str] = frozenset()) -> httpx.AsyncHTTPTransport:
        pooled = httpx.AsyncHTTPTransport(trust_env=False)
        # httpx exposes no network-backend option; the pool is replaced with one on the policy's backend.
        pooled._pool = httpcore.AsyncConnectionPool(  # pyright: ignore[reportPrivateUsage]
            ssl_context=context, network_backend=EgressBackend(self.policy, tenant_id, self.network, also)
        )
        return pooled

    def _context(self, certificate: Any) -> Any:
        if certificate is None:
            return self.ssl_context
        return certificate_context(self.ca_file, certificate.cert_pem, certificate.key_pem, certificate.ca_pem)

    def _pool(
        self, tenant_id: str, certificate: Any = None, also: frozenset[str] = frozenset()
    ) -> httpx.AsyncHTTPTransport:
        if also:
            key = (tenant_id, str(certificate.fingerprint) if certificate is not None else "", also)
            if key not in self.plugin_pools:
                self.plugin_pools[key] = self._pooled(tenant_id, self._context(certificate), also)
            return self.plugin_pools[key]
        if certificate is None:
            if tenant_id not in self.pools:
                self.pools[tenant_id] = self._pooled(tenant_id, self.ssl_context)
            return self.pools[tenant_id]
        cert_key = (tenant_id, str(certificate.fingerprint))
        if cert_key not in self.certificate_pools:
            self.certificate_pools[cert_key] = self._pooled(tenant_id, self._context(certificate))
        return self.certificate_pools[cert_key]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        tenant_id = request.extensions.get(TENANT_EXTENSION)
        if not tenant_id:
            raise EgressDenied("An outbound request names no tenant, so no allow-list applies; nothing is dialled.")
        also = request.extensions.get(HOSTS_EXTENSION)
        pool = self._pool(
            str(tenant_id),
            request.extensions.get(CERTIFICATE_EXTENSION),
            cast(frozenset[str], also) if isinstance(also, frozenset) else frozenset[str](),
        )
        return await pool.handle_async_request(request)

    async def aclose(self) -> None:
        for pool in [*self.pools.values(), *self.certificate_pools.values(), *self.plugin_pools.values()]:
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
    """The transport an outbound client dials through, for a client built with its own base URL and hooks (Graph);
    `ca_file` as for `egress_client`."""
    ssl_context = httpx.create_ssl_context()
    if ca_file:
        ssl_context.load_verify_locations(cafile=ca_file)
    return EgressTransport(policy, ssl_context, ca_file=ca_file)
