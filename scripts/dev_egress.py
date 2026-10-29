"""Lists this machine's private address and the dev mail and bank hosts on the shared stack's egress allow-list.

tools-service reaches GreenMail (mail.harborpine.test), Mailpit (smtp.harborpine.test) and the fake bank
(api.bank.test) at this machine's private address (scripts/stack.sh, OPS_EGRESS_RESOLVE). That address changes when
the network does, and an allow-list naming yesterday's address refuses every mail and bank call. `make up` runs this
after the services start: it signs in as the Security team's admin and adds, through tools-service's own egress API,
whatever is missing. Run alone: `uv run python scripts/dev_egress.py`. Dev stacks only; prints what it changed.
"""

from __future__ import annotations

import os
import socket
import sys

import httpx

PLATFORM = f"http://127.0.0.1:{os.environ.get('OPS_PLATFORM_PORT', '8710')}"
TOOLS = f"http://127.0.0.1:{os.environ.get('OPS_TOOLS_PORT', '8720')}"
SECURITY_ADMIN, PASSWORD = "s.adeyemi@harborpine.example", "northfield-demo"
HOSTS = {
    "mail.harborpine.test": "dev GreenMail",
    "smtp.harborpine.test": "dev Mailpit",
    "api.bank.test": "dev fake bank",
}


def private_address() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("10.255.255.255", 1))
        return str(s.getsockname()[0])


def host_ip(name: str) -> str | None:
    if not name or name in {"127.0.0.1", "localhost"}:
        return None
    try:
        return str(socket.getaddrinfo(name, None, socket.AF_INET)[0][4][0])
    except OSError:
        return None


def headers() -> dict[str, str]:
    """A Security admin's platform token, or the dev header on a stack that runs dev sign-in."""
    try:
        r = httpx.post(f"{PLATFORM}/v1/auth/sign-in", json={"email": SECURITY_ADMIN, "password": PASSWORD}, timeout=10)
    except httpx.HTTPError:
        r = None
    if r is not None and r.status_code == 200:
        return {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": "team_security"}
    return {"X-Dev-User": "Sam Adeyemi", "X-Team-Id": "team_security"}


def main() -> int:
    h = headers()
    listed = httpx.get(f"{TOOLS}/v1/egress", headers=h, timeout=10)
    if listed.status_code != 200:
        print(f"dev egress: cannot read the allow-list ({listed.status_code}): {listed.text[:200]}")
        return 1
    have = listed.json()["data"]
    hosts = {x["host"] for x in have["hosts"]}
    ranges = {x["cidr"] for x in have["ranges"]}
    wanted = [("hosts", host, note) for host, note in HOSTS.items() if host not in hosts]
    cidr = f"{private_address()}/32"
    if cidr not in ranges:
        wanted.append(("ranges", cidr, "this machine's address, for the dev mail and bank fakes"))
    for label, name in (
        ("greenmail", os.environ.get("OPS_GREENMAIL_HOST", "")),
        ("mailpit", os.environ.get("OPS_MAILPIT_HOST", "")),
        ("fake bank", "api.bank.test"),
    ):
        addr = host_ip(name)
        sidecar = f"{addr}/32" if addr else ""
        if sidecar and sidecar not in ranges:
            wanted.append(("ranges", sidecar, f"{label} side container"))
    for kind, value, note in wanted:
        r = httpx.post(f"{TOOLS}/v1/egress/{kind}", json={"value": value, "note": note}, headers=h, timeout=10)
        if r.status_code not in (200, 201):
            print(f"dev egress: could not add {value}: {r.status_code} {r.text[:200]}")
            return 1
        print(f"dev egress: added {value}")
    if not wanted:
        print(f"dev egress: {cidr} and the dev mail and bank hosts are listed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
