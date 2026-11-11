"""uc-691, api layer: docs/usecases/tools-service/a-second-org-signs-in-at-its-own-address.md.

A team on Ops AI's app adds a second live Salesforce org at its own My Domain: it signs in there, keeps that org's
address, and a call naming it reaches that org, while the first account keeps its own (lib/several_accounts.py)."""

from __future__ import annotations

from several_accounts import SF, add_org, retail_on, rig
from usecase_harness import check, data, finish

with rig("uc-691") as r:
    sf = r.sf
    # 1. The first account, through Ops AI's app at the production org's My Domain.
    on = retail_on(r)
    first = r.found(r.priya, r.ids["retail"])
    check(
        "1 Retail org signs in at the production org and keeps its address",
        on.status_code == 200 and first.get("found:instance_url") == sf["api_base"],
        {"on": on.text[:200], "found": first},
    )
    # 2. A second live account, typed at the EU org's My Domain, signs in there, not at the first one's address.
    made, opened = add_org(r, "EU org", sf["eu_login_url"], "kestrel.eu")
    eu = r.found(r.priya, r.ids["EU org"])
    check(
        "2 EU org opens its sign-in at the EU org's My Domain and keeps the EU org's address",
        made.status_code == 201 and opened.startswith(f"{sf['eu_login_url']}/authorize")
        and eu.get("found:instance_url") == sf["eu_base"],
        {"made": made.text[:200], "opened": opened[:160], "found": eu},
    )  # fmt: skip
    # 3. A call naming EU org reaches the EU org; the fake answers a token only at its own org's host.
    before = r.calls_so_far()
    named = r.call(accounts={SF: "EU org"})
    check(
        "3 salesforce_query naming EU org is answered by the EU org",
        named.status_code == 200 and r.hosts(before) == [sf["eu_base"].removeprefix("https://")],
        {"call": named.text[:300], "hosts": r.hosts(before)},
    )
    # 4. The first account is unchanged: a call naming nothing still reaches the production org.
    before = r.calls_so_far()
    plain = r.call()
    after = r.found(r.priya, r.ids["retail"])
    check(
        "4 Retail org keeps its own address, and a call naming no account reaches the production org",
        plain.status_code == 200 and r.hosts(before) == [sf["api_base"].removeprefix("https://")]
        and after.get("found:instance_url") == sf["api_base"],
        {"call": plain.text[:300], "hosts": r.hosts(before), "found": after},
    )  # fmt: skip
    # 5. The auth config offers the first address as a default, which is what let step 2 type its own.
    page = data(r.gw.get(f"/v1/apps/{SF}", headers=r.priya)) or {}
    config = next((c for c in page.get("authConfigs") or [] if c.get("type") == "ops_ai"), {})
    place = next((f for f in config.get("fields") or [] if f.get("name") == "login_url"), {})
    check(
        "5 Ops AI's auth config keeps the first sign-in address as a default, not fixed",
        (place.get("value"), place.get("mode")) == (sf["login_url"], "default"),
        place,
    )

finish()
