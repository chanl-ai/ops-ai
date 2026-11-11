"""Taking a template's update into a team's document type copy, through the real routes, by failure mode: an update
replaces a field the team edited, or skips one the team never touched; it changes a version a workflow already pinned;
a conflict takes the template's value without the person choosing it; a review that went stale is applied; a detached
copy is still updated, or its template is not offered again; and Add after the pin moved makes a second live copy.

tools-service is faked at the service client, as in test_templates_install.py."""

from __future__ import annotations

from typing import Any

from .conftest import Make
from .test_templates_install import LETTER, OPS, SOURCE, code, data, install, listed, wire

PATH = f"/v1/resources/{SOURCE}:case-letter/copies/{{}}"


def field(key: str, label: str, kind: str = "text") -> dict[str, Any]:
    """A field as the template ships it with a new label, or a new field."""
    shipped_now = {f["key"]: f for f in LETTER["body"]["fields"]}
    return shipped_now.get(key, {"key": key, "type": kind}) | {"label": label}


def shipped(version: int, fields: list[dict[str, Any]]) -> dict[str, Any]:
    return LETTER | {"version": version, "digest": f"{version}" * 64, "body": {**LETTER["body"], "fields": fields}}


async def newest(svc: Any, type_id: str) -> dict[str, Any]:
    versions = data(await svc.client.get(f"/v1/document-types/{type_id}", headers=OPS))["versions"]
    return max(versions, key=lambda v: v["version"])


def labels(version: dict[str, Any]) -> dict[str, str]:
    return {f["key"]: f["label"] for f in version["fields"]}


async def test_an_update_keeps_the_teams_fields_takes_the_rest_and_leaves_a_pinned_version_as_it_was(
    make: Make,
) -> None:
    svc = make()
    wire(svc, [LETTER])
    made = data(await install(svc), 201)["copy"]["recordId"]
    # The team relabels the letter date and adds a field of its own: version 2, which a workflow may pin.
    own = [field("case_number", "Case number"), field("letter_date", "Dated", "date"), field("ref", "Our reference")]
    mine = await svc.client.post(f"/v1/document-types/{made}/versions", json={"fields": own}, headers=OPS)
    assert mine.status_code == 201, mine.text
    # The template relabels the case number and adds a sender; it leaves the letter date alone.
    wire(svc, [shipped(2, [field("case_number", "Case no."), field("letter_date", "Letter date", "date"),
                           field("sender", "Sender")])])  # fmt: skip
    path = PATH.format(made) + "/update"
    review = data(await svc.client.get(path, headers=OPS))
    outcomes = {f["field"]: f["outcome"] for f in review["fields"]}
    assert outcomes == {
        "field:case_number": "taken",
        "field:letter_date": "kept",
        "field:ref": "kept",
        "field:sender": "taken",
    }, review["fields"]
    assert review["appliesNow"] is True and review["draftOpen"] is False
    taken = data(await svc.client.post(path, json={"expect": review["expect"]}, headers=OPS))
    assert taken["taken"] is True and taken["version"] == 3 and taken["copy"]["version"] == 2
    assert labels(await newest(svc, made)) == {
        "case_number": "Case no.",
        "letter_date": "Dated",
        "ref": "Our reference",
        "sender": "Sender",
    }
    # Version 2 is unchanged, so a workflow pinned to it still reads its fields.
    pinned = data(await svc.client.get(f"/v1/document-types/{made}/versions/2", headers=OPS))
    assert labels(pinned) == {"case_number": "Case number", "letter_date": "Dated", "ref": "Our reference"}
    # Nothing left to take: the copy reads added.
    [row] = await listed(svc)
    assert row["state"] == "added", row


async def test_a_conflict_keeps_the_teams_value_unless_chosen_and_a_stale_review_saves_nothing(make: Make) -> None:
    svc = make()
    wire(svc, [LETTER])
    made = data(await install(svc), 201)["copy"]["recordId"]
    own = [field("case_number", "Claim number"), field("letter_date", "Letter date", "date")]
    assert (
        await svc.client.post(f"/v1/document-types/{made}/versions", json={"fields": own}, headers=OPS)
    ).status_code == 201
    wire(svc, [shipped(2, [field("case_number", "Case no."), field("letter_date", "Letter date", "date")])])
    path = PATH.format(made) + "/update"
    review = data(await svc.client.get(path, headers=OPS))
    [conflict] = review["fields"]
    assert (conflict["field"], conflict["outcome"]) == ("field:case_number", "conflict")
    # The pin moved after the review: the take names the old digest and is refused, with no version made.
    wire(svc, [shipped(3, [field("case_number", "Case #"), field("letter_date", "Letter date", "date")])])
    stale = await svc.client.post(path, json={"expect": review["expect"]}, headers=OPS)
    assert code(stale, 409) == "update_stale"
    assert (await newest(svc, made))["version"] == 2
    # Taken with no choice: the team's label stays.
    again = data(await svc.client.get(path, headers=OPS))
    kept = data(await svc.client.post(path, json={"expect": again["expect"]}, headers=OPS))
    assert labels(await newest(svc, made))["case_number"] == "Claim number", kept
    # The next pin changes it again: still a conflict, the team's by default, never taken.
    wire(svc, [shipped(4, [field("case_number", "Case ref"), field("letter_date", "Letter date", "date")])])
    later = data(await svc.client.get(path, headers=OPS))
    assert [(f["field"], f["outcome"]) for f in later["fields"]] == [("field:case_number", "conflict")]
    chosen = {"choices": {"field:case_number": "template"}, "expect": later["expect"]}
    data(await svc.client.post(path, json=chosen, headers=OPS))
    assert labels(await newest(svc, made))["case_number"] == "Case ref"


async def test_a_detached_copy_takes_no_update_and_its_template_is_offered_again(make: Make) -> None:
    svc = make()
    wire(svc, [LETTER])
    made = data(await install(svc), 201)["copy"]["recordId"]
    detach = PATH.format(made) + "/detach"
    first = data(await svc.client.post(detach, headers=OPS))
    assert first["detachedAt"]
    assert data(await svc.client.post(detach, headers=OPS))["detachedAt"] == first["detachedAt"]
    wire(svc, [shipped(2, [field("case_number", "Case no."), field("letter_date", "Letter date", "date")])])
    assert code(await svc.client.get(PATH.format(made) + "/update", headers=OPS), 409) == "detached"
    [row] = await listed(svc)
    assert row["state"] == "available" and row["copy"] is None, row


async def test_add_after_the_pin_moves_answers_the_copy_the_team_holds(make: Make) -> None:
    svc = make()
    wire(svc, [LETTER])
    first = data(await install(svc), 201)["copy"]
    wire(svc, [shipped(2, LETTER["body"]["fields"])])
    again = await install(svc)
    assert again.status_code == 200, again.text
    assert again.json()["data"]["copy"]["id"] == first["id"]
    assert [t["name"] for t in data(await svc.client.get("/v1/document-types", headers=OPS))["items"]] == [
        "Case letter"
    ]
