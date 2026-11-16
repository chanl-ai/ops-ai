"""How many transactions an app's account and credential routes hold, by failure mode: a route opening one transaction
per store call, so one screen's read sees rows from different moments and a change can land without the row that goes
with it. The routes here only read and write this service's database; the ones that ask another party hold none
(`connections/routes.py`, `apps.py`). Seeded as the statement budget seeds a team."""

from __future__ import annotations

import json

import httpx

from ops_service_kit.logging import captured_logging
from ops_service_kit.testing import SeedTeam

from . import test_statement_budget as budget

app = budget.app
client = budget.client
seed_team = budget.seed_team


async def test_an_apps_accounts_and_credentials_each_hold_one_transaction(
    client: httpx.AsyncClient, seed_team: SeedTeam
) -> None:
    seeded = await seed_team(2)
    c, admin, app = client, dict(seeded.headers), budget.APP
    account, credential = seeded.ids["account_id"], seeded.ids["credential_id"]
    ledger = (await c.get(f"/v1/app-credentials/{credential}", headers=admin)).json()["data"]["app"]
    revision = (await c.get(f"/v1/apps/{app}/accounts/{account}", headers=admin)).json()["data"]["revision"]
    steps = [
        ("account", "GET", f"/v1/apps/{app}/accounts/{account}", None),
        ("rename", "PATCH", f"/v1/apps/{app}/accounts/{account}", {"revision": revision, "name": "Desk tx"}),
        ("mine", "GET", "/v1/me/accounts", None),
        ("add", "POST", f"/v1/apps/{app}/accounts", {"name": "Desk tx 2", "credentials": {"token": "t-tx"}}),
        ("team default", "PUT", f"/v1/apps/{app}/accounts/{account}/team-default", None),
        ("turn on", "PUT", f"/v1/apps/{app}/team", {"enabled": True, "credentials": {"token": "t-1"}}),
        ("choices", "GET", f"/v1/apps/{app}/accounts", None),
        ("apps", "GET", "/v1/apps", None),
        ("credentials", "GET", "/v1/app-credentials", None),
        ("new credential", "POST", "/v1/app-credentials", {"app": ledger, "clientId": "tx", "clientSecret": "tx-s"}),
        ("credential", "GET", f"/v1/app-credentials/{credential}", None),
        ("edit credential", "PATCH", f"/v1/app-credentials/{credential}", {"name": "Ledger tx"}),
        ("secret", "PUT", f"/v1/app-credentials/{credential}/secret", {"clientSecret": "tx-s-2"}),
        ("delete credential", "DELETE", f"/v1/app-credentials/{credential}?move=true", None),
        ("page", "GET", f"/v1/apps/{app}", None),
    ]
    counts: dict[str, int] = {}
    for name, method, path, body in steps:
        r, counts[name] = await _counted(c, method, path, body, admin)
        assert r.status_code in (200, 201, 204), (name, r.text)
    assert counts == {name: 1 for name, *_ in steps}, counts


async def _counted(
    c: httpx.AsyncClient, method: str, path: str, body: object, headers: dict[str, str]
) -> tuple[httpx.Response, int]:
    """The answer and how many transactions the request held, from its request line."""
    with captured_logging("tools-apps-tx") as stream:
        r = await c.request(method, path, json=body, headers=headers)
    line = next(json.loads(x) for x in stream.getvalue().splitlines() if '"http.request"' in x)
    return r, int(line["db.tx_count"])
