"""uc-701, api layer: docs/usecases/agents-service/a-rename-changes-no-published-version.md.

Renaming an account rewrites no workflow version: the published one keeps its digest and its old name, so its run is
refused rather than sent to another account, and publishing a new version that still names the old name is refused
until the step names the new one. The rename's warning counts what names the account (lib/several_accounts.py)."""

from __future__ import annotations

from typing import Any

from several_accounts import SF, add_org, code_of, flow, retail_on, rig, run_flow, save_and_publish
from usecase_harness import check, data, finish

FLOW = "uc701_eu"


def live_digest(r: Any) -> str:
    view = data(r.api.get(f"/v1/workflows/definitions/{FLOW}", headers=r.priya)) or {}
    live = view.get("liveVersion")
    return next((str(v.get("digest")) for v in view.get("versions") or [] if v.get("version") == live), "")


with rig("uc-701", with_agents=True) as r:
    sf = r.sf
    retail_on(r)
    add_org(r, "EU org", sf["eu_login_url"], "kestrel.eu")
    save_and_publish(r, flow(FLOW, {SF: "EU org"}))
    before_digest = live_digest(r)
    # 1. The rename's warning counts the published version that names EU org.
    uses = data(
        r.api.get("/v1/workflows/definitions/account-uses", params={"app": SF, "name": "EU org"}, headers=r.priya)
    )
    check(
        "1 before the rename, the warning counts one published version naming EU org",
        (uses or {}).get("published") == 1 and FLOW in (uses or {}).get("workflows", []),
        uses,
    )
    # 2. The rename changes no published version: same digest, and its run is refused rather than sent elsewhere.
    row = r.row(r.priya, r.ids["EU org"])
    renamed = r.gw.patch(
        f"/v1/apps/{SF}/accounts/{r.ids['EU org']}",
        json={"revision": row.get("revision", 1), "name": "Europe org"},
        headers=r.priya,
    )
    before = r.calls_so_far()
    ran = run_flow(r, FLOW)
    check(
        "2 after renaming EU org to Europe org the published version keeps its digest, and its run sends nothing",
        renamed.status_code == 200 and live_digest(r) == before_digest and ran.get("outcome") != "done"
        and r.hosts(before) == [],
        {"renamed": renamed.text[:200], "digest": (before_digest, live_digest(r)), "ran": ran, "hosts": r.hosts(before)},
    )  # fmt: skip
    # 3. Its next publish, still naming EU org, is refused naming the step.
    old = flow(FLOW, {SF: "EU org"})
    old["name"] = "Look up the case again"
    _, refused = save_and_publish(r, old)
    check(
        "3 publishing a new version that still names EU org is refused 422 account_name_unknown",
        refused.status_code == 422 and code_of(refused) == "account_name_unknown",
        refused.text[:300],
    )
    # 4. With the step naming Europe org it publishes, and runs in the EU org.
    _, fixed = save_and_publish(r, flow(FLOW, {SF: "Europe org"}))
    before = r.calls_so_far()
    again = run_flow(r, FLOW)
    check(
        "4 the step renamed to Europe org publishes and runs in the EU org",
        (data(fixed) or {}).get("status") == "approved" and again.get("outcome") == "done"
        and r.hosts(before) == [sf["eu_base"].removeprefix("https://")],
        {"fixed": fixed.text[:200], "ran": again, "hosts": r.hosts(before)},
    )  # fmt: skip

finish()
