"""The template update rule, by failure mode: a field the team never touched does not take the template's change; a
field the team edited is replaced; a binding (the team's name, model or knowledge bases) is taken from the template; a
copy with no stored base silently takes the template; and a guardrail merge ends less strict than the team's."""

from __future__ import annotations

from ops_service_kit.template_merge import FieldOutcome, apply, merge

FIELDS = ("name", "useWhen", "instructions", "model", "collections")
BINDINGS = ("name", "model", "collections")


def outcomes(result: list[FieldOutcome]) -> dict[str, str]:
    return {o.field: o.outcome for o in result}


def test_a_field_the_team_never_touched_takes_the_template() -> None:
    base = {"useWhen": "A case is open", "instructions": "Read it."}
    yours = dict(base)
    template = {"useWhen": "A case is open or waiting", "instructions": "Read it."}
    result = merge(base, yours, template, FIELDS)
    assert outcomes(result) == {"useWhen": "taken"}
    assert apply(yours, result, {})["useWhen"] == "A case is open or waiting"


def test_a_field_only_the_team_changed_is_kept() -> None:
    base = {"useWhen": "A case is open", "instructions": "Read it."}
    yours = {"useWhen": "A case is open", "instructions": "Read it twice."}
    result = merge(base, yours, dict(base), FIELDS)
    assert outcomes(result) == {"instructions": "kept"}
    assert apply(yours, result, {})["instructions"] == "Read it twice."


def test_both_sides_changing_a_field_is_a_choice_that_keeps_yours_by_default() -> None:
    base = {"useWhen": "A case is open", "instructions": "Read it."}
    yours = {"useWhen": "A case is open", "instructions": "Read it twice."}
    template = {"useWhen": "Any case", "instructions": "Read it, then cite the policy."}
    result = merge(base, yours, template, FIELDS)
    assert outcomes(result) == {"useWhen": "taken", "instructions": "conflict"}
    kept = apply(yours, result, {})
    assert (kept["instructions"], kept["useWhen"]) == ("Read it twice.", "Any case")
    chosen = apply(yours, result, {"instructions": "template"})
    assert chosen["instructions"] == "Read it, then cite the policy."


def test_both_sides_making_the_same_change_lists_nothing() -> None:
    base = {"instructions": "Read it."}
    same = {"instructions": "Read it twice."}
    assert merge(base, same, dict(same), FIELDS) == []


def test_the_teams_bindings_never_take_the_template() -> None:
    base = {"model": "chat", "collections": ["kb_a"], "instructions": "Read it."}
    yours = {"model": "chat-large", "collections": ["kb_team"], "instructions": "Read it."}
    template = {"model": "chat-fast", "collections": ["kb_other"], "instructions": "Read it."}
    result = merge(base, yours, template, FIELDS, bindings=BINDINGS)
    assert result == []
    merged = apply(yours, result, {})
    assert (merged["model"], merged["collections"]) == ("chat-large", ["kb_team"])


def test_a_copy_with_no_base_lists_every_difference_as_a_choice_kept_as_yours() -> None:
    yours = {"useWhen": "A case is open", "instructions": "Read it twice."}
    template = {"useWhen": "Any case", "instructions": "Read it twice."}
    result = merge(None, yours, template, FIELDS)
    assert outcomes(result) == {"useWhen": "conflict"}
    assert apply(yours, result, {})["useWhen"] == "A case is open"


def test_a_guardrail_merge_keeps_the_teams_topic_and_the_smaller_limit() -> None:
    base = {"topics": ["refunds", "fees"], "maxActions": 10}
    yours = {"topics": ["refunds", "fees", "legal advice"], "maxActions": 5}
    template = {"topics": ["refunds"], "maxActions": 20}
    strict = {"topics": "union", "maxActions": "min"}
    result = merge(base, yours, template, ("topics", "maxActions"), strict=strict)
    assert outcomes(result) == {"topics": "kept", "maxActions": "kept"}
    merged = apply(yours, result, {})
    assert merged["maxActions"] == 5
    assert set(merged["topics"]) == {"refunds", "fees", "legal advice"}


def test_a_strict_list_takes_the_templates_new_entries_beside_the_teams() -> None:
    base = {"topics": ["refunds"]}
    yours = {"topics": ["refunds", "legal advice"]}
    template = {"topics": ["refunds", "medical advice"]}
    result = merge(base, yours, template, ("topics",), strict={"topics": "union"})
    assert outcomes(result) == {"topics": "taken"}
    assert apply(yours, result, {})["topics"] == ["refunds", "legal advice", "medical advice"]
