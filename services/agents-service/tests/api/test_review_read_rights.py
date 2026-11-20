"""Reading Human Tasks without reviews.view, by failure mode: a chat user's GET /reviews and GET /reviews/{id}
answered the team's open tasks, customer and proposal included, because the routes asked only for a signed-in person;
and the check that closes them must still let a reviewer read the list."""

from __future__ import annotations

from tests.api.test_case_page import typed_case
from tests.api.test_reviews_list_reads import typed_waiting
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import person

CHAT_USER = person("lena", "team_ops", "chat_user")
REVIEWER = person("rosa", "team_ops", "approver")


async def test_a_chat_user_reads_no_task_and_a_reviewer_reads_the_list(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await typed_waiting(stack, await typed_case(stack, customer="C-lena"), 1)
    listed = await c.get("/reviews", headers=REVIEWER)
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]["data"]
    assert rows, listed.text
    review_id = str(rows[0]["id"])
    for path in ("/reviews", f"/reviews/{review_id}", f"/reviews/{review_id}/place"):
        got = await c.get(path, headers=CHAT_USER)
        assert (got.status_code, got.json()["error"]["code"]) == (403, "forbidden"), (path, got.text)
