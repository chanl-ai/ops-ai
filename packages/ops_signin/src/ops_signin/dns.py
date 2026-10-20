"""Domain proof by DNS: a workspace publishes `ops-ai-verify=<token>` as a TXT record on its email domain, and
`TxtResolver.has_record` reads the domain's TXT records to see it (RFC 1464 attribute=value strings).

The resolver asks the servers it is given (`host:port`, as a test or a bank's internal resolver needs) or, given none,
the system's. It keeps no cache of its own, so a record published a moment ago is seen as soon as the servers see it.
"""

from __future__ import annotations

from dataclasses import dataclass

import dns.asyncresolver
import dns.exception
import dns.nameserver
import dns.resolver

RECORD_PREFIX = "ops-ai-verify="


def record_value(token: str) -> str:
    """The TXT value a workspace publishes for its claim token."""
    return f"{RECORD_PREFIX}{token}"


@dataclass(frozen=True)
class TxtAnswer:
    """What DNS held for the domain: whether the expected value was there, and every TXT value seen."""

    found: bool
    values: list[str]
    error: str | None = None


class TxtResolver:
    def __init__(self, servers: list[str] | None = None, *, timeout_s: float = 5.0) -> None:
        self._servers = servers or []
        self._timeout_s = timeout_s

    def _resolver(self) -> dns.asyncresolver.Resolver:
        if not self._servers:
            r = dns.asyncresolver.Resolver()
        else:
            r = dns.asyncresolver.Resolver(configure=False)
            r.nameservers = [_nameserver(s) for s in self._servers]
        r.lifetime = self._timeout_s
        r.cache = None
        return r

    async def values(self, domain: str) -> TxtAnswer:
        try:
            answer = await self._resolver().resolve(domain, "TXT")
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return TxtAnswer(found=False, values=[])
        except dns.exception.DNSException as e:
            return TxtAnswer(found=False, values=[], error=type(e).__name__)
        # A TXT record is one or more strings of at most 255 bytes; a long value is split, so join them back.
        values = [b"".join(r.strings).decode(errors="replace") for r in answer]  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType,reportUnknownArgumentType]
        return TxtAnswer(found=False, values=sorted(values))

    async def has_record(self, domain: str, token: str) -> TxtAnswer:
        got = await self.values(domain)
        return TxtAnswer(found=record_value(token) in got.values, values=got.values, error=got.error)


def _nameserver(server: str) -> dns.nameserver.Do53Nameserver:
    host, _, port = server.rpartition(":") if ":" in server else (server, "", "53")
    return dns.nameserver.Do53Nameserver(host, int(port or 53))
