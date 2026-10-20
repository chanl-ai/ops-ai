"""Points the shared stack's chat alias at a real, cheap OpenAI model for a live demo, or back at the fake (`make
demo-model MODEL=<id>`, `make demo-model MODEL=fake`). Dev tooling only: it drives models-service's own admin routes
with a dev service token, the way an operator would, and changes nothing in any service's code.

  MODEL=<id>   rebinds provider connection `openai-local` to https://api.openai.com/v1 with credential name `openai`
               (the key models-service holds from OPS_MODEL_PROVIDER_KEYS) and adds a version of ALIAS on model <id>;
               the id must be one the key can use (GET /v1/models), checked first when OPENAI_API_KEY is set
  MODEL=fake   rebinds `openai-local` to the fake OpenAI (OPS_MODELS_FAKE_OPENAI_URL, else :8746) and adds a version of
               ALIAS on the model id the alias is named after, which the fake's rules answer

Every alias version is immutable, so each switch adds one (asking for what the alias already serves changes nothing);
agents pick up the newest on their next turn. ALIAS names another alias (default `default`); `ALIAS=guardrail-check
MODEL=gpt-5-mini` gives the guardrail checks their own model, creating the alias when it does not exist yet. No key is
ever printed: the provider connection stores only the credential's name.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from typing import Any

import httpx

from ops_identity import mint_service_token
from ops_identity.service_keys import dev_service_signer

MODELS = os.environ.get("OPS_MODELS_URL") or f"http://127.0.0.1:{os.environ.get('OPS_MODELS_PORT', '8730')}"
FAKE = os.environ.get("OPS_MODELS_FAKE_OPENAI_URL") or "http://127.0.0.1:8746/v1"
OPENAI = "https://api.openai.com/v1"
PROVIDER = "openai-local"
KEY_REF = "openai"
# USD per million tokens (input, output) from OpenAI's price list, so the call log meters what the demo spends. An id
# not listed keeps the previous version's prices and says so.
PRICES: dict[str, tuple[str, str]] = {
    "gpt-5-nano": ("0.05", "0.40"),
    "gpt-5-mini": ("0.25", "2.00"),
    "gpt-4.1-nano": ("0.10", "0.40"),
    "gpt-4.1-mini": ("0.40", "1.60"),
    "gpt-4o-mini": ("0.15", "0.60"),
    "gpt-5.5": ("1.25", "10.00"),
}


def data(r: httpx.Response) -> Any:
    if r.status_code >= 400:
        raise SystemExit(
            f"demo-model: {r.request.method} {r.request.url.path} answered {r.status_code}: {r.text[:300]}"
        )
    return r.json()["data"]


def usable(model: str) -> None:
    """Refuses an id the key cannot use, when the key is at hand; models-service would only fail on the first turn."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("demo-model: OPENAI_API_KEY is not set here, so the model id is not checked against the key")
        return
    r = httpx.get(f"{OPENAI}/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
    if r.status_code != 200:
        raise SystemExit(f"demo-model: OpenAI refused the model list ({r.status_code}); check the key")
    ids = {m["id"] for m in r.json()["data"]}
    if model not in ids:
        near = sorted(i for i in ids if "mini" in i or "nano" in i)
        raise SystemExit(f"demo-model: the key cannot use {model}; cheap ones it can: {', '.join(near)}")


def main() -> int:
    model = os.environ.get("MODEL") or (sys.argv[1] if len(sys.argv) > 1 else "")
    alias = os.environ.get("ALIAS") or "default"
    if not model:
        print(__doc__)
        return 2
    to_fake = model == "fake"
    if not to_fake:
        usable(model)
    token = mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id="team_ops")
    with httpx.Client(base_url=MODELS, headers={"Authorization": f"Bearer {token}"}, timeout=20) as m:
        before = next((p for p in data(m.get("/v1/models/providers")) if p["id"] == PROVIDER), None)
        if before is None:
            raise SystemExit(f"demo-model: models-service at {MODELS} has no provider connection {PROVIDER}")
        base_url, key_ref, model_id = (FAKE, None, alias) if to_fake else (OPENAI, KEY_REF, model)
        found = m.get(f"/v1/models/aliases/{alias}/versions")
        created = found.status_code == 404 and not to_fake
        if created:
            # A new alias (guardrail-check, for the guardrail checks) starts on the runtime alias's clearance; `default`
            # is the one every dev seed has.
            chat = data(m.get("/v1/models/aliases/default/versions"))[-1]
            price_in, price_out = PRICES.get(model_id, ("0", "0"))
            body = {"name": alias, "kind": "chat", "providerId": PROVIDER, "modelId": model_id}
            body |= {"clearedSensitivity": chat["clearedSensitivity"], "inputPerMillion": price_in}
            data(m.post("/v1/models/aliases", json=body | {"outputPerMillion": price_out}))
            print(f"alias {alias}: created on {model_id}")
            found = m.get(f"/v1/models/aliases/{alias}/versions")
        versions = data(found)
        current = next((v for v in reversed(versions) if v["status"] == "current"), versions[-1])
        if (before["baseUrl"], before["keyRef"], current["modelId"]) == (base_url, key_ref, model_id):
            # make up runs this on every start; a version per start would bury the ones a person made.
            print(f"alias {alias}: already v{current['version']} {model_id} on {base_url}")
            return 0
        data(m.put(f"/v1/models/providers/{PROVIDER}", json={"baseUrl": base_url, "keyRef": key_ref}))
        if created:
            print(f"agents use {model_id} for {alias} on their next turn")
            return 0
        price_in, price_out = PRICES.get(model_id, (current["inputPerMillion"], current["outputPerMillion"]))
        made = data(
            m.post(
                f"/v1/models/aliases/{alias}/versions",
                json={
                    "providerId": PROVIDER,
                    "modelId": model_id,
                    "clearedSensitivity": current["clearedSensitivity"],
                    "inputPerMillion": str(Decimal(price_in)),
                    "outputPerMillion": str(Decimal(price_out)),
                    # A switch of model keeps how the alias's calls are run (its reasoning effort).
                    **({"reasoningEffort": current["reasoningEffort"]} if current.get("reasoningEffort") else {}),
                },
            )
        )
    was = f"{before['baseUrl']} (key {before['keyRef'] or 'none'})"
    print(f"provider {PROVIDER}: {was} -> {base_url} (key {key_ref or 'none'})")
    print(f"alias {alias}: v{current['version']} {current['modelId']} -> v{made['version']} {model_id}")
    if model_id not in PRICES:
        print(f"prices for {model_id} are not listed here; v{made['version']} keeps v{current['version']}'s")
    print(f"agents use {model_id} on their next turn; undo with `make demo-model MODEL=fake`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
