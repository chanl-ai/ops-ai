"""The /wf-builder skill's scripts (c-535), one test per failure mode: an examples page left stale after a seed
changed, which would have the skill copy a workflow that no longer exists; and a create on a profile that is not local
(named otherwise, or not on this machine) going ahead without the workflow id typed back."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wf_builder
import wf_builder_examples

SEED = [
    {
        "schemaVersion": 2,
        "id": "two_source_match",
        "name": "Match a notice to the bank's record",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {}},
        ],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }
]


def test_a_stale_examples_page_fails_the_check_and_a_regenerated_one_passes(tmp_path: Path) -> None:
    seeds = tmp_path / "engine_workflows.json"
    seeds.write_text(json.dumps(SEED))
    page = tmp_path / "examples.md"
    page.write_text("# Examples\n\nNothing yet.\n")
    assert wf_builder_examples.check(seeds, page), "a page that does not match the seeds is reported"
    page.write_text(wf_builder_examples.render(seeds))
    assert wf_builder_examples.check(seeds, page) == []
    assert "two_source_match" in page.read_text() and "start" in page.read_text()


def test_creating_on_a_profile_that_is_not_local_needs_the_id_typed_back() -> None:
    # Local only when it is named local and its base URL is on this machine; anything else asks.
    remote = {"name": "production", "baseUrl": "https://ops.bank.example", "team": "team_ops"}
    staging_here = {"name": "staging", "baseUrl": "http://127.0.0.1:8700", "team": "team_ops"}
    local = {"name": "local", "baseUrl": "http://127.0.0.1:8700", "team": "team_ops"}
    asked: list[str] = []

    def answer(text: str) -> str:
        def reply(prompt: str) -> str:
            asked.append(prompt)
            return text

        return reply  # type: ignore[return-value]

    assert wf_builder.may_create(remote, "two_source_match", ask=answer("yes")) is False, "yes is not the id"
    assert wf_builder.may_create(remote, "two_source_match", ask=answer("two_source_match")) is True
    assert wf_builder.may_create(staging_here, "two_source_match", ask=answer("yes")) is False, "named staging asks"
    asked.clear()
    assert wf_builder.may_create(local, "two_source_match", ask=answer("")) is True
    assert asked == [], "local asks nothing"
