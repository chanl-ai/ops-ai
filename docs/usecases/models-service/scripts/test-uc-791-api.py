# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-791 A provider type added as a file shows in the add list, api layer:
docs/usecases/models-service/a-provider-type-added-as-a.md, steps 1-3.

The run's own models-service twice: once with an extra registry folder holding one JSON entry for a provider no code
names, once with an entry naming an adapter no code registers, which must stop it starting."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import httpx
from usecase_harness import check, data, finish, models

ADMIN = {"X-Team-Id": "team_security", "X-Dev-User": "n.petrov@harborpine.example"}
ENTRY = {
    "id": "acme-llm",
    "label": "Acme LLM",
    "icon": "acme",
    "adapter": "openai-compatible",
    "baseUrl": "https://llm.acme.example/v1",
    "connection": {
        "type": "object",
        "properties": {"apiKey": {"type": "string", "title": "API key", "x-secret": True}},
        "required": ["apiKey"],
    },
    "modelList": {"path": "/models", "auth": "bearer"},
}

extra = Path(tempfile.mkdtemp(prefix="uc791-registry-"))
(extra / "acme-llm.json").write_text(json.dumps(ENTRY))

with models({"OPS_MODELS_PROVIDER_REGISTRY_EXTRA": str(extra)}) as base, httpx.Client(base_url=base, timeout=30) as m:
    listed = data(m.get("/v1/models/provider-types", headers=ADMIN)) or []
    acme = next((t for t in listed if t["id"] == "acme-llm"), None)
    check(
        "1 the admin's add list shows Acme LLM, added as one JSON file, beside the built-in types",
        acme is not None
        and acme["label"] == "Acme LLM"
        and {"openai", "anthropic", "google", "azure-openai", "bedrock", "openai-compatible"}
        <= {t["id"] for t in listed},
        [t.get("id") for t in listed],
    )
    made = m.post(
        "/v1/models/providers", json={"name": "acme-main", "type": "acme-llm", "keyRef": "ACME"}, headers=ADMIN
    )
    kept = data(m.get("/v1/models/providers", params={"search": "acme-main"}, headers=ADMIN)) or {}
    check(
        "2 the admin makes a connection of the new type with no code change",
        made.status_code == 201 and [c["type"] for c in kept.get("data") or []] == ["acme-llm"],
        made.text[:200],
    )

broken = Path(tempfile.mkdtemp(prefix="uc791-broken-"))
(broken / "acme-llm.json").write_text(json.dumps({**ENTRY, "adapter": "acme-sdk"}))
try:
    with models({"OPS_MODELS_PROVIDER_REGISTRY_EXTRA": str(broken)}) as base:
        started = True
except SystemExit:  # the harness exits this way when the service stops before it answers
    started = False
check("3 an entry naming an adapter no code has stops the service from starting", started is False, "it started")

finish()
