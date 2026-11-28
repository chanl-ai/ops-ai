"""Who a save or publish is recorded under: an API key has no email, and two keys must not look like one author."""

from __future__ import annotations

from ops_agents.api.auth import Principal


def test_two_api_keys_without_an_email_are_two_authors_and_a_person_stays_their_email() -> None:
    key_a = Principal(name="Key A", email="", team_id="t", tenant_id="x", sub="key-a", is_key=True)
    key_b = Principal(name="Key B", email="", team_id="t", tenant_id="x", sub="key-b", is_key=True)
    person = Principal(name="James", email="j@x", team_id="t", tenant_id="x", sub="u1")
    assert key_a.actor != key_b.actor and key_a.actor
    assert person.actor == "j@x"
