"""uc-692, api layer: docs/usecases/tools-service/a-second-server-signs-in-at-its-own-address.md.

The same as uc-691 on GitHub, an app with no identity setting and nothing read from its token answer: a second
account at a company's own GitHub server signs in there, and a call naming it acts with that server's sign-in
(lib/several_accounts.py, lib/fake_github.py)."""

from __future__ import annotations

from several_accounts import GH, git_rig, github_on, issues
from usecase_harness import check, data, finish

with git_rig("uc-692") as r:
    gh = r.gh
    on = github_on(r)
    # 1. A second account at the corp server signs in there.
    made = r.gw.post(
        f"/v1/apps/{GH}/accounts",
        json={"name": "Corp server", "settings": {"web_url": gh["corp_url"]}},
        headers=r.priya,
    )
    r.ids["corp"] = str((data(made) or {}).get("id") or "con_missing")
    opened, done = r.sign_in(r.priya, r.ids["corp"])
    check(
        "1 Corp server opens its sign-in at ghe.corp.test and the sign-in finishes there",
        on.status_code == 200 and made.status_code == 201 and done.status_code == 200
        and opened.startswith(f"{gh['corp_url']}/login/oauth/authorize")
        and r.gh["fake"].state()["issued"] == ["github.test", "ghe.corp.test"],
        {"on": on.text[:200], "made": made.text[:200], "opened": opened[:160], "done": done.text[:200],
         "issued": r.gh["fake"].state()["issued"]},
    )  # fmt: skip
    # 2. A call naming Corp server acts with the corp server's sign-in, and answers its issue.
    named = r.call({GH: "Corp server"})
    check(
        "2 list_issues naming Corp server answers the corp server's issue 412",
        named.status_code == 200 and issues(named) == [412],
        named.text[:300],
    )
    # 3. A call naming nothing stays on the team's default, Platform server.
    plain = r.call()
    check("3 list_issues naming no account answers github.test's issue 7", issues(plain) == [7], plain.text[:300])

finish()
