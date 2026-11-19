"""uc-751, sdk and api layers: docs/usecases/platform-service/a-new-workspace-chats-and-writes.md, steps 1, 2, 4, 5 and
10. On a running stack started on a fresh database (`make up OPS_PORT_OFFSET=<n>`, ports from the OPS_*_PORT the
make target exports), the first admin finds the first-run defaults off, saves the company's OpenAI key
(OPENAI_API_KEY), sees it tested and its models listed, points chat at one and an agent answers through it.
`--layer api` makes the key and chat-model calls over plain HTTP instead of the Python SDK."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "sdk" / "python" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import api_as  # noqa: E402
from ops_ai import OpsAI  # noqa: E402

failures: list[str] = []
SECURITY = "team_security"


def check(label: str, ok: bool, seen: Any = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {label}" + ("" if ok else f": {str(seen)[:300]}"))
    if not ok:
        failures.append(label)


def pick(models: list[dict[str, Any]]) -> str:
    """A small chat model the key lists, so the use case spends little."""
    ids = [m["id"] for m in models]
    for want in ("gpt-4.1-mini", "gpt-4o-mini", "gpt-4.1-nano"):
        if want in ids:
            return want
    return next(i for i in ids if i.startswith("gpt-"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", choices=("sdk", "api"), default="sdk")
    layer = parser.parse_args().layer
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("FAIL OPENAI_API_KEY is not set: the use case needs the company's own key")
        return 1
    urls = api_as.addresses("local")
    session = api_as.token("local", "admin", urls)
    team = session.get("team")
    # The account admin: an admin of the Security team, where settings.manage is held, as a new workspace's first admin.
    owner = api_as.token("local", "security", urls)
    with OpsAI(base_url=urls["platform"], services=urls, access_token=session["token"], team=team) as ops:
        # Steps 1 and 2: a new workspace starts with reviews, approvals and step-up off.
        policies: dict[str, Any] = {}
        for name in ("publishReview", "egressNewHosts", "appChanges", "stepUp"):
            policies[name] = ops.raw.platform.policies_get_policy(name).get("value")
        first = next(iter((policies["publishReview"] or {}).values()), {})
        check("publish review is never for the first team", bool(first) and set(first.values()) == {"never"}, policies)
        check("new addresses are any_public", policies["egressNewHosts"] == "any_public", policies)
        check("makers' ask-first writes are off workspace-wide", (policies["appChanges"] or {}).get("*", {}).get("makersAsk") is False, policies)
        check("step-up is off", policies["stepUp"] is False, policies)

        # Step 4: the key is saved, tested with the provider, its models listed, and chat pointed at one.
        # Keys are the account's: changed as an admin of the Security team, where settings.manage is held.
        if layer == "sdk":
            with OpsAI(base_url=urls["platform"], services=urls, access_token=owner["token"], team=SECURITY) as sec:
                sec.models.save_key("OPENAI", key)
                tested = sec.models.check_key("OPENAI", "openai")
                listed = sec.models.key_models("OPENAI", "openai")
                model = pick(listed)
                chosen = sec.models.set_chat_model({"provider": "openai", "keyName": "OPENAI", "model": model})
        else:
            auth = {"Authorization": f"Bearer {owner['token']}", "X-Team-Id": SECURITY}
            m = urls["models"]
            with httpx.Client(timeout=60, headers=auth) as http:
                assert http.put(f"{m}/v1/provider-keys/OPENAI", json={"value": key}).status_code == 200
                tested = http.post(f"{m}/v1/provider-keys/OPENAI/check", json={"provider": "openai"}).json()["data"]
                listed = http.get(f"{m}/v1/provider-keys/OPENAI/models", params={"provider": "openai"}).json()["data"]
                model = pick(listed)
                body = {"provider": "openai", "keyName": "OPENAI", "model": model}
                r = http.put(f"{m}/v1/models/chat-model", json=body)
                check("PUT /v1/models/chat-model answers 200", r.status_code == 200, r.text)
                chosen = r.json()["data"]
        check("the provider accepts the key", tested.get("ok") is True and tested.get("models", 0) > 0, tested)
        check("the key lists chat models", any(m["id"].startswith("gpt-") for m in listed), listed[:5])
        check("default and assistant point at the chosen model", chosen.get("aliases") == ["default", "assistant"] and chosen.get("model") == model, chosen)
        with OpsAI(base_url=urls["platform"], services=urls, access_token=owner["token"], team=SECURITY) as sec:
            conns = {c["name"]: c for c in sec.models.providers()}
        made = conns.get("default-openai", {})
        check("one OpenAI connection signs in with the saved key", made.get("keyRef") == "OPENAI" and made.get("id") == chosen.get("providerId"), conns.keys())

        # Step 5: an agent answers through the chosen model.
        agents = [a for a in ops.agents.list() if a.get("status") in ("published", "live", None)]
        check("the new workspace has an agent to chat with", bool(agents), agents)
        if agents:
            reply = ops.agents.chat(agents[0]["id"], "Reply with the single word: ready")
            text = str(reply)
            check(f"{agents[0].get('name')} answers", "ready" in text.lower() and "provider_key_missing" not in text, text)
    print(f"uc-751 {layer}: {'PASS' if not failures else 'FAIL ' + ', '.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
