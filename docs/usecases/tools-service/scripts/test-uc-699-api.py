"""uc-699, api layer: docs/usecases/tools-service/two-accounts-never-share-a-name.md.

Two admins adding an account of one app with the same name at the same moment get one account and one 409
account_name_taken; a person's own second account may not take a name the team's account holds; a lookup by the
name finds exactly one (lib/several_accounts.py). The database's filtered unique index is the guarantee: the route's
own check passes for both of two adds that arrive together."""

from __future__ import annotations

import threading
from typing import Any

from several_accounts import SF, code_of, retail_on, rig
from usecase_harness import check, data, finish

ROUNDS = 4

with rig("uc-699") as r:
    sf = r.sf
    retail_on(r, sign_in="person_or_team")
    # 1. Two adds of one name at the same moment, several rounds, so the two requests overlap in the route.
    outcomes: list[list[tuple[int, str]]] = []
    for n in range(ROUNDS):
        name = f"EU org {n}"
        gate = threading.Barrier(2)
        got: list[tuple[int, str]] = []

        def add(name: str = name, gate: threading.Barrier = gate, got: list[tuple[int, str]] = got) -> None:
            gate.wait()
            made = r.gw.post(
                f"/v1/apps/{SF}/accounts",
                json={"name": name, "settings": {"login_url": sf["eu_login_url"]}},
                headers=r.priya,
            )
            got.append((made.status_code, code_of(made)))

        both = [threading.Thread(target=add) for _ in range(2)]
        for t in both:
            t.start()
        for t in both:
            t.join()
        outcomes.append(sorted(got))
    check(
        "1 of two adds with one name at the same moment, one makes the account and the other is refused 409 "
        "account_name_taken, in every round",
        all(o == [(201, ""), (409, "account_name_taken")] for o in outcomes),
        outcomes,
    )
    # 2. The same name in another case is the same name.
    shouted = r.gw.post(f"/v1/apps/{SF}/accounts", json={"name": "eu ORG 0"}, headers=r.priya)
    check(
        "2 a name that differs only in case is refused 409 account_name_taken",
        shouted.status_code == 409 and code_of(shouted) == "account_name_taken",
        shouted.text[:200],
    )
    # 3. Maya's own second account may not take the name either.
    mine = r.gw.post(
        f"/v1/me/accounts/{r.ids['retail']}/another",
        json={"name": "EU org 0", "settings": {"login_url": sf["eu_login_url"]}},
        headers=r.maya,
    )
    check(
        "3 Maya's own second account named like a team account is refused 409 account_name_taken",
        mine.status_code == 409 and code_of(mine) == "account_name_taken",
        mine.text[:200],
    )
    # 4. A rename onto another account's name is refused too.
    row = r.row(r.priya, r.ids["retail"])
    renamed = r.gw.patch(
        f"/v1/apps/{SF}/accounts/{r.ids['retail']}",
        json={"revision": row.get("revision", 1), "name": "EU ORG 1"},
        headers=r.priya,
    )
    check(
        "4 renaming Retail org onto EU org 1's name is refused 409 account_name_taken",
        renamed.status_code == 409 and code_of(renamed) == "account_name_taken",
        renamed.text[:200],
    )
    # 5. A lookup by the name finds exactly one account.
    found: Any = data(r.gw.get(f"/v1/apps/{SF}/accounts", params={"name": "eu org 0"}, headers=r.priya)) or []
    check("5 a lookup of 'eu org 0' finds exactly one account", len(found) == 1, found)

finish()
