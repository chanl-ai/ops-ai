"""uc-706, api layer: docs/usecases/tools-service/a-package-app-runs-on-the-chosen-org.md.

A package app (the fictional Loan desk, lib/plugins/loan_desk) runs on Salesforce's accounts: a call naming the org
that has the package reads its record there, and a call on an org without it is refused before it leaves tools-service
(lib/several_accounts.py)."""

from __future__ import annotations

import time
from typing import Any

from fake_salesforce import LOAN_ID
from several_accounts import LOANS, SF, add_org, code_of, retail_on, rig
from usecase_harness import check, data, finish

PACKAGE = "demo.loan-desk"


def packages(r: Any, account: str) -> dict[str, Any]:
    """The package check on the account's last test, polled while the test that follows a sign-in lands."""
    for _ in range(40):
        got = data(r.gw.get(f"/v1/apps/{SF}/accounts/{account}", headers=r.priya)) or {}
        found = dict((got.get("health") or {}).get("packages") or {})
        if PACKAGE in found:
            return found
        time.sleep(0.25)
    return {}


with rig("uc-706", with_package=True) as r:
    # 1. Salesforce's two orgs, then the package, which makes no account of its own.
    retail_on(r)
    add_org(r, "EU org", r.sf["eu_login_url"], "kestrel.eu")
    on = r.gw.put(f"/v1/apps/{LOANS}/team", json={"enabled": True}, headers=r.priya)
    check(
        "1 Loan desk turns on with no account of its own",
        on.status_code == 200 and not (data(on) or {}).get("connectionId"),
        on.text[:300],
    )
    # 2. Each sign-in's test checked the org for the loan object.
    retail, eu = packages(r, r.ids["retail"]), packages(r, r.ids["EU org"])
    check(
        "2 Retail org lists the loan object missing and EU org lists nothing missing",
        retail.get(PACKAGE, {}).get("missing") == ["LNDK__Loan__c"] and eu.get(PACKAGE, {}).get("missing") == [],
        {"retail": retail, "eu": eu},
    )
    # 3. Naming EU org under Salesforce: the EU org answers with its loan.
    before = r.calls_so_far()
    named = r.call(accounts={SF: "EU org"}, tool="loan_desk_get_loan", args={"id": LOAN_ID})
    out = dict((data(named) or {}).get("output") or {}) if named.status_code == 200 else {}
    hosts = [c["host"] for c in r.sf["fake"].state()["calls"][before:]]
    check(
        "3 loan_desk_get_loan naming EU org reads the loan at the EU org with EU org's account",
        named.status_code == 200 and out.get("Name") == "Harbor bakery expansion"
        and hosts == [r.sf["eu_base"].removeprefix("https://")]
        and r.logged(named).get("connectionId") == r.ids["EU org"],
        {"call": named.text[:300], "hosts": hosts, "log": r.logged(named)},
    )  # fmt: skip
    # 4. Naming nothing takes the team default, Retail org, which has no package: refused before any request.
    before = r.calls_so_far()
    plain = r.call(tool="loan_desk_get_loan", args={"id": LOAN_ID})
    check(
        "4 a call on Retail org is refused with PACKAGE_MISSING and reaches no org",
        plain.status_code == 409 and code_of(plain) == "PACKAGE_MISSING" and "Retail org" in plain.text
        and r.calls_so_far() == before,
        {"call": plain.text[:300], "calls": r.calls_so_far() - before},
    )  # fmt: skip
    # 5. An account named under the package's own app, which has none, is refused.
    before = r.calls_so_far()
    wrong = r.call(accounts={LOANS: "EU org"}, tool="loan_desk_get_loan", args={"id": LOAN_ID})
    check(
        "5 an account named under Loan desk's own app is refused with ACCOUNT_NOT_FOUND",
        wrong.status_code == 404 and code_of(wrong) == "ACCOUNT_NOT_FOUND" and r.calls_so_far() == before,
        {"call": wrong.text[:300]},
    )

finish()
