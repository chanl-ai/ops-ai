"""uc-709, api layer: docs/usecases/tools-service/changing-who-signs-in-to-each-person.md.

Changing who signs in to an account from the shared team login to each person, with the team's login kept for runs
nobody started: a call naming the account for a person then signs in as that person, and a call acting for nobody
(a schedule) keeps the shared login. The fake Salesforce records whose token each query came with
(lib/several_accounts.py)."""

from __future__ import annotations

from typing import Any

from several_accounts import MAYA, QUERY_PATH, SF, add_org, retail_on, rig
from usecase_harness import check, data, finish


def who_since(r: Any, since: int) -> list[str]:
    """Whose token each query the fake answered after `since` calls came with."""
    return [c["who"] for c in r.sf["fake"].state()["calls"][since:] if c["path"].endswith(QUERY_PATH)]


with rig("uc-709") as r:
    retail_on(r)
    add_org(r, "EU org", r.sf["eu_login_url"], "kestrel.eu")
    eu = {SF: "EU org"}
    # 1. While the team's login is shared, a call for Maya signs in as the team.
    since = r.calls_so_far()
    shared = r.call(accounts=eu, acting_for=MAYA)
    before = who_since(r, since)
    check("1 while EU org signs in as the team, a call for Maya uses the team's login",
          shared.status_code == 200 and len(before) == 1 and "kestrel.eu" in before[0], {"who": before})  # fmt: skip
    # 2. Priya changes who signs in to each person, keeping the team's login for runs nobody started; Maya signs in.
    row = r.row(r.priya, r.ids["EU org"])
    changed = r.gw.patch(
        f"/v1/apps/{SF}/accounts/{r.ids['EU org']}",
        json={"revision": row.get("revision", 1), "signIn": "person_or_team", "teamBackup": True},
        headers=r.priya,
    )
    _, mine = r.sign_in(r.maya, r.ids["EU org"], "maya.eu", as_="self")
    after_row = r.row(r.priya, r.ids["EU org"])
    check(
        "2 EU org now signs in as each person, and Maya holds her own sign-in on it",
        changed.status_code == 200 and mine.status_code == 200 and after_row.get("signIn") == "person_or_team"
        and (after_row.get("peopleSignedIn") or 0) >= 1,
        {"changed": changed.text[:300], "mine": mine.text[:200], "row": {k: after_row.get(k) for k in ("signIn", "peopleSignedIn")}},
    )  # fmt: skip
    # 3. A call for Maya now signs in as Maya, at EU org.
    since = r.calls_so_far()
    own = r.call(accounts=eu, acting_for=MAYA)
    as_maya = who_since(r, since)
    hosts = r.hosts(since)
    check("3 a call naming EU org for Maya signs in as Maya, at EU org",
          own.status_code == 200 and len(as_maya) == 1 and "maya.eu" in as_maya[0] and all("kestrel-eu" in h for h in hosts),
          {"who": as_maya, "hosts": hosts, "answer": own.text[:200]})  # fmt: skip
    # 4. A run nobody started (a schedule) keeps the shared login.
    since = r.calls_so_far()
    scheduled = r.call(accounts=eu)
    as_team = who_since(r, since)
    check("4 a call acting for nobody naming EU org keeps the team's login",
          scheduled.status_code == 200 and len(as_team) == 1 and "kestrel.eu" in as_team[0],
          {"who": as_team, "answer": scheduled.text[:200], "data": (data(scheduled) or {}).get("status") if scheduled.status_code == 200 else None})  # fmt: skip

finish()
