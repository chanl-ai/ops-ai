"""uc-707, api layer: docs/usecases/agents-service/an-account-in-use-is-not-deleted.md.

Deleting an account that a published workflow step names is refused with the count agents-service gives, and goes
through once the step names another account (lib/several_accounts.py)."""

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
    # 3. With the step naming Retail org and published, the delete goes through.
    _, moved = save_and_publish(r, flow(FLOW, {SF: "Retail org"}))
    gone = r.gw.delete(f"/v1/apps/{SF}/accounts/{r.ids['EU org']}", headers=r.priya)
    check(
        "3 after the step names Retail org, EU org is deleted",
        (data(moved) or {}).get("status") == "approved" and gone.status_code == 204
        and not r.row(r.priya, r.ids["EU org"]),
        {"moved": moved.text[:200], "gone": gone.text[:200]},
    )  # fmt: skip

finish()
