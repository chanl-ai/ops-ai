"""One-click sign-in for the seeded demo people (c-504), by failure mode: the routes answering outside dev, where the
seeded people share one public password; the password reaching the browser; a click signing in someone who is not a
seeded demo person."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx

from ops_platform.api.app import create_public_app

from .conftest import DEMO_PASSWORD, Platform


async def client(platform: Platform, *, dev: bool, seed: Path) -> httpx.AsyncClient:
    app = create_public_app(
        platform.store,
        platform.signer,
        demo_password=DEMO_PASSWORD if dev else None,
        dev_people=seed if dev else None,
        audiences=["platform"],
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://platform")


async def seeded(platform: Platform, tmp_path: Path) -> tuple[str, Path]:
    # An email of its own per run: sign-in finds a person by email, and a database kept between runs holds earlier ones.
    p = await platform.person(roles=("builder",), email=f"j.richardson.{uuid4().hex[:8]}@harborpine.example")
    seed = tmp_path / "people.json"
    seed.write_text(
        json.dumps(
            {
                "teams": [{"id": "team_ops", "name": "Operations"}],
                "people": [{"name": "James Richardson", "email": p.email, "teams": {"team_ops": "builder"}}],
            }
        )
    )
    return p.email, seed


async def test_in_dev_the_seeded_people_are_listed_and_one_click_signs_in(platform: Platform, tmp_path: Path) -> None:
    email, seed = await seeded(platform, tmp_path)
    async with await client(platform, dev=True, seed=seed) as c:
        listed = await c.get("/v1/auth/dev-people")
        signed = await c.post("/v1/auth/dev-sign-in", json={"email": email})
    assert listed.status_code == 200
    assert listed.json()["data"] == [
        {"name": "James Richardson", "email": email, "teams": [{"team": "Operations", "role": "builder"}]}
    ]
    assert DEMO_PASSWORD not in listed.text
    assert signed.status_code == 200 and signed.json()["data"]["token"]


async def test_only_a_seeded_person_can_be_signed_in_with_one_click(platform: Platform, tmp_path: Path) -> None:
    _, seed = await seeded(platform, tmp_path)
    other = await platform.person(roles=("admin",))
    async with await client(platform, dev=True, seed=seed) as c:
        r = await c.post("/v1/auth/dev-sign-in", json={"email": other.email})
    assert r.status_code == 404


async def test_outside_dev_neither_route_exists(platform: Platform, tmp_path: Path) -> None:
    email, seed = await seeded(platform, tmp_path)
    async with await client(platform, dev=False, seed=seed) as c:
        listed = await c.get("/v1/auth/dev-people")
        signed = await c.post("/v1/auth/dev-sign-in", json={"email": email})
    assert (listed.status_code, signed.status_code) == (404, 404)
