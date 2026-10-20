"""Runs a fake bank for a Node ui use case: prints one JSON line with what tools-service needs to reach it (its
settings, the private range to list, the host), then serves until stdin closes or it is signalled.

Two banks answer as `https://api.bank.test`: the Statements API (fake_bank_https), the default, and with
OPS_FAKE_BANK_APP=core the core-banking system (services/tools-service/scripts/fake_bank: customers, accounts, holds,
notes, and its sign-in routes), which a levy use case needs, also on https. The core bank also serves the same app as
`https://mtls.bank.test` on a listener that refuses any handshake without a client certificate its own CA signed
(c-330); the JSON line names that host, the CA and the client certificate's files."""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from bank_certificates import MTLS_HOST
from bank_certificates import make as make_certificates
from fake_bank_https import HOST, _certificate, fake_bank, private_address

ROOT = Path(__file__).resolve().parents[3]


def _start(app: object, address: str, **ssl: Any) -> tuple[Any, threading.Thread, int]:
    import uvicorn  # noqa: PLC0415 - the agents-service environment this runs under has it

    with socket.socket() as s:
        s.bind((address, 0))
        port = int(s.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, host=address, port=port, log_level="warning", **ssl))  # pyright: ignore[reportArgumentType]
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    return server, thread, port


def serve_core_bank() -> None:
    sys.path.insert(0, str(ROOT / "services" / "tools-service" / "scripts"))
    from fake_bank.app import app  # noqa: PLC0415 - a script folder, not a package on the path

    with tempfile.TemporaryDirectory() as tmp:
        cert, key = _certificate(Path(tmp))
        mtls = make_certificates(Path(tmp))
        address = private_address()
        servers = [
            _start(app, address, ssl_certfile=str(cert), ssl_keyfile=str(key)),
            _start(
                app,
                address,
                ssl_certfile=str(mtls["server_cert"]),
                ssl_keyfile=str(mtls["server_key"]),
                ssl_ca_certs=str(mtls["ca"]),
                ssl_cert_reqs=ssl.CERT_REQUIRED,
                # TLS 1.2, as many bank systems still serve mutual TLS: the refusal of a missing certificate is then
                # part of the handshake. Under TLS 1.3 it comes after it, and reaches a client as a reset.
                ssl_version=ssl.PROTOCOL_TLSv1_2,
            ),
        ]
        (_, _, port), (_, _, mtls_port) = servers
        resolve = {HOST: f"{address}:{port}", MTLS_HOST: f"{address}:{mtls_port}"}
        settings = {"OPS_EGRESS_CA_FILE": str(cert), "OPS_EGRESS_RESOLVE": json.dumps(resolve)}
        files = {k: str(v) for k, v in mtls.items() if k in ("ca", "client_cert", "client_key")}
        line = {"settings": settings, "range": f"{address}/32", "host": HOST, "mtlsHost": MTLS_HOST, "mtls": files}
        print(json.dumps(line), flush=True)
        try:
            sys.stdin.read()
        finally:
            for server, thread, _ in servers:
                server.should_exit = True
                thread.join(10)


if os.environ.get("OPS_FAKE_BANK_APP") == "core":
    serve_core_bank()
else:
    with fake_bank() as bank:
        print(json.dumps({"settings": bank.settings, "range": bank.range, "host": HOST}), flush=True)
        # The harness holds stdin open; it closes when the harness stops this process or exits.
        sys.stdin.read()
