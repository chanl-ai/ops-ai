"""Serve the fake bank on https as api.bank.test and print the two tools-service settings that reach it.

The certificate is self-signed for api.bank.test and doubles as the CA tools-service trusts (OPS_EGRESS_CA_FILE);
OPS_EGRESS_RESOLVE maps the name to this machine's private address and port, so the module's URL stays an ordinary
https one and passes the same egress checks a real bank's would. The private range still has to be on the egress list.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
import sys
from pathlib import Path

import uvicorn

HOST = "api.bank.test"
PORT = 8745


def private_address() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        address = str(s.getsockname()[0])
    finally:
        s.close()
    if not ipaddress.ip_address(address).is_private or address.startswith("127."):
        sys.exit(f"no private network address to serve on (found {address})")
    return address


def main() -> None:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".run/fake-bank").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    cert, key = folder / "bank.crt", folder / "bank.key"
    if not cert.exists():
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "ec",
                "-pkeyopt",
                "ec_paramgen_curve:prime256v1",
                "-nodes",
                "-days",
                "30",
                "-subj",
                f"/CN={HOST}",
                "-addext",
                f"subjectAltName=DNS:{HOST}",
                "-addext",
                "basicConstraints=critical,CA:TRUE",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            check=True,
            capture_output=True,
        )
    address = private_address()
    print(f"OPS_EGRESS_CA_FILE={cert}")
    print(f"OPS_EGRESS_RESOLVE={json.dumps({HOST: f'{address}:{PORT}'})}")
    print(f"egress: host {HOST}, range {address}/32", flush=True)
    uvicorn.run(
        "fake_bank.app:app", host=address, port=PORT, ssl_certfile=str(cert), ssl_keyfile=str(key), log_level="warning"
    )


if __name__ == "__main__":
    main()
