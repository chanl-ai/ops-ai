"""The team's people as picker choices (a Human Task sent back to a person), by failure mode: a search that does not
reach the query (every member listed), a stored email that does not resolve to its name, and someone who may not decide
reviews reading the team's people."""

from __future__ import annotations

from .conftest import DEMO_PASSWORD, SignInRig


async def _headers(rig: SignInRig, email: str, team: str) -> dict[str, str]:
    r = await rig.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": team}


async def _team_of(rig: SignInRig, person: str) -> str:
    r = await rig.public.get(f"/v1/people/{person}/permissions", headers=rig.admin)
    assert r.status_code == 200, r.text
    return str(r.json()["data"]["teams"][0]["teamId"])


async def test_a_search_and_stored_emails_answer_from_the_query(signin: SignInRig) -> None:
    approver = f"approver@{signin.zone}"
    team = await _team_of(signin, await signin.person(approver, role="approver"))
    h = await _headers(signin, approver, team)
    found = await signin.public.get("/v1/settings/members/options", params={"search": "APPROV"}, headers=h)
    assert found.status_code == 200, found.text
    assert [o["id"] for o in found.json()["data"]["data"]] == [approver], found.text
    none = await signin.public.get("/v1/settings/members/options", params={"search": "nobody-by-this-name"}, headers=h)
    assert none.json()["data"]["data"] == [], none.text
    named = await signin.public.get("/v1/settings/members/options", params={"ids": [approver.upper()]}, headers=h)
    assert [o["id"] for o in named.json()["data"]["data"]] == [approver], named.text


async def test_a_person_who_cannot_decide_reviews_cannot_list_the_team(signin: SignInRig) -> None:
    viewer = f"viewer@{signin.zone}"
    team = await _team_of(signin, await signin.person(viewer, role="viewer"))
    r = await signin.public.get("/v1/settings/members/options", headers=await _headers(signin, viewer, team))
    assert r.status_code == 403, r.text
