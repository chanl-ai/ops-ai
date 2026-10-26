"""scripts/demo/seed_demo_team.py `--no-levy` (c-450): the levy story's workflows are made by
deploy/fly/staging/mailbox_demo.py levy under the team's own ids, so a seed that also made them gave the demo team two
"Levy notice: read the document" and two "Levy notice: one debtor" workflows."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import httpx

SEED = Path(__file__).resolve().parents[1] / "demo" / "seed_demo_team.py"


def seed() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_demo_team_c450", SEED)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_no_levy_leaves_out_every_workflow_the_levy_walk_makes() -> None:
    demo = seed()
    team = json.loads(demo.TEAM_FILE.read_text())
    kept = {w["key"] for w in demo.team_workflows(team, no_levy=True)}
    assert kept == {"dispute"}, kept
    levy = {w["key"] for w in team["workflows"] if demo.levy_story(w)}
    assert levy == {"levy_debtor", "levy_document", "levy_mail", "levy_reply_debtor", "levy_reply_document"}, levy


def test_with_the_levy_story_the_seed_makes_every_workflow() -> None:
    demo = seed()
    team = json.loads(demo.TEAM_FILE.read_text())
    assert demo.team_workflows(team, no_levy=False) == team["workflows"]


def test_a_prefixed_team_reads_its_own_document_type() -> None:
    """c-440: with --workflow-prefix the workflows took the prefix and the type they read kept the first team's id, so
    northfield_levy_document read another team's garnishment notice."""
    demo = seed()
    team = json.loads(demo.TEAM_FILE.read_text())
    demo.prefixed(team, "northfield_")
    kinds = {k["id"] for k in team["documentTypes"]}
    assert kinds == {"northfield_garnishment_notice"}, kinds
    named = {t for w in team["workflows"] for t in (w.get("documentTypes") or {}).values()}
    assert named and named <= kinds, named
    copy = demo.definition_of(next(w for w in team["workflows"] if w.get("documentTypes")), {}, None)
    read = [n["parameters"]["documentType"]["id"] for n in copy["nodes"] if "documentType" in n["parameters"]]
    assert read and set(read) <= kinds, read


def test_a_prefixed_teams_reply_workflows_name_its_own_type_and_person_workflow() -> None:
    """c-532: the reply workflow files name the document type and the per-person workflow by placeholder, so a second
    demo team's copy reads its own type and starts its own per-person workflow."""
    demo = seed()
    team = json.loads(demo.TEAM_FILE.read_text())
    demo.prefixed(team, "northfield_")
    names = {"agent:levy": "ag_levy_northfield"} | demo.ids_by_key(team)
    copy = demo.definition_of(next(w for w in team["workflows"] if w["key"] == "levy_reply_document"), names, None)
    params = {n["id"]: n["parameters"] for n in copy["nodes"]}
    assert copy["id"] == "northfield_levy_reply_document"
    assert params["read"]["documentType"]["id"] == "northfield_garnishment_notice"
    assert params["each"]["workflow"] == "northfield_levy_reply_debtor"


def test_a_type_id_another_team_holds_fails_the_seed_instead_of_counting_as_found() -> None:
    demo = seed()

    class Taken:
        """documents-service as another team's holder of the id leaves it: the create conflicts, the read is 404."""

        def post(self, *_: object, **__: object) -> httpx.Response:
            return httpx.Response(409, json={"success": False})

        def get(self, *_: object, **__: object) -> httpx.Response:
            return httpx.Response(404, json={"success": False})

    team = json.loads(demo.TEAM_FILE.read_text())
    demo.FAILED.clear()
    demo.ensure_document_types(lambda _service: Taken(), team["documentTypes"])
    failed = list(demo.FAILED)
    assert failed == [f"document type {team['documentTypes'][0]['name']}"]
