"""uc-694, api layer: docs/usecases/tools-service/a-call-never-uses-someone-elses-account.md.

A call naming one person's own account runs only when it acts for that person; naming another team's account is
refused as unknown. Neither reaches Salesforce (lib/several_accounts.py)."""

from __future__ import annotations

from several_accounts import MAYA, PRIYA, SF, code_of, retail_on, rig
from usecase_harness import check, data, finish

MINE = "Mobile org · Maya"

with rig("uc-694") as r:
    sf = r.sf
    # Each person may sign in with their own account beside the team's, so Maya may add one of her own.
    retail_on(r, sign_in="person_or_team")
    # 1. Maya adds a second account of her own, at the EU org, and signs in to it.
    started = r.gw.post(
        f"/v1/me/accounts/{r.ids['retail']}/another",
        json={"name": MINE, "settings": {"login_url": sf["eu_login_url"]}},
        headers=r.maya,
    )
    opened, done = r.finish(r.maya, str((data(started) or {}).get("authorizeUrl") or ""), "maya.eu")
    check(
        "1 Maya's own account signs in at the EU org",
        started.status_code == 200 and opened.startswith(f"{sf['eu_login_url']}/authorize") and done.status_code == 200,
        {"started": started.text[:200], "opened": opened[:160], "done": done.text[:200]},
    )
    # 2. A run acting for nobody (a schedule, a workflow step) that names her account is refused, and nothing is sent.
    before = r.calls_so_far()
    nobody = r.call(accounts={SF: MINE})
    check(
        "2 a run acting for nobody that names Maya's own account is refused ACCOUNT_NOT_YOURS, and nothing is sent",
        nobody.status_code == 403 and code_of(nobody) == "ACCOUNT_NOT_YOURS" and r.hosts(before) == [],
        {"call": nobody.text[:300], "hosts": r.hosts(before)},
    )
    # 3. A run Priya started that names Maya's account is refused the same way.
    for_priya = r.call(accounts={SF: MINE}, acting_for=PRIYA)
    check(
        "3 a run acting for Priya that names Maya's own account is refused ACCOUNT_NOT_YOURS, and nothing is sent",
        for_priya.status_code == 403 and code_of(for_priya) == "ACCOUNT_NOT_YOURS" and r.hosts(before) == [],
        {"call": for_priya.text[:300], "hosts": r.hosts(before)},
    )
    # 4. Maya's own chat may name it: the call acts for her and reaches the EU org.
    for_maya = r.call(accounts={SF: MINE}, acting_for=MAYA)
    check(
        "4 Maya's own call naming her account runs, in the EU org",
        for_maya.status_code == 200 and r.hosts(before) == [sf["eu_base"].removeprefix("https://")],
        {"call": for_maya.text[:300], "hosts": r.hosts(before)},
    )
    # 5. Another team's account is never found from this team, by name.
    platform_team = {**r.priya, "X-Team-Id": "team_platform"}
    other = r.gw.put(
        f"/v1/apps/{SF}/team",
        json={"enabled": True, "accountName": "Brand org", "settings": {"login_url": sf["login_url"]}},
        headers=platform_team,
    )
    before = r.calls_so_far()
    crossed = r.call(accounts={SF: "Brand org"})
    check(
        "5 a run in Operations naming the Platform team's Brand org is refused ACCOUNT_NOT_FOUND, and nothing is sent",
        other.status_code == 200 and crossed.status_code == 404 and code_of(crossed) == "ACCOUNT_NOT_FOUND"
        and r.hosts(before) == [],
        {"other": other.text[:200], "call": crossed.text[:300], "hosts": r.hosts(before)},
    )  # fmt: skip

finish()
