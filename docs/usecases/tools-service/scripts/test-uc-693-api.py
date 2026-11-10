"""uc-693, api layer: docs/usecases/tools-service/every-account-says-what-it-points-at.md.

Every account row says what it points at: on GitHub, which declares no identity, on the app's Accounts list and on a
person's Connectors > Mine; and on a custom app, by its address. Two accounts of one app never read the same
(lib/several_accounts.py, lib/fake_github.py)."""

from __future__ import annotations

from typing import Any

from several_accounts import GH, git_rig, github_on
from usecase_harness import check, data, finish


def shown(row: dict[str, Any]) -> list[str]:
    return [str(e.get("shown")) for e in row.get("identity") or []]


with git_rig("uc-693") as r:
    gh = r.gh
    github_on(r, sign_in="person_or_team")
    made = r.gw.post(
        f"/v1/apps/{GH}/accounts",
        json={"name": "Corp server", "settings": {"web_url": gh["corp_url"]}},
        headers=r.priya,
    )
    r.ids["corp"] = str((data(made) or {}).get("id") or "con_missing")
    r.sign_in(r.priya, r.ids["corp"])
    # 1. The Accounts list: each row says its server, and the two differ.
    page = data(r.gw.get(f"/v1/apps/{GH}", headers=r.priya)) or {}
    rows = {str(a["name"]): shown(a) for a in page.get("accounts") or [] if a.get("kind") == "team"}
    check(
        "1 on the Accounts list each GitHub account names its server, and the two differ",
        (rows.get("Platform server") or [""])[0] == "github.test"
        and (rows.get("Corp server") or [""])[0] == "ghe.corp.test",
        rows,
    )
    # 4. Where each points, for text a model reads, is the server and never who signed in.
    points = {str(a["name"]): a.get("pointsAt") for a in page.get("accounts") or [] if a.get("kind") == "team"}
    check(
        "4 each team account's pointsAt is its server, never who signed in",
        points.get("Platform server") == "github.test" and points.get("Corp server") == "ghe.corp.test",
        points,
    )
    # 2. Connectors > Mine: Maya signs in on Platform server and adds Corp of her own; both rows say their server.
    _, mine_done = r.sign_in(r.maya, r.ids["public"], as_="self")
    started = r.gw.post(
        f"/v1/me/accounts/{r.ids['public']}/another",
        json={"name": "Corp · Maya", "settings": {"web_url": gh["corp_url"]}},
        headers=r.maya,
    )
    r.finish(r.maya, str((data(started) or {}).get("authorizeUrl") or ""))
    connectors = data(r.gw.get("/v1/me/connections", headers=r.maya)) or []
    gh_row = next((c for c in connectors if c.get("appId") == GH), {})
    mine = {str(a["name"]): shown(a) for a in gh_row.get("accounts") or [] if a.get("state") == "connected"}
    firsts = [v[0] if v else "" for v in mine.values()]
    check(
        "2 on Maya's Connectors each of her two GitHub accounts names its server, and the two differ",
        mine_done.status_code == 200 and started.status_code == 200 and sorted(mine) == ["Corp · Maya", "Platform server"]
        and sorted(firsts) == ["ghe.corp.test", "github.test"],
        {"mine": mine, "started": started.text[:200]},
    )  # fmt: skip
    # 3. A custom app's two accounts say their addresses.
    app = data(r.gw.post("/v1/apps", json={"name": "uc693 ledger", "authKind": "none"}, headers=r.priya)) or {}
    app_id = str(app.get("id") or "app_missing")
    first = data(r.gw.get(f"/v1/apps/{app_id}/accounts/{app_id}", headers=r.priya)) or {}
    r.gw.patch(
        f"/v1/apps/{app_id}/accounts/{app_id}",
        json={"revision": first.get("revision", 1), "settings": {"baseUrl": "https://ledger.north.test"}},
        headers=r.priya,
    )
    second = r.gw.post(
        f"/v1/apps/{app_id}/accounts",
        json={"name": "South ledger", "credentials": {"baseUrl": "https://ledger.south.test"}},
        headers=r.priya,
    )
    listed = data(r.gw.get(f"/v1/apps/{app_id}/accounts", headers=r.priya)) or []
    custom = sorted(shown(a)[0] if shown(a) else "" for a in listed)
    check(
        "3 a custom app's two accounts name their addresses, and the two differ",
        second.status_code == 201 and custom == ["ledger.north.test", "ledger.south.test"],
        {"second": second.text[:200], "listed": listed},
    )

finish()
