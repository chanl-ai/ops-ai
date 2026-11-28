# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-792 An admin connects Anthropic and an agent's model settings reach its chat, api layer:
docs/usecases/models-service/an-admin-connects-anthropic-and-an.md, steps 1-7, 4a and 16.

The run's own models-service and the fake OpenAI (services/models-service/scripts/fake_openai), standing in for
Anthropic's OpenAI-compatible endpoint: it answers only the key in FAKE_OPENAI_API_KEY and keeps the settings of each
chat request it receives (GET /received). agents-service runs its turns through models-service on its dev model key."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import httpx
from usecase_harness import AGENTS_PORT, TEAM, agents, check, data, fake_openai, finish, models, save_agent

KEY = "sk-ant-uc792-0123456789abcdef"
os.environ["FAKE_OPENAI_API_KEY"] = KEY
ADMIN = {"X-Team-Id": "team_security", "X-Dev-User": "n.petrov@harborpine.example"}
BUILDER = {**TEAM, "X-Dev-User": "m.okafor@harborpine.example"}
MODEL = "claude-haiku-4-5"
RUN = uuid.uuid4().hex[:6]
ALIAS = f"fast-{RUN}"

with fake_openai(Path(tempfile.mkdtemp(prefix="uc792-fake-"))) as fake_v1:
    with (
        # models-service asks agents-service how many agents name each alias (step 16).
        models({"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}) as models_url,
        httpx.Client(base_url=models_url, timeout=30) as m,
        httpx.Client(base_url=fake_v1.removesuffix("/v1"), timeout=10) as fake,
    ):
        types = data(m.get("/v1/models/provider-types", headers=ADMIN)) or []
        anthropic = next((t for t in types if t["id"] == "anthropic"), {})
        check(
            "1 the admin's add list offers Anthropic, its key marked secret",
            bool(anthropic) and anthropic["connection"]["properties"]["apiKey"]["x-secret"] is True,
            [t.get("id") for t in types],
        )

        body = {
            "name": f"anthropic-{RUN}",
            "type": "anthropic",
            "baseUrl": fake_v1,
            "keyRef": "UC792_ANTHROPIC",
            "secrets": {"apiKey": KEY},
        }
        made = m.post("/v1/models/providers", json=body, headers=ADMIN)
        listed = m.get("/v1/models/providers", headers=ADMIN)
        check(
            "2 the admin saves the connection with its key, and no reply shows the key",
            made.status_code == 201 and KEY not in made.text + listed.text and KEY[:12] not in listed.text,
            made.text[:300],
        )
        pid = (data(made) or {}).get("id")

        tested = m.post(
            "/v1/provider-keys/UC792_ANTHROPIC/check",
            json={"provider": "anthropic", "endpoint": fake_v1},
            headers=ADMIN,
        )
        check(
            "3 a key test never sends the key to a loopback address: the test is refused, naming the endpoint",
            tested.status_code == 422 and tested.json()["error"]["code"] == "endpoint_refused",
            tested.text[:300],
        )

        version = {"providerId": pid, "modelId": MODEL, "clearedSensitivity": "confidential"}
        mapped = m.post("/v1/models/aliases", json={"name": ALIAS, **version}, headers=ADMIN)
        check("4 the admin maps alias fast to Claude Haiku 4.5 on it", mapped.status_code == 201, mapped.text[:300])

        # The account admin re-points the alias with no owner rule in between. Dev sign-in carries no roles, so the
        # member's refusal (403 admin_only) is the ui layer's step 15, on platform sign-in.
        repointed = m.post(f"/v1/models/aliases/{ALIAS}/versions", json=version, headers=ADMIN)
        versions = [v.get("version") for v in (data(m.get(f"/v1/models/aliases/{ALIAS}/versions", headers=ADMIN)) or {}).get("data", [])]
        check(
            "4a the admin re-points alias fast: it now has versions 1 and 2",
            repointed.status_code == 201 and versions == [1, 2],
            {"repointed": repointed.text[:200], "versions": versions},
        )

        with agents(models_url=models_url, models_key="mk_dev_agents") as api:
            knobs = data(api.get(f"/v1/model-aliases/{ALIAS}/knobs", headers=BUILDER)) or {}
            props = (knobs.get("knobs") or {}).get("properties") or {}
            check(
                "5 the builder sees only the knobs Claude Haiku takes, with catalog defaults",
                set(props) == {"temperature", "top_p", "top_k", "thinking_budget", "max_tokens"}
                and props["temperature"].get("default") == 1
                and props["temperature"].get("maximum") == 1,
                knobs,
            )

            made_agent = api.post(
                "/v1/agents",
                json={"name": f"Claims Helper {RUN}", "role": "Answers claims", "model": ALIAS},
                headers=BUILDER,
            )
            aid = (data(made_agent) or {}).get("id")
            wanted = {"temperature": 0.4, "top_k": 30, "thinking_budget": 2000}
            too_hot = save_agent(api, aid, {"modelSettings": {"temperature": 1.6}}, headers=BUILDER)
            saved = save_agent(api, aid, {"modelSettings": wanted}, headers=BUILDER)
            check(
                "6 a temperature above the model's range is refused naming it, and settings in range are saved",
                too_hot.status_code == 422
                and "Temperature" in too_hot.text
                and saved.status_code == 200
                and (data(saved) or {}).get("modelSettings") == wanted,
                {"made": made_agent.text[:200], "refused": too_hot.text[:200], "saved": saved.text[:200]},
            )

            turn = api.post(f"/v1/agents/{aid}/test", json={"message": "Summarise claim CLM-77"}, headers=BUILDER)
            received = fake.get("/received").json()
            last = next((r for r in reversed(received) if r.get("model") == MODEL), {})
            check(
                "7 the agent's chat reaches the provider with the saved settings",
                turn.status_code == 200
                and last.get("temperature") == 0.4
                and last.get("top_k") == 30
                and last.get("thinking") == {"type": "enabled", "budget_tokens": 2000},
                {"turn": turn.text[:200], "received": received[-3:]},
            )

            listed = data(m.get("/v1/models/aliases", params={"ids": ALIAS}, headers=ADMIN)) or {}
            used = [a.get("usedBy") for a in listed.get("data", [])]
            check("16 the alias list says one agent uses the alias", used == [1], listed)

finish()
