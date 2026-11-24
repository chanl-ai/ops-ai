"""The workspace's list of agent instruction sections (`/v1/agent-instruction-sections`), by failure mode: a list that
drops or hides a fixed section is stored, or the never rules stop being the last thing the model reads once the list
is reordered; a section an admin adds is written at the end of the prompt instead of where the list places it, or
resetting the list leaves the prompt different from the one written before the list existed; a person without
`settings.manage` changes the list.

Everything is read as a caller reads it: the list from GET, a refusal from PUT or DELETE, and the order from the
prompt route of an agent saved after the change. What these tests ask beyond the design's words: the body and the
reply are `{sections: [...], customMax}`; a refused list answers 422 `validation_failed` with a message naming
`sections`; a section sent without an `id` is given one, read back here by its label; the cell is read in the team the
request acts in."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.engine.test_lifecycle_rights import (
    ADMIN,
    BUILDER,
    VIEWER,
    person,
    stack,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
)
from tests.saves import save_agent

Stack = tuple[AsyncClient, AsyncEngine]
ROUTE = "/v1/agent-instruction-sections"
# An admin whose role had the one cell taken off on the Roles page: the same role name, without settings.manage.
ADMIN_WITHOUT_THE_CELL = person("ada", "team_ops", "admin", unticked=(("settings", "manage"),))
NEVER = "Never promise a refund date."
BRIEF: dict[str, Any] = {
    "purpose": "Help customers dispute a card charge.",
    "howToAnswer": "Two short paragraphs at most.",
    "handOff": ["The person asks for a human."],
    "never": [NEVER],
}
COMPLIANCE: dict[str, Any] = {
    "label": "Compliance notes",
    "hint": "What the regulator asks the agent to say.",
    "kind": "menu",
    "required": False,
    "hidden": False,
    "drives": "none",
}


async def listed(c: AsyncClient, who: dict[str, str]) -> dict[str, Any]:
    res = await c.get(ROUTE, headers=who)
    assert res.status_code == 200, res.text
    return res.json()["data"]


def in_order(listing: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(listing["sections"], key=lambda s: s["order"])


def numbered(items: list[dict[str, Any]], listing: dict[str, Any]) -> dict[str, Any]:
    """The list as a save sends it: every item with its place, and the rest of the setting as it was read."""
    return {**listing, "sections": [{**item, "order": n} for n, item in enumerate(items)]}


def after(items: list[dict[str, Any]], section_id: str, added: dict[str, Any]) -> list[dict[str, Any]]:
    at = [s["id"] for s in items].index(section_id) + 1
    return [*items[:at], added, *items[at:]]


async def saved_agent(c: AsyncClient, name: str, sections: list[dict[str, str]]) -> tuple[str, Response]:
    """An agent a builder saves with this brief; returns its id and the save's response."""
    made = await c.post("/v1/agents", json={"name": name, "role": "Disputes"}, headers=BUILDER)
    assert made.status_code in (200, 201), made.text
    aid = made.json()["data"]["id"]
    return aid, await save_agent(c, aid, {"brief": {**BRIEF, "sections": sections}}, headers=BUILDER)


async def shown(c: AsyncClient, aid: str) -> str:
    res = await c.get(f"/v1/agents/{aid}/prompt", headers=BUILDER)
    assert res.status_code == 200, res.text
    return res.json()["data"]["text"]


def headings(prompt: str) -> list[str]:
    return [line for line in prompt.splitlines() if line.startswith("# ")]


async def test_a_list_without_a_fixed_section_is_refused_and_never_is_written_last_wherever_the_list_puts_it(
    stack: Stack,  # noqa: F811
) -> None:
    c, _ = stack
    default = await listed(c, ADMIN)
    items = in_order(default)
    fixed = {s["id"] for s in items if s["kind"] == "fixed"}
    assert fixed == {"purpose", "goal", "how_to_answer", "hand_off", "examples", "never"}, items
    refused = {
        "a fixed section removed": [s for s in items if s["id"] != "how_to_answer"],
        "a fixed section hidden": [{**s, "hidden": s["id"] == "how_to_answer"} for s in items],
        "the section that drives never-last removed": [s for s in items if s["id"] != "never"],
    }
    for why, kept in refused.items():
        res = await c.put(ROUTE, json=numbered(kept, default), headers=ADMIN)
        error = res.json().get("error", {})
        assert (res.status_code, error.get("code")) == (422, "validation_failed"), (why, res.text)
        assert "sections" in error.get("message", ""), (why, error)
    assert await listed(c, ADMIN) == default, "a refused list stores nothing"

    never_first = [next(s for s in items if s["id"] == "never"), *(s for s in items if s["id"] != "never")]
    moved = await c.put(ROUTE, json=numbered(never_first, default), headers=ADMIN)
    assert moved.status_code == 200, moved.text
    assert in_order(await listed(c, ADMIN))[0]["id"] == "never", "the fixed sections may be reordered"
    aid, saved = await saved_agent(c, "Never desk", [{"kind": "tone", "text": "Calm."}])
    assert saved.status_code == 200, saved.text
    prompt = await shown(c, aid)
    assert headings(prompt) == ["# Who you are", "# Tone", "# How to answer", "# Hand off when", "# Never"], prompt
    assert prompt.rstrip().endswith(f"- {NEVER}"), prompt


async def test_a_section_an_admin_adds_is_written_where_the_list_places_it_and_a_reset_writes_the_first_prompt_again(
    stack: Stack,  # noqa: F811
) -> None:
    c, _ = stack
    tone_and_place = [{"kind": "environment", "text": "The bank's chat."}, {"kind": "tone", "text": "Calm."}]
    first_id, first = await saved_agent(c, "First desk", tone_and_place)
    assert first.status_code == 200, first.text
    written_by_default = await shown(c, first_id)

    default = await listed(c, ADMIN)
    # Between Tone and Environment: a list that only appends would write it after both.
    put = await c.put(ROUTE, json=numbered(after(in_order(default), "tone", COMPLIANCE), default), headers=ADMIN)
    assert put.status_code == 200, put.text
    added = next(s for s in (await listed(c, BUILDER))["sections"] if s["label"] == "Compliance notes")
    assert added["kind"] == "menu" and added["id"], added

    with_it = [{"kind": added["id"], "text": "Say the call is recorded."}, *tone_and_place]
    aid, saved = await saved_agent(c, "Compliance desk", with_it)
    assert saved.status_code == 200, saved.text
    replied = saved.json()["data"]["brief"]["sections"][0]
    assert replied == {"kind": added["id"], "name": "Compliance notes", "text": "Say the call is recorded."}
    prompt = await shown(c, aid)
    assert headings(prompt) == [
        "# Who you are",
        "# Tone",
        "# Compliance notes",
        "# Environment",
        "# How to answer",
        "# Hand off when",
        "# Never",
    ], prompt
    assert "# Compliance notes\nSay the call is recorded.\n\n# Environment" in prompt, prompt

    reset = await c.delete(ROUTE, headers=ADMIN)
    assert reset.status_code == 200, reset.text
    assert await listed(c, ADMIN) == default
    again = await save_agent(c, first_id, {"brief": {**BRIEF, "sections": tone_and_place}}, headers=BUILDER)
    assert again.status_code == 200, again.text
    assert await shown(c, first_id) == written_by_default


async def test_the_list_is_changed_only_by_a_person_who_holds_settings_manage(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    default = await listed(c, VIEWER)
    hinted = [{**s, "hint": "Formal, no slang."} if s["id"] == "tone" else s for s in in_order(default)]
    body = numbered(hinted, default)
    for who in (BUILDER, VIEWER, ADMIN_WITHOUT_THE_CELL):
        assert (await c.put(ROUTE, json=body, headers=who)).status_code == 403
        assert (await c.delete(ROUTE, headers=who)).status_code == 403
    assert await listed(c, VIEWER) == default, "a refused change stores nothing"

    allowed = await c.put(ROUTE, json=body, headers=ADMIN)
    assert allowed.status_code == 200, allowed.text
    tone = next(s for s in (await listed(c, VIEWER))["sections"] if s["id"] == "tone")
    assert tone["hint"] == "Formal, no slang."
    assert (await c.delete(ROUTE, headers=ADMIN)).status_code == 200
    assert await listed(c, VIEWER) == default
