"""uc-695, api layer: docs/usecases/agents-service/a-step-runs-in-the-account-it-names.md.

A published workflow whose tool step names an account runs its call in that account, through the real engine,
worker and gateway; the same step naming none uses the team's default (lib/several_accounts.py)."""

from __future__ import annotations

from several_accounts import SF, add_org, flow, retail_on, rig, run_flow, save_and_publish
from usecase_harness import check, data, finish

with rig("uc-695", with_agents=True) as r:
    sf = r.sf
    retail_on(r)
    add_org(r, "EU org", sf["eu_login_url"], "kestrel.eu")
    eu, retail = sf["eu_base"].removeprefix("https://"), sf["api_base"].removeprefix("https://")
    # 1. A workflow whose step names EU org publishes, and its run's query is answered by the EU org.
    saved, live = save_and_publish(r, flow("uc695_eu", {SF: "EU org"}))
    before = r.calls_so_far()
    ran = run_flow(r, "uc695_eu")
    check(
        "1 a published step naming EU org runs its query in the EU org",
        saved.status_code in (200, 201) and (data(live) or {}).get("status") == "approved"
        and ran.get("outcome") == "done" and r.hosts(before) == [eu],
        {"saved": saved.text[:200], "live": live.text[:200], "ran": ran, "hosts": r.hosts(before)},
    )  # fmt: skip
    # 2. The same step naming none runs in the team's default, Retail org.
    save_and_publish(r, flow("uc695_default", None))
    before = r.calls_so_far()
    plain = run_flow(r, "uc695_default")
    check(
        "2 a step naming no account runs in the team's default, Retail org",
        plain.get("outcome") == "done" and r.hosts(before) == [retail],
        {"ran": plain, "hosts": r.hosts(before)},
    )
    # 3. A step naming an account the team does not have cannot be published.
    _, ghost = save_and_publish(r, flow("uc695_ghost", {SF: "Ghost org"}))
    check(
        "3 publishing a step that names Ghost org is refused 422 account_name_unknown",
        ghost.status_code == 422 and (ghost.json().get("error") or {}).get("code") == "account_name_unknown",
        ghost.text[:300],
    )

finish()
