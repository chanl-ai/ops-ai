"""Gives the local shared stack a model alias on the fake model, for the demo team's agents (c-383). Dev tooling only.

    uv run python scripts/demo/local_model.py --fake-url http://127.0.0.1:8747/v1 --alias bank-assist

Staging needs none of this: its `default` alias is bound to the fake on the committed rules. The local shared stack
binds `default` to a paid provider, so the demo seed (`OPS_DEMO_MODEL_ALIAS=bank-assist` in its env file) would spend
on every turn. This adds a provider connection `fake-demo` at `--fake-url` (a fake started on the committed rules,
`uv run --directory services/models-service/scripts --project .. python -m fake_openai
services/models-service/seed/demo-fake-openai` with FAKE_OPENAI_PORT) and the alias on it, through models-service's
own admin routes with a dev service token, as scripts/demo_model.py does. Every other alias keeps its provider. A
second run with the same URL changes nothing; another URL rebinds the connection.
"""

from __future__ import annotations

import argparse
import os
from typing import Any

import httpx

from ops_identity import mint_service_token
from ops_identity.service_keys import dev_service_signer

MODELS = os.environ.get("OPS_MODELS_URL") or f"http://127.0.0.1:{os.environ.get('OPS_MODELS_PORT', '8730')}"
PROVIDER = "fake-demo"
# Priced as a small hosted model, so the call log's cost column reads as it would for a real one.
PRICE_IN, PRICE_OUT = "0.25", "2.00"


def data(r: httpx.Response) -> Any:
    if r.status_code >= 400:
        raise SystemExit(
            f"local-model: {r.request.method} {r.request.url.path} answered {r.status_code}: {r.text[:300]}"
        )
    return r.json()["data"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fake-url", required=True, help="the fake model's base URL, ending in /v1")
    ap.add_argument("--alias", default="bank-assist")
    args = ap.parse_args()
    token = mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id="team_ops")
    with httpx.Client(base_url=MODELS, headers={"Authorization": f"Bearer {token}"}, timeout=20) as m:
        providers = {p["id"]: p for p in data(m.get("/v1/models/providers"))}
        found = providers.get(PROVIDER) or next((p for p in providers.values() if p.get("name") == PROVIDER), None)
        if found is None:
            made = data(
                m.post(
                    "/v1/models/providers",
                    json={"name": PROVIDER, "type": "openai-compatible", "baseUrl": args.fake_url},
                )
            )
            provider_id = str(made["id"])
            print(f"provider {PROVIDER}: made at {args.fake_url}")
        else:
            provider_id = str(found["id"])
            if found.get("baseUrl") != args.fake_url:
                data(m.put(f"/v1/models/providers/{provider_id}", json={"baseUrl": args.fake_url, "keyRef": None}))
                print(f"provider {PROVIDER}: {found.get('baseUrl')} -> {args.fake_url}")
            else:
                print(f"provider {PROVIDER}: already at {args.fake_url}")
        versions = m.get(f"/v1/models/aliases/{args.alias}/versions")
        if versions.status_code == 404:
            clearance = data(m.get("/v1/models/aliases/default/versions"))[-1]["clearedSensitivity"]
            body = {"name": args.alias, "kind": "chat", "providerId": provider_id, "modelId": args.alias}
            data(
                m.post(
                    "/v1/models/aliases",
                    json=body
                    | {"clearedSensitivity": clearance, "inputPerMillion": PRICE_IN, "outputPerMillion": PRICE_OUT},
                )
            )
            print(f"alias {args.alias}: made on {PROVIDER}")
            return 0
        current = data(versions)[-1]
        if current["providerId"] != provider_id:
            raise SystemExit(
                f"local-model: alias {args.alias} exists on provider {current['providerId']}; pick another --alias"
            )
        print(f"alias {args.alias}: already on {PROVIDER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
