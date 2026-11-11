"""uc-702, api layer: docs/usecases/tools-service/a-person-adds-a-second-account-of-their-own.md.

A member adds a second account of their own with a name and their own server's address: it signs in there rather than
where their first account does, both show on Connectors > Mine told apart, and once it is their default their calls
use it (lib/several_accounts.py, lib/fake_github.py)."""

from __future__ import annotations

from several_accounts import GH, MAYA, git_rig, issues, maya_second_github, my_github
from usecase_harness import check, finish

with git_rig("uc-702") as r:
    started, opened, done = maya_second_github(r)
    # 1. The second account signs in at the corp server, not where her first one does.
    check(
        "1 Maya's Corp account opens its sign-in at ghe.corp.test and finishes there",
        started.status_code == 200 and opened.startswith(f"{r.gh['corp_url']}/login/oauth/authorize")
        and done.status_code == 200,
        {"started": started.text[:200], "opened": opened[:160], "done": done.text[:200]},
    )  # fmt: skip
    # 2. Mine lists both of her accounts, told apart by their servers.
    row = my_github(r)
    mine = {
        str(a["name"]): [e["shown"] for e in a.get("identity") or []]
        for a in row.get("accounts") or []
        if a.get("state") == "connected"
    }
    check(
        "2 Connectors > Mine lists Platform server and Corp with their servers",
        (mine.get("Platform server") or [""])[0] == "github.test" and (mine.get("Corp") or [""])[0] == "ghe.corp.test",
        mine,
    )
    # 3. With two of her own and no default, a call asks which; once Corp is her default, her calls use it.
    asked = r.call(acting_for=MAYA)
    corp = next((a for a in row.get("accounts") or [] if a.get("name") == "Corp"), {})
    pinned = r.gw.put(f"/v1/apps/{GH}/accounts/{corp.get('connectionId')}/default", headers=r.maya)
    used = r.call(acting_for=MAYA)
    check(
        "3 with two and no default a call asks which; with Corp her default it answers the corp server's issue 412",
        (asked.json().get("error") or {}).get("code") == "ACCOUNT_CHOICE_NEEDED" and pinned.status_code == 200
        and issues(used) == [412] and any(a.get("primary") for a in my_github(r).get("accounts") or [] if a.get("name") == "Corp"),
        {"asked": asked.text[:200], "pinned": pinned.text[:200], "used": used.text[:300]},
    )  # fmt: skip

finish()
