"""The address of the caller behind the install's proxies, for limits counted per address (hosted form submissions,
assistant registrations and sign-in starts). Behind Caddy or the embed app every request's peer is the proxy, so a
limit keyed on the peer would count everyone as one caller."""

from __future__ import annotations

import ipaddress

from starlette.requests import Request


def client_address(request: Request, trusted: list[str]) -> str:
    """The right-most X-Forwarded-For entry outside the trusted proxies (CIDRs, `forms_trusted_proxies`), read from
    the raw header; the peer only when there is no header. A left-hand entry a client wrote itself is never reached."""
    nets = [ipaddress.ip_network(n, strict=False) for n in trusted]

    def inside(raw: str) -> bool:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return False
        return any(ip in n for n in nets)

    chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    for hop in reversed(chain):
        if not inside(hop):
            return hop
    return chain[0] if chain else (request.client.host if request.client else "unknown")
