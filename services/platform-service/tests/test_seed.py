"""The development seed: one tenant, one team and a person per role from a fixture file, safe to run twice, and every
seeded person signs in with the demo password into the team with their role."""

from __future__ import annotations

import json
from pathlib import Path

from ops_platform.seed import seed

from .conftest import DEMO_PASSWORD, Platform

PEOPLE = Path(__file__).parent / "fixtures" / "people.json"


async def test_seeded_people_sign_in_with_their_roles_and_a_second_run_changes_nothing(
    platform: Platform, database_url: str
) -> None:
    await seed(database_url, PEOPLE)
    await seed(database_url, PEOPLE)
    for person in json.loads(PEOPLE.read_text())["people"]:
        r = await platform.public.post("/v1/auth/sign-in", json={"email": person["email"], "password": DEMO_PASSWORD})
        assert r.status_code == 200, (person["email"], r.text)
        assert r.json()["data"]["principal"]["roles"] == person["teams"]
