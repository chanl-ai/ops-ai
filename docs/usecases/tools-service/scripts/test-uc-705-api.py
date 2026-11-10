"""uc-705, api layer: docs/usecases/tools-service/callers-from-before-several-accounts-keep-working.md.

A caller that sends one account name as `runContext.account` still has it honoured, and the older bodyless add of a
person's second account still works (lib/several_accounts.py)."""

from __future__ import annotations

from several_accounts import SF, add_org, code_of, retail_on, rig
from usecase_harness import check, data, finish

with rig("uc-705") as r:
    sf = r.sf
    retail_on(r, sign_in="person_or_team")
    add_org(r, "EU org", sf["eu_login_url"], "kestrel.eu")
    # 1. The older single string still names the account, and the map wins over it when both are sent.
    before = r.calls_so_far()
    old = r.call(account="EU org")
    both = r.call(account="EU org", accounts={SF: "Retail org"})
    check(
        "1 runContext.account 'EU org' runs in the EU org; with runContext.accounts as well, the map wins",
        old.status_code == 200 and both.status_code == 200
        and r.hosts(before) == [sf["eu_base"].removeprefix("https://"), sf["api_base"].removeprefix("https://")],
        {"old": old.text[:200], "both": both.text[:200], "hosts": r.hosts(before)},
    )  # fmt: skip
    # 2. An unknown name in the older string is refused as an unknown name in the map is.
    ghost = r.call(account="Ghost org")
    check(
        "2 runContext.account naming no account is refused ACCOUNT_NOT_FOUND",
        code_of(ghost) == "ACCOUNT_NOT_FOUND",
        ghost.text[:200],
    )
    # 3. The older add of a second own account, with no body, starts a sign-in where the first one signs in.
    started = r.gw.post(f"/v1/me/accounts/{r.ids['retail']}/another", headers=r.maya)
    opened = str((data(started) or {}).get("authorizeUrl") or "")
    check(
        "3 POST /another with no body starts a sign-in at the first account's address",
        started.status_code == 200 and opened.startswith(f"{sf['login_url']}/authorize"),
        {"started": started.text[:200], "opened": opened[:160]},
    )

finish()
