"""uc-130 an agent's Channels tab, api layer: docs/usecases/console/agent-channels.md.

The agents service on the scripted model under dev auth; who may retire is the unit suite's
(services/agents-service/tests/api/test_widget_channels.py) and the ui layer's."""

from __future__ import annotations

from usecase_harness import agents, check, data, finish

TEAM = {"X-Team-Id": "team_ops", "X-Dev-User": "j.richardson@harborpine.example"}
INTRANET = "https://intranet.bank.example"

with agents() as api:
    # Embeds are created and listed on the channel API (c-339); /v1/widget-deployments is a deprecated alias.
    chat = {"type": "chat", "agentId": "ag_fraud", "origins": [INTRANET]}
    made = [data(api.post("/v1/channels", json=chat | {"name": n}, headers=TEAM)) for n in ("Intranet help", "Kiosk")]
    one, two = made[0]["id"], made[1]["id"]
    secret = data(api.post(f"/v1/widget-deployments/{one}/keys", json={"name": "intranet server"}, headers=TEAM))[
        "secret"
    ]
    person = {"email": "m.okafor@harborpine.example", "name": "Maya Okafor", "origin": INTRANET}
    minted = api.post(
        f"/v1/widget-deployments/{one}/sessions", json=person, headers={"Authorization": f"Bearer {secret}"}
    )
    token = data(minted)["session"]
    started = api.post(f"/v1/widget/{one}/threads", headers={"X-Widget-Session": token, "Origin": INTRANET})
    check("1 two embeds, a key and one conversation", started.status_code == 201, started.text[:200])

    listing = "/v1/channels?type=chat&agentId=ag_fraud"
    rows = {r["id"]: r for r in data(api.get(listing, headers=TEAM))["data"]}
    a, b = rows[one], rows[two]
    check(
        "2 each embed shows its own usage and active keys",
        (
            a["activity7d"],
            bool(a["lastActivityAt"]),
            a["embed"]["activeKeys"],
            b["activity7d"],
            b.get("lastActivityAt"),
            b["embed"]["activeKeys"],
        )
        == (1, True, 1, 0, None, 0),
        {"one": a, "two": b},
    )

    retired = api.post(f"/v1/channels/{one}/retire", headers=TEAM)
    check(
        "3 the first embed is retired",
        retired.status_code == 200 and bool(data(retired)["retiredAt"]),
        retired.text[:200],
    )

    again = api.post(
        f"/v1/widget-deployments/{one}/sessions", json=person, headers={"Authorization": f"Bearer {secret}"}
    )
    resumed = api.patch(f"/v1/channels/{one}", json={"paused": False}, headers=TEAM)
    codes = [(r.status_code, r.json().get("error", {}).get("code")) for r in (again, resumed)]
    check(
        "4 a retired embed mints no session and cannot be resumed",
        codes == [(409, "widget_retired"), (409, "widget_retired")],
        codes,
    )

    live = {r["id"] for r in data(api.get(listing, headers=TEAM))["data"]}
    every = {r["id"]: r for r in data(api.get(listing + "&includeRetired=true", headers=TEAM))["data"]}
    check(
        "5 the agent's list leaves the retired embed out unless asked, and shows when it retired",
        one not in live and two in live and bool(every.get(one, {}).get("embed", {}).get("retiredAt")),
        {"live": sorted(live), "retired": every.get(one)},
    )
finish()
