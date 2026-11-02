# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-605 A team runs its agents on its own Azure OpenAI resource, cli layer:
docs/usecases/models-service/a-team-connects-azure-openai.md, steps 7-8.

What an install runs: models-service started with OPENAI_API_TYPE=azure, OPENAI_API_BASE, OPENAI_API_VERSION and
OPENAI_API_REGION, the key as the dev stack names it (`openai`, which scripts/stack.sh fills from OPENAI_API_KEY),
against the fake Azure. Then the same start with the api-version missing, which must stop before serving and name
the variable."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import httpx
from usecase_harness import ROOT, check, fake_openai, finish, models, pg_url, service_headers

KEY = "azure-uc605-cli-key-0123456789"
os.environ["FAKE_OPENAI_API_KEY"] = KEY
os.environ["FAKE_AZURE_REGION"] = "Sweden Central"

with fake_openai(Path(tempfile.mkdtemp(prefix="uc605-cli-fake-"))) as fake_v1:
    endpoint = fake_v1.removesuffix("/v1")
    install = {
        "OPENAI_API_TYPE": "azure",
        "OPENAI_API_BASE": endpoint,
        "OPENAI_API_VERSION": "2024-10-21",
        "OPENAI_API_REGION": "swedencentral",
        "OPS_MODEL_PROVIDER_KEYS": json.dumps({"openai": KEY}),
    }
    with models(install) as base, httpx.Client(base_url=base, timeout=30) as m:
        local = next(
            p
            for p in m.get("/v1/models/providers", headers=service_headers("models")).json()["data"]
            if p["id"] == "openai-local"
        )
        answer = m.post(
            "/v1/models/chat/completions",
            json={"model": "default", "messages": [{"role": "user", "content": "Which region are you in?"}]},
            headers={"Authorization": "Bearer mk_dev_agents", "X-Tenant-Id": "local"},
        )
        check(
            "7 the install's Azure settings make openai-local that resource, and alias default answers through it",
            (local["type"], local["baseUrl"], local["apiVersion"], local["region"], local["keyRef"])
            == ("azure-openai", endpoint, "2024-10-21", "swedencentral", "openai")
            and answer.status_code == 200
            and KEY not in json.dumps(local),
            {"local": local, "status": answer.status_code, "body": answer.text[:200]},
        )

env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "OPENAI_API_VERSION")}
env |= {k: v for k, v in install.items() if k != "OPENAI_API_VERSION"}
env |= {"OPS_DATABASE_URL": pg_url(), "OPS_MODELS_PORT": "0"}
started = subprocess.run(
    ["uv", "run", "python", "-m", "ops_models"],
    cwd=ROOT / "services" / "models-service",
    env=env,
    capture_output=True,
    text=True,
    timeout=120,
    check=False,
)
said = started.stdout + started.stderr
check(
    "8 with OPENAI_API_VERSION missing, models-service stops before serving and names the variable",
    started.returncode != 0 and "OPENAI_API_VERSION" in said and KEY not in said,
    said[-400:],
)

finish()
