"""`uv run python -m ops_signin.fake_idp --port 8790 [--dns-port 8791]`: the fake identity provider on localhost, and
with `--dns-port` its fake DNS server."""

from __future__ import annotations

import argparse

import uvicorn

from .app import create_app
from .dns import FakeDns


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake OIDC and SAML identity provider (tests and dev only)")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--base", help="public origin; defaults to http://127.0.0.1:<port>")
    parser.add_argument("--dns-port", type=int, help="also answer DNS TXT queries on this UDP port")
    args = parser.parse_args()
    base = args.base or f"http://127.0.0.1:{args.port}"
    fake_dns = FakeDns()
    if args.dns_port:
        fake_dns.serve(args.dns_port)
    uvicorn.run(create_app(base, fake_dns), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
