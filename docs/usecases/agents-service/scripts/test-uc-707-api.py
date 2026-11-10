"""uc-707, api layer: docs/usecases/agents-service/an-account-in-use-is-not-deleted.md.

Deleting an account that a published workflow step or an agent names is refused with the counts agents-service gives,
and goes through once neither names it (lib/several_accounts.py)."""

from __future__ import annotations

from several_accounts import SF, add_org, code_of, flow, retail_on, rig, save_and_publish
from usecase_harness import check, data, finish

FLOW = "uc707_eu"

with rig("uc-707", with_agents=True) as r:
    # 1. Two orgs, and a published workflow whose step names EU org.
    retail_on(r)
    add_org(r, "EU org", r.sf["eu_login_url"], "kestrel.eu")
    _, published = save_and_publish(r, flow(FLOW, {SF: "EU org"}))
    check("1 the workflow naming EU org is published", (data(published) or {}).get("status") == "approved",
          published.text[:200])  # fmt: skip
    # 2. Deleting EU org is refused with the count, and the account stays.
    refused = r.gw.delete(f"/v1/apps/{SF}/accounts/{r.ids['EU org']}", headers=r.priya)
    details = dict((refused.json().get("error") or {}).get("details") or {}) if refused.status_code == 409 else {}
    check(
        "2 deleting EU org is refused account_in_use counting one published version of the workflow",
        refused.status_code == 409 and code_of(refused) == "account_in_use" and details.get("published") == 1
        and FLOW in details.get("workflows", []) and r.row(r.priya, r.ids["EU org"]).get("id") == r.ids["EU org"],
        {"refused": refused.text[:400]},
    )  # fmt: skip
    # 3. An agent naming EU org keeps it from being deleted after the step names Retail org.
    _, moved = save_and_publish(r, flow(FLOW, {SF: "Retail org"}))
    assert r.api is not None
    agent = data(r.api.post("/v1/agents", json={"name": "Case desk", "role": "Finds cases"}, headers=r.priya)) or {}
    aid = str(agent.get("id") or "ag_missing")
    named = r.api.patch(f"/v1/agents/{aid}", json={"toolIds": ["salesforce_query"], "accounts": {SF: "EU org"}},
                        headers=r.priya)  # fmt: skip
    held = r.gw.delete(f"/v1/apps/{SF}/accounts/{r.ids['EU org']}", headers=r.priya)
    by_agent = dict((held.json().get("error") or {}).get("details") or {}) if held.status_code == 409 else {}
    check(
        "3 with only an agent naming EU org, deleting it is refused account_in_use naming that agent",
        named.status_code == 200 and held.status_code == 409 and code_of(held) == "account_in_use"
        and by_agent.get("agents") == [aid] and not by_agent.get("workflows"),
        {"named": named.text[:200], "held": held.text[:400]},
    )  # fmt: skip
    # 4. With the agent naming Retail org too, the delete goes through.
    r.api.patch(f"/v1/agents/{aid}", json={"accounts": {SF: "Retail org"}}, headers=r.priya)
    gone = r.gw.delete(f"/v1/apps/{SF}/accounts/{r.ids['EU org']}", headers=r.priya)
    check(
        "4 once the step and the agent name Retail org, EU org is deleted",
        (data(moved) or {}).get("status") == "approved" and gone.status_code == 204
        and not r.row(r.priya, r.ids["EU org"]),
        {"moved": moved.text[:200], "gone": gone.text[:200]},
    )  # fmt: skip

finish()
