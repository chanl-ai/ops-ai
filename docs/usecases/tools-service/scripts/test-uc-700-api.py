"""uc-700, api layer: docs/usecases/tools-service/a-test-run-never-uses-a-named-live-account.md.

A test run naming a live account signs in with the app's test account; with no test account it is refused
SANDBOX_REQUIRED. A live run naming the same account uses it (lib/several_accounts.py)."""

from __future__ import annotations

from several_accounts import SF, add_org, code_of, retail_on, rig
from usecase_harness import check, finish

with rig("uc-700", with_agents=True) as r:
    sf = r.sf
    retail_on(r)
    add_org(r, "EU org", sf["eu_login_url"], "kestrel.eu")
    made, _ = add_org(r, "UAT", sf["sandbox_login_url"], "kestrel.uat", sandbox=True)
    uat_host, eu_host = sf["sandbox_base"].removeprefix("https://"), sf["eu_base"].removeprefix("https://")
    # 1. A live run naming EU org is in the EU org.
    before = r.calls_so_far()
    live = r.call(accounts={SF: "EU org"})
    check(
        "1 a live run naming EU org is answered by the EU org",
        made.status_code == 201 and live.status_code == 200 and r.hosts(before) == [eu_host],
        {"made": made.text[:200], "call": live.text[:300], "hosts": r.hosts(before)},
    )
    # 2. A test run naming EU org is in the sandbox, and its log row says test and names the sandbox account.
    before = r.calls_so_far()
    test = r.call(accounts={SF: "EU org"}, environment="test")
    row = r.logged(test)
    check(
        "2 a test run naming EU org is answered by the sandbox, logged as test on the UAT account",
        test.status_code == 200 and r.hosts(before) == [uat_host]
        and (row.get("environment"), row.get("connectionId")) == ("test", r.ids["UAT"]),
        {"call": test.text[:300], "hosts": r.hosts(before), "row": {k: row.get(k) for k in ("environment", "connectionId")}},
    )  # fmt: skip
    # 3. With the test account deleted, a test run naming EU org is refused and nothing is sent.
    gone = r.gw.delete(f"/v1/apps/{SF}/accounts/{r.ids['UAT']}", headers=r.priya)
    before = r.calls_so_far()
    refused = r.call(accounts={SF: "EU org"}, environment="test")
    check(
        "3 with no test account, a test run naming EU org is refused SANDBOX_REQUIRED and nothing is sent",
        gone.status_code == 204 and code_of(refused) == "SANDBOX_REQUIRED" and r.hosts(before) == [],
        {"deleted": gone.status_code, "call": refused.text[:300], "hosts": r.hosts(before)},
    )

finish()
