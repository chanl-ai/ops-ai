"""The development seed: one tenant, one team and a person per role from the service's seed/ file, safe to run twice,
and every seeded person signs in with the demo password into the team with their role."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops_platform.bootstrap import FirstAdmin, bootstrap
from ops_platform.seed import seed
from ops_platform.store.lifecycle import owner_query
from ops_platform.store.seeding import SeedConflictError
from ops_platform.store.tenancy import TenantDb
from ops_service_kit.ids import new_id
from ops_service_kit.settings import Settings

from .conftest import DEMO_PASSWORD, Platform

PEOPLE = Path(__file__).parents[1] / "seed" / "people.json"


async def test_seeded_people_sign_in_with_their_roles_and_a_second_run_changes_nothing(
    platform: Platform, database_url: str
) -> None:
    await seed(database_url, PEOPLE)
    await seed(database_url, PEOPLE)
    for person in json.loads(PEOPLE.read_text())["people"]:
        r = await platform.public.post("/v1/auth/sign-in", json={"email": person["email"], "password": DEMO_PASSWORD})
        assert r.status_code == 200, (person["email"], r.text)
        assert r.json()["data"]["principal"]["roles"] == person["teams"]


async def test_a_role_changed_through_the_api_stays_when_the_seed_runs_again(
    platform: Platform, database_url: str
) -> None:
    # The seed runs on every start; it adds what is missing and never undoes a person's change.
    await seed(database_url, PEOPLE)
    admin = await platform.public.post(
        "/v1/auth/sign-in", json={"email": "p.shah@harborpine.example", "password": DEMO_PASSWORD}
    )
    h = {"Authorization": f"Bearer {admin.json()['data']['token']}", "X-Team-Id": "team_ops"}
    changed = await platform.public.post(
        "/v1/settings/members/role", headers=h, json={"ids": ["mem_usr_builder_team_ops"], "role": "admin"}
    )
    assert changed.status_code == 200, changed.text
    await seed(database_url, PEOPLE)
    r = await platform.public.post(
        "/v1/auth/sign-in", json={"email": "j.richardson@harborpine.example", "password": DEMO_PASSWORD}
    )
    assert r.json()["data"]["principal"]["roles"] == {"team_ops": "admin"}, r.text


async def test_a_seeded_id_held_by_another_tenant_stops_the_seed(database_url: str, tmp_path: Path) -> None:
    await seed(database_url, PEOPLE)
    data = json.loads(PEOPLE.read_text())
    data["tenant"]["id"] = "ten_moved"
    moved = tmp_path / "people.json"
    moved.write_text(json.dumps(data))
    with pytest.raises(SeedConflictError, match="another tenant than ten_moved; rebuild the dev database"):
        await seed(database_url, moved)


async def test_the_everyone_admin_seed_makes_each_person_admin_everywhere_and_off_leaves_it(
    platform: Platform, database_url: str
) -> None:
    """Dev only (OPS_SEED_EVERYONE_ADMIN): a person tried in the console is held back by no role. Like every seeded row
    it is only added, so turning it off later leaves it; the API takes it away."""
    teams = {t["id"] for t in json.loads(PEOPLE.read_text())["teams"]}

    async def james_teams() -> set[str]:
        r = await platform.public.post(
            "/v1/auth/sign-in", json={"email": "j.richardson@harborpine.example", "password": DEMO_PASSWORD}
        )
        return set(r.json()["data"]["principal"]["teamIds"])

    await seed(database_url, PEOPLE, everyone_admin=True)
    assert await james_teams() == teams
    await seed(database_url, PEOPLE, everyone_admin=False)
    assert await james_teams() == teams


async def test_a_seeded_persons_new_address_reaches_a_database_seeded_before_it(
    platform: Platform, database_url: str, tmp_path: Path
) -> None:
    # The demo bank's rename moved every seeded address; a database seeded before it signs in with the new one.
    data = json.loads(PEOPLE.read_text())
    before = json.loads(PEOPLE.read_text())
    for person in before["people"]:
        person["email"] = person["email"].replace("@harborpine.example", "@northfieldbank.com")
    old = tmp_path / "people-before.json"
    old.write_text(json.dumps(before))
    await seed(database_url, old)
    await seed(database_url, PEOPLE)
    for person in data["people"]:
        r = await platform.public.post("/v1/auth/sign-in", json={"email": person["email"], "password": DEMO_PASSWORD})
        assert r.status_code == 200, (person["email"], r.text)


async def test_a_stack_seeded_as_shipped_gives_each_person_only_their_own_roles(
    platform: Platform, database_url: str, tmp_path: Path
) -> None:
    """The start-up seed with the install's settings: no one is made admin in every team unless the install
    asks, so a viewer on a `make up` stack is a viewer and a role test there means something. A person no earlier test
    seeded, since the seed only adds rows."""
    data = json.loads(PEOPLE.read_text())
    data["people"].append(
        {
            "id": "usr_c615_viewer",
            "name": "Vera Lind",
            "email": "v.lind@harborpine.example",
            "teams": {"team_ops": "viewer"},
        }
    )
    with_vera = tmp_path / "people.json"
    with_vera.write_text(json.dumps(data))
    await seed(database_url, with_vera, everyone_admin=Settings().seed_everyone_admin)
    r = await platform.public.post(
        "/v1/auth/sign-in", json={"email": "v.lind@harborpine.example", "password": DEMO_PASSWORD}
    )
    assert r.json()["data"]["principal"]["teamIds"] == ["team_ops"], r.json()["data"]["principal"]


async def test_a_fresh_dev_install_has_one_owner_who_signs_in(
    platform: Platform, database_url: str, tmp_path: Path
) -> None:
    """`make up` runs the first-admin bootstrap (a generated password nobody types), then the people seed. The owner,
    the only person holding install.manage, must be the seed's admin who signs in with the demo password, not the
    bootstrap's. A fresh tenant with the seed's people under fresh ids stands in for a new database."""
    run = new_id("t")[2:10]
    data = json.loads(PEOPLE.read_text())
    tenant, security = f"ten_{run}", f"team_security_{run}"
    data["tenant"]["id"] = tenant
    for team in data["teams"]:
        team["id"] = f"{team['id']}_{run}"
    for person in data["people"]:
        person["id"] = f"{person['id']}_{run}"
        person["email"] = person["email"].replace("@", f"+{run}@")
        person["teams"] = {f"{t}_{run}": role for t, role in person["teams"].items()}
    data["owner"] = f"{data['owner']}_{run}"
    fresh = tmp_path / "people.json"
    fresh.write_text(json.dumps(data))
    first = FirstAdmin(
        tenant_id=tenant, tenant_name="Harbor & Pine Bank", team_id=security, team_name="Security",
        email=f"dev-admin+{run}@harborpine.example", name="Alex Morgan", password="generated-password-1",
    )  # fmt: skip
    assert await bootstrap(database_url, first, iterations=1000) == "created"
    await seed(database_url, fresh, security_team=security)

    db = TenantDb.open(database_url)
    async with db.tenant_tx(tenant) as c:
        owners = [str(r) for r in (await c.execute(owner_query(tenant))).scalars()]
    await db.engine.dispose()
    named = next(p for p in data["people"] if p["id"] == data["owner"])
    assert owners == [named["id"]]
    r = await platform.public.post("/v1/auth/sign-in", json={"email": named["email"], "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['data']['token']}"}
    held = (await platform.public.get("/v1/me/permissions", headers=h)).json()["data"]["workspace"]
    assert {(c["area"], c["action"]) for c in held} >= {("install", "manage")}, held
