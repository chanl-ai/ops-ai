"""The development seed: one tenant, one team and a person per role from the service's seed/ file, safe to run twice,
and every seeded person signs in with the demo password into the team with their role."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops_platform.seed import seed
from ops_platform.store.seeding import SeedConflictError

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
