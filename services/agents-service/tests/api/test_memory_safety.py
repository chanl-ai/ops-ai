"""Numbers a memory must never hold (c-563), by failure mode: a card number, IBAN or national id saved because the
model marked it harmless, and a number that only looks like one dropped. Each pattern is decided by its check digits
or its issuing rules, never by the model."""

from __future__ import annotations

from typing import Any

import pytest

from ops_agents.api.memory_safety import sensitive
from tests.api.test_action_roles import VIEWER
from tests.api.test_memory import Answering, chat, mine, said
from tests.api.test_team_default_agent import Stack, say, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("my card is 4111 1111 1111 1111", "card number"),
        ("card 5500-0000-0000-0004 please", "card number"),
        ("pay into GB82 WEST 1234 5698 7654 32", "IBAN"),
        ("DE89370400440532013000 is mine", "IBAN"),
        ("SSN 123-45-6789", "national id"),
        ("my NI number is AB 12 34 56 C", "national id"),
        ("SIN 046 454 286", "national id"),
    ],
)
def test_each_number_a_memory_must_never_hold_is_found(text: str, kind: str) -> None:
    assert sensitive(text) == kind


@pytest.mark.parametrize(
    "text",
    [
        "order 4111 1111 1111 1112",
        "GB82 WEST 1234 5698 7654 33",
        "ticket 000-12-3456",
        "ticket 666-12-3456",
        "AB 12 34 56 E",
        "reference 046 454 287",
        "my branch code is 1234 and the limit is 25000",
    ],
)
def test_a_number_that_only_looks_like_one_is_kept(text: str) -> None:
    assert sensitive(text) is None


async def test_a_card_number_is_never_saved_whatever_the_model_says(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    message = "My card is 4111 1111 1111 1111, and I prefer updates by email."
    extractor = Answering(
        said("Card 4111 1111 1111 1111", key="card", quote="My card is 4111 1111 1111 1111", sensitivity="none"),
        said("Updates by email", kind="preference", key="updates", quote="I prefer updates by email"),
    )
    rt.memory_extractor = extractor
    thread = await chat(c, VIEWER)
    await say(c, thread, message, VIEWER)
    await say(c, thread, "Remember that my card is 4111 1111 1111 1111.", VIEWER)
    kept: list[dict[str, Any]] = await mine(c, VIEWER)
    assert [m["value"] for m in kept] == ["Updates by email"], kept
