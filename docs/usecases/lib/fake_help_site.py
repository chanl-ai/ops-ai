"""A small help centre for website-source use cases: served on https as help.northbank.test on this machine's private
address, with robots.txt (refusing /admin/), a sitemap index naming a sitemap with lastmod dates, pages with menus and
footers around their main article, and ETags that answer 304 when a page is unchanged. A use case edits `pages` and
`lastmod` between syncs and reads `hits` to see what a sync fetched.

What tools-service needs to reach it is `settings` (the CA file and the name override) and `range` (its address, which
a security admin allows)."""

from __future__ import annotations

import hashlib
import json
import ssl
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fake_bank_https import private_address

HOST = "help.northbank.test"


def page(title: str, *paragraphs: str) -> str:
    """A help page as a CMS serves one: a menu, the article, a footer with a cookie line."""
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return (
        f"<html><head><title>{title}</title></head><body>"
        "<nav><a href='/'>Home</a> <a href='/lending/'>Lending</a> <a href='/cards/'>Cards</a></nav>"
        f"<main><h1>{title}</h1>{body}</main>"
        "<footer>Northbank help centre. We use cookies to improve this site.</footer></body></html>"
    )


class HelpSite:
    def __init__(self, address: str, port: int, cert: Path) -> None:
        self.address, self.port = address, port
        self.settings = {"OPS_EGRESS_CA_FILE": str(cert), "OPS_EGRESS_RESOLVE": json.dumps({HOST: f"{address}:{port}"})}
        self.range = f"{address}/32"
        self.base = f"https://{HOST}"
        self.pages: dict[str, str] = {
            "/lending/early-repayment": page(
                "Early repayment of a personal loan",
                "You can repay all or part of your personal loan at any time.",
                "An early repayment charge of up to 58 days interest may apply to loans over three years.",
            ),
            "/lending/payment-holidays": page(
                "Payment holidays",
                "A payment holiday pauses your loan payments for up to three months.",
                "Interest still builds up during a payment holiday.",
            ),
            "/cards/lost-card": page(
                "Report a lost card",
                "Freeze a lost card in the app straight away, then order a replacement.",
            ),
            "/archive/2019-rates": page("2019 rates", "Old rates no customer can still take."),
            "/admin/": page("Staff only", "The staff area."),
        }
        self.lastmod = dict.fromkeys(self.pages, "2026-11-01")
        self.hits: list[str] = []
        # Pages the sitemap still lists that answer 404, as a page deleted in a CMS whose sitemap is cached.
        self.gone: set[str] = set()

    def etag(self, path: str) -> str:
        return '"' + hashlib.sha256(self.pages[path].encode()).hexdigest()[:16] + '"'

    def change(self, path: str, html: str, lastmod: str) -> None:
        self.pages[path], self.lastmod[path] = html, lastmod

    def remove(self, path: str) -> None:
        self.pages.pop(path, None)
        self.lastmod.pop(path, None)


def _certificate(folder: Path, host: str = HOST) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = folder / f"{host}.crt", folder / f"{host}.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return cert_file, key_file


def _handler(site: HelpSite) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, status: int, body: str = "", headers: dict[str, str] | None = None) -> None:
            raw = body.encode()
            self.send_response(status)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            site.hits.append(path)
            if path == "/robots.txt":
                return self._send(200, f"User-agent: *\nDisallow: /admin/\n\nSitemap: {site.base}/sitemap-index.xml\n")
            if path == "/sitemap-index.xml":
                index = f"<sitemapindex><sitemap><loc>{site.base}/sitemap-pages.xml</loc></sitemap></sitemapindex>"
                return self._send(200, index, {"Content-Type": "application/xml"})
            if path == "/sitemap-pages.xml":
                urls = "".join(
                    f"<url><loc>{site.base}{p}</loc><lastmod>{site.lastmod[p]}</lastmod></url>"
                    for p in sorted(site.pages)
                )
                return self._send(200, f"<urlset>{urls}</urlset>", {"Content-Type": "application/xml"})
            if path not in site.pages or path in site.gone:
                return self._send(404, "not found")
            tag = site.etag(path)
            if self.headers.get("If-None-Match") == tag:
                return self._send(304)
            return self._send(200, site.pages[path], {"Content-Type": "text/html; charset=utf-8", "ETag": tag})

    return Handler


@contextmanager
def help_site() -> Generator[HelpSite]:
    with tempfile.TemporaryDirectory() as tmp:
        cert, key = _certificate(Path(tmp))
        address = private_address()
        server = ThreadingHTTPServer((address, 0), BaseHTTPRequestHandler)
        site = HelpSite(address, int(server.server_address[1]), cert)
        server.RequestHandlerClass = _handler(site)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield site
        finally:
            server.shutdown()


DOCS_HOST = "docs.opsai.test"


class Proxied:
    """A site of this machine's (the repo's own docs site, served by `next dev`) put behind https under a test name,
    so the website plugin reaches it the way it reaches any site: through the egress proxy, by name."""

    def __init__(self, address: str, port: int, cert: Path) -> None:
        self.settings = {
            "OPS_EGRESS_CA_FILE": str(cert),
            "OPS_EGRESS_RESOLVE": json.dumps({DOCS_HOST: f"{address}:{port}"}),
        }
        self.range = f"{address}/32"
        self.base = f"https://{DOCS_HOST}"
        self.hits: list[str] = []


def _proxy_handler(site: Proxied, upstream: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            site.hits.append(self.path)
            try:
                with urllib.request.urlopen(f"{upstream}{self.path}", timeout=60) as r:
                    status, body, kind = r.status, r.read(), r.headers.get("Content-Type", "text/html")
            except urllib.error.HTTPError as e:
                status, body, kind = e.code, e.read(), e.headers.get("Content-Type", "text/html")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


@contextmanager
def proxied_site(upstream: str) -> Generator[Proxied]:
    """`upstream` (http on this machine) served on https as docs.opsai.test on the private address."""
    with tempfile.TemporaryDirectory() as tmp:
        cert, key = _certificate(Path(tmp), DOCS_HOST)
        address = private_address()
        server = ThreadingHTTPServer((address, 0), BaseHTTPRequestHandler)
        site = Proxied(address, int(server.server_address[1]), cert)
        server.RequestHandlerClass = _proxy_handler(site, upstream.rstrip("/"))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield site
        finally:
            server.shutdown()
