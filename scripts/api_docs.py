"""Every service's API reference on one local page: `make up` starts it at http://127.0.0.1:8799 (OPS_API_DOCS_PORT).

One Swagger UI with a service picker. Each spec is read live from the running service; when a service is down, its
committed services/<name>-service/openapi.json is served instead and the page says so in the spec's title. Standard
library only, so it runs before any virtualenv exists.
"""

from __future__ import annotations

import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Service, its default port and the path its live spec is served at.
SERVICES = [
    ("platform", int(os.environ.get("OPS_PLATFORM_PORT", "8710")), "/openapi.json"),
    ("agents", int(os.environ.get("OPS_AGENTS_PORT", "8700")), "/v1/openapi.json"),
    ("tools", int(os.environ.get("OPS_TOOLS_PORT", "8720")), "/openapi.json"),
    ("models", int(os.environ.get("OPS_MODELS_PORT", "8730")), "/openapi.json"),
    ("kb", int(os.environ.get("OPS_KB_PORT", "8740")), "/openapi.json"),
    ("files", int(os.environ.get("OPS_FILES_PORT", "8750")), "/openapi.json"),
    ("documents", int(os.environ.get("OPS_DOCUMENTS_PORT", "8760")), "/openapi.json"),
]

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ops AI API reference</title>
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.17.14/swagger-ui.css"
  integrity="sha384-wxLW6kwyHktdDGr6Pv1zgm/VGJh99lfUbzSn6HNHBENZlCN7W602k9VkGdxuFvPn" crossorigin="anonymous">
<style>body{margin:0;background:#fafafa} .topbar{display:none}</style></head>
<body><div id="ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"
  integrity="sha384-wmyclcVGX/WhUkdkATwhaK1X1JtiNrr2EoYJ+diV3vj4v6OC5yCeSu+yW13SYJep" crossorigin="anonymous"></script>
<script src="https://unpkg.com/swagger-ui-dist@5.17.14/swagger-ui-standalone-preset.js"
  integrity="sha384-2YH8WDRaj7V2OqU/trsmzSagmk/E2SutiCsGkdgoQwC9pNUJV1u/141DHB6jgs8t" crossorigin="anonymous"></script>
<script>
SwaggerUIBundle({dom_id: "#ui", urls: %s, "urls.primaryName": "agents", deepLinking: true,
  presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset], layout: "StandaloneLayout"});
</script></body></html>"""


def spec(name: str, port: int, path: str) -> bytes:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as r:
            return r.read()
    except OSError:
        committed = json.loads((ROOT / "services" / f"{name}-service" / "openapi.json").read_text())
        info = committed.setdefault("info", {})
        info["title"] = f"{info.get('title', name)} (not running: the committed spec)"
        return json.dumps(committed).encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            urls = [{"name": n, "url": f"/specs/{n}.json"} for n, _, _ in SERVICES]
            self.send(200, "text/html; charset=utf-8", (PAGE % json.dumps(urls)).encode())
        elif self.path == "/health":
            self.send(200, "application/json", b'{"status":"ok"}')
        elif self.path.startswith("/specs/") and self.path.endswith(".json"):
            wanted = self.path[len("/specs/") : -len(".json")]
            match = next((s for s in SERVICES if s[0] == wanted), None)
            if match is None:
                self.send(404, "application/json", b'{"error":"no such service"}')
            else:
                self.send(200, "application/json", spec(*match))
        else:
            self.send(404, "text/plain", b"not found")

    def send(self, code: int, kind: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


if __name__ == "__main__":
    port = int(os.environ.get("OPS_API_DOCS_PORT", "8799"))
    print(f"api docs: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
