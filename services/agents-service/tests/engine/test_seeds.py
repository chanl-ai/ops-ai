"""The seeded workflows (c-535), by failure mode: a seed that no longer passes the engine's checks, which a dev stack
finds only when it fails to start, and the /wf-builder skill copies as an example; and the two-source example the
skill reuses missing its Join or its disagree way to a person."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ops_engine.definition import parse, validate
from ops_engine.node_types import default_registry

SEEDS = Path(__file__).parents[2] / "seed" / "engine_workflows.json"


def seeds() -> list[dict[str, Any]]:
    return json.loads(SEEDS.read_text())


def test_every_seeded_workflow_passes_the_engines_checks() -> None:
    failing = {}
    for item in seeds():
        d = parse({k: v for k, v in item.items() if k != "teamId"})
        if checks := [c for c in validate(d, default_registry()) if c.get("level", "error") == "error"]:
            failing[d.id] = checks
    assert failing == {}, failing


def test_the_two_source_example_joins_both_sources_and_sends_disagreements_to_a_person() -> None:
    [item] = [s for s in seeds() if s["id"] == "two_source_match"]
    types = {n["id"]: n["type"] for n in item["nodes"]}
    combine = next(n for n in item["nodes"] if n["type"] == "ops.data.combine")
    assert "ops.flow.join" in types.values() and combine["parameters"].get("onDisagreement") == "port", item["nodes"]
    leaving = [c["to"]["node"] for c in item["connections"] if c["from"] == {"node": combine["id"], "port": "disagree"}]
    assert leaving and types[leaving[0]] == "ops.flow.humanReview", (leaving, types)
