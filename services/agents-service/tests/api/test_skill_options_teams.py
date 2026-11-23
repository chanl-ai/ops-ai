"""New skill's Owner team select on a team that owns no skill yet: the options name the teams the caller may create
skills in, not the teams that already own one, so a first skill can be made."""

from __future__ import annotations

from httpx import AsyncClient

from tests.api.test_widget_embed import BUILDER, OUTSIDER, VIEWER
from tests.api.test_widget_route_pins import client  # pyright: ignore[reportPrivateUsage]

__all__ = ["client"]


async def test_options_offer_the_builders_team_before_any_skill_exists(client: AsyncClient) -> None:
    built = await client.get("/v1/skills/options", headers=BUILDER)
    other = await client.get("/v1/skills/options", headers=OUTSIDER)
    assert built.json()["data"]["teams"] == ["team_ops"], built.text
    assert other.json()["data"]["teams"] == ["team_fraud"], other.text


async def test_options_offer_no_team_to_a_caller_who_may_not_create(client: AsyncClient) -> None:
    viewer = await client.get("/v1/skills/options", headers=VIEWER)
    assert viewer.status_code == 200, viewer.text
    assert viewer.json()["data"]["teams"] == []
