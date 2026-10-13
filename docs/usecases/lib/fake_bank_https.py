"""A fake bank system on https, for use cases that drive tools-service's discovery and calls end to end.

It serves an OpenAPI document, the operations it describes, and an MCP server, on this machine's private address
with a self-signed certificate for `api.bank.test`. tools-service reaches it as any bank system: the use case lists
the host and the private range, gives tools-service the certificate as its CA (OPS_EGRESS_CA_FILE) and maps the
name to the address and port (OPS_EGRESS_RESOLVE, dev only), so the URL stays `https://api.bank.test` and passes
the same checks a real one does.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import ssl
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

HOST = "api.bank.test"
SLOW_S = 3.0


def private_address() -> str:
    """This machine's address on its private network: the source address of a route out, never sent anywhere."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        address = str(s.getsockname()[0])
    finally:
        s.close()
    if not ipaddress.ip_address(address).is_private or address.startswith("127."):
        raise RuntimeError(f"no private network address to serve the fake bank on (found {address})")
    return address


def _certificate(folder: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOST)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = folder / "bank.crt", folder / "bank.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return cert_file, key_file


SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Statements API", "version": "2.3.0"},
    "servers": [{"url": f"https://{HOST}/v1"}],
    "components": {"securitySchemes": {"statementsKey": {"type": "apiKey", "in": "header", "name": "X-Api-Key"}}},
    "paths": {
        "/accounts/{accountId}": {
            "get": {
                "operationId": "getAccount",
                "summary": "Balance for an account",
                "parameters": [{"name": "accountId", "in": "path", "required": True, "schema": {"type": "string"}}],
            }
        },
        "/statements/latest": {
            "get": {"operationId": "latestStatement", "summary": "The latest statement", "security": [{"statementsKey": []}]}
        },
    },
}


@dataclass
class FakeBank:
    address: str
    port: int
    ca_file: Path
    received: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    mcp_tools: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    @property
    def settings(self) -> dict[str, str]:
        """What tools-service needs to reach this fake as `https://api.bank.test`."""
        return {"OPS_EGRESS_CA_FILE": str(self.ca_file), "OPS_EGRESS_RESOLVE": json.dumps({HOST: f"{self.address}:{self.port}"})}

    @property
    def range(self) -> str:
        return f"{self.address}/32"


def _handler(bank: FakeBank) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send(self, status: int, body: Any) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _record(self, body: bytes) -> None:
            bank.received.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body})

        def do_GET(self) -> None:  # noqa: N802
            self._record(b"")
            if self.path == "/v1/openapi.json":
                return self._send(200, SPEC)
            if self.path.split("?")[0] == "/v1/slow":
                # Answers after SLOW_S, for a use case that shows an operation's own timeout stopping the call.
                time.sleep(SLOW_S)
                return self._send(200, {"slow": True})
            if self.path.startswith("/v1/accounts/"):
                return self._send(200, {"accountId": self.path.rsplit("/", 1)[1], "balance": 1200.5})
            if self.path == "/v1/statements/latest":
                key = self.headers.get("X-Api-Key")
                if not key:
                    return self._send(401, {"error": "no key"})
                # Proves which key arrived without returning it; and repeats the header, as a careless API might.
                print_ = hashlib.sha256(key.encode()).hexdigest()[:12]
                return self._send(200, {"statement": "2026-09", "keyFingerprint": print_, "echo": dict(self.headers)})
            return self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self._record(raw)
            if self.path.startswith("/v1/accounts/") and self.path.endswith("/holds"):
                # A write that succeeds, for a use case that replays an approved write.
                return self._send(200, {"hold": "placed"})
            if self.path != "/v1/mcp":
                return self._send(404, {"error": "not found"})
            msg: dict[str, Any] = json.loads(raw or b"{}")
            method, rid = msg.get("method"), msg.get("id")
            if method == "notifications/initialized":
                self.send_response(202)
                self.end_headers()
                return None
            if method == "initialize":
                info = {"name": "Case desk", "version": "4.1.0"}
                return self._send(200, {"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2025-06-18", "serverInfo": info}})
            if method == "tools/list":
                return self._send(200, {"jsonrpc": "2.0", "id": rid, "result": {"tools": bank.mcp_tools}})
            if method == "tools/call":
                params: dict[str, Any] = msg.get("params") or {}
                result = {"content": [{"type": "text", "text": "ok"}], "structuredContent": {"tool": params.get("name"), "arguments": params.get("arguments")}}
                return self._send(200, {"jsonrpc": "2.0", "id": rid, "result": result})
            return self._send(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}})

    return Handler


@contextmanager
def fake_bank():  # type: ignore[no-untyped-def]
    with tempfile.TemporaryDirectory() as tmp:
        cert_file, key_file = _certificate(Path(tmp))
        address = private_address()
        server = ThreadingHTTPServer((address, 0), BaseHTTPRequestHandler)
        bank = FakeBank(address, server.server_address[1], cert_file)
        bank.mcp_tools = [
            {"name": "lookupCase", "description": "A case by its id", "inputSchema": {"type": "object", "properties": {"caseId": {"type": "string"}}, "required": ["caseId"]}},
        ]
        server.RequestHandlerClass = _handler(bank)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_file, key_file)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield bank
        finally:
            server.shutdown()
