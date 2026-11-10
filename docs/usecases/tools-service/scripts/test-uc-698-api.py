"""uc-698, api layer: docs/usecases/tools-service/a-deleted-account-name-is-refused.md.

A call naming an account that was deleted is refused ACCOUNT_NOT_FOUND and is never sent to the team's default account
(lib/several_accounts.py)."""

from __future__ import annotations

from several_accounts import SF, add_org, code_of, retail_on, rig
from usecase_harness import check, finish

with rig("uc-698") as r:
    sf = r.sf
    retail_on(r)
    add_org(r, "EU org", sf["eu_login_url"], "kestrel.eu")
    before = r.calls_so_far()
    first = r.call(accounts={SF: "EU org"})
    check(
        "1 a call naming EU org reaches the EU org",
        first.status_code == 200 and r.hosts(before) == [sf["eu_base"].removeprefix("https://")],
        {"call": first.text[:300], "hosts": r.hosts(before)},
    )
    gone = r.gw.delete(f"/v1/apps/{SF}/accounts/{r.ids['EU org']}", headers=r.priya)
    before = r.calls_so_far()
    named = r.call(accounts={SF: "EU org"})
    check(
        "2 once EU org is deleted, a call naming it is refused ACCOUNT_NOT_FOUND and nothing reaches Retail org",
        gone.status_code == 204 and named.status_code == 404 and code_of(named) == "ACCOUNT_NOT_FOUND"
        and r.hosts(before) == [],
        {"deleted": gone.status_code, "call": named.text[:300], "hosts": r.hosts(before)},
    )  # fmt: skip

finish()
