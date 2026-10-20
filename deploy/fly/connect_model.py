"""Points one model alias at a provider and issues a model key with a spending cap, through models-service's own
routes. Run it where agents-service runs (`fly ssh console -a <agents app>`, `docker compose run --rm agents`): it signs
models-service's admin token with that service's own key (OPS_SERVICE_SIGNING_KEY), which no other machine holds.

    python deploy/fly/connect_model.py --models-url <models-service URL> --base-url <provider base URL>/v1 \\
        --key-ref provider --alias default --model <provider model id> --input-price <per million> \\
        --output-price <per million> --budget 25 --key-id purpose:agents

`--key-ref` names a secret in the deployment's Secrets; the provider key itself never passes through here. A second run
rebinds the connection, adds an alias version and leaves an existing key alone. The key's secret is printed once: set
it as the service's OPS_MODELS_KEY, which models-service refuses once the key's budget is spent.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import httpx

from ops_identity import mint_service_token
from ops_identity.service_keys import service_signer
from ops_service_kit.settings import Settings

KEY_ID = "purpose:agents"


def _check(r: httpx.Response, *ok: int) -> dict[str, Any]:
    if r.status_code not in ok:
        sys.exit(f"{r.request.method} {r.request.url.path}: {r.status_code} {r.text}")
    return r.json() if r.content else {}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--models-url", default=os.environ.get("OPS_MODELS_URL", "http://127.0.0.1:8730"))
    p.add_argument("--provider", default="provider", help="connection name")
    p.add_argument("--base-url", required=True, help="an openai-compatible endpoint's base URL, ending in /v1")
    p.add_argument("--key-ref", default=None, help="name in OPS_MODEL_PROVIDER_KEYS; omit for a keyless endpoint")
    p.add_argument("--alias", required=True, help="agents-service's OPS_MODEL_ALIAS, or another an agent names")
    p.add_argument(
        "--model",
        default=os.environ.get("OPS_PROVIDER_MODEL_ID"),
        help="the provider's model id; defaults to the OPS_PROVIDER_MODEL_ID secret",
    )
    p.add_argument("--sensitivity", default="confidential")
    p.add_argument("--input-price", required=True, help="per million input tokens")
    p.add_argument("--output-price", required=True, help="per million output tokens")
    p.add_argument("--budget", required=True, help="the key's spending cap")
    p.add_argument(
        "--key-id",
        default=KEY_ID,
        help="the model key to issue: purpose:agents for agents-service, purpose:documents for documents-service",
    )
    a = p.parse_args()
    if not a.model:
        sys.exit("name the provider's model with --model or the OPS_PROVIDER_MODEL_ID secret")

    signer = service_signer(Settings())
    token = mint_service_token(
        signer, service="agents", audience="models", tenant_id=os.environ.get("OPS_BOOTSTRAP_TENANT_ID"), ttl_s=300
    )
    with httpx.Client(base_url=a.models_url, headers={"Authorization": f"Bearer {token}"}, timeout=15) as c:
        made = c.post(
            "/v1/models/providers",
            json={"name": a.provider, "type": "openai-compatible", "baseUrl": a.base_url, "keyRef": a.key_ref},
        )
        if made.status_code == 409:
            found = _check(c.get("/v1/models/providers"), 200)["data"]
            pid = next(x["id"] for x in found if x["name"] == a.provider)
            _check(c.put(f"/v1/models/providers/{pid}", json={"baseUrl": a.base_url, "keyRef": a.key_ref}), 200)
            print(f"provider {a.provider}: rebound to {a.base_url}")
        else:
            pid = _check(made, 201)["data"]["id"]
            print(f"provider {a.provider}: created at {a.base_url}")
        version = {
            "providerId": pid,
            "modelId": a.model,
            "clearedSensitivity": a.sensitivity,
            "inputPerMillion": a.input_price,
            "outputPerMillion": a.output_price,
        }
        alias = c.post("/v1/models/aliases", json={"name": a.alias, "kind": "chat", **version})
        if alias.status_code == 409:
            alias = c.post(f"/v1/models/aliases/{a.alias}/versions", json=version)
        ref = _check(alias, 201)["data"]
        print(f"alias {ref['name']}: version {ref['version']} on {a.model}")
        key = c.post("/v1/models/keys", json={"id": a.key_id, "kind": "purpose", "budget": a.budget})
        if key.status_code == 409:
            print(f"key {a.key_id}: exists; OPS_MODELS_KEY stays as set (rotate it through models-service to replace)")
            return
        secret = _check(key, 201)["data"]["secret"]
        print(f"key {a.key_id}: budget {a.budget}. Set it now; it is not shown again:")
        print(f"OPS_MODELS_KEY={secret}")


if __name__ == "__main__":
    main()
