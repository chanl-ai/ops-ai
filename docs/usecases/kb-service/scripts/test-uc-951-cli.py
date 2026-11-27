# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-951 open a deck or Word file as pages, cli layer: docs/usecases/kb-service/open-a-deck-or-word-file-as-pages.md,
story S5 (step 5). With no converter worker, a pushed deck still gives its text to `opsai kb text`, reading the address
from a saved profile. Own kb-service with its files-service and documents-service; no model is called."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path

from usecase_harness import ROOT, check, data, finish, kb

_api = importlib.util.spec_from_file_location("uc951_api", Path(__file__).with_name("test-uc-951-api.py"))
assert _api and _api.loader
api = importlib.util.module_from_spec(_api)
_api.loader.exec_module(api)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc-951-cli-") as tmp, kb(Path(tmp) / "files") as k:
        base = data(k.post("/v1/knowledge-bases", json={"name": "Claims intake", "owner": "maya@harborpine.example"}))
        src = data(k.post("/v1/sources", json={"type": "push", "name": "Project files", "kbIds": [base["id"]]}))
        body = {"name": "project-update.pptx", "content": base64.b64encode(api.deck()).decode(), "mime": api.PPTX}
        item = data(k.post(f"/v1/sources/{src['id']}/items", json=body))["item"]
        config = Path(tmp) / "ops-config.json"
        profile = {"baseUrl": "http://127.0.0.1", "team": "team_ops", "services": {"kb": str(k.base_url).rstrip("/")}}
        config.write_text(json.dumps({"profiles": {"local": profile}, "current": "local"}))
        env = {**os.environ, "OPS_CONFIG": str(config)}
        env.pop("VIRTUAL_ENV", None)
        argv = ["uv", "run", "--quiet", "--project", str(ROOT / "sdk" / "python"), "opsai", "kb", "text", item["id"]]
        ran = subprocess.run(argv, env=env, capture_output=True, text=True, check=False, timeout=300)
        check(
            "5 with no converter, opsai kb text still prints the deck's slide text",
            ran.returncode == 0
            and "[p1 text] The event queue went live in three regions" in ran.stdout
            and "[p3 text] Replay after an outage is tested every quarter" in ran.stdout,
            {"out": ran.stdout[-600:], "err": ran.stderr[-400:]},
        )
    finish()


main()
