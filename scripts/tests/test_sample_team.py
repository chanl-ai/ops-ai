"""The sample team's installer (c-542): the manifest is checked before anything is made, a second team's ids never meet
the first team's, `--no-levy` leaves the levy story to staging's walk, and the first admin's password is made once."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dev_admin
import sample_team


def manifest() -> dict[str, Any]:
    return json.loads(sample_team.MANIFEST.read_text())


def test_the_manifest_has_exactly_the_sections_the_installer_runs() -> None:
    sample_team.check_manifest(manifest())


def test_an_unknown_section_is_refused_before_anything_is_made() -> None:
    with pytest.raises(SystemExit, match="unknown sections \\['chats'\\]"):
        sample_team.check_manifest(manifest() | {"chats": []})


def test_no_levy_leaves_out_every_workflow_the_levy_walk_makes() -> None:
    team = manifest()
    kept = {w["key"] for w in sample_team.team_workflows(team, no_levy=True)}
    assert kept == {"dispute"}, kept


def test_a_named_team_reads_its_own_document_type_and_starts_its_own_workflows() -> None:
    """Workflow and document type ids belong to the first team that makes them, so `--name` prefixes both, and each
    reply workflow names the copies under the same prefix."""
    team = manifest()
    sample_team.prefixed(team, sample_team.prefix_of("Northfield Ops"))
    kinds = {k["id"] for k in team["documentTypes"]}
    assert kinds == {"northfield_ops_garnishment_notice"}, kinds
    names = {"agent:levy": "ag_levy_northfield"} | sample_team.ids_by_key(team)
    copy = sample_team.definition_of(
        next(w for w in team["workflows"] if w["key"] == "levy_reply_document"), names, None
    )
    params = {n["id"]: n["parameters"] for n in copy["nodes"]}
    assert copy["id"] == "northfield_ops_levy_reply_document"
    assert params["read"]["documentType"]["id"] == "northfield_ops_garnishment_notice"
    assert params["each"]["workflow"] == "northfield_ops_levy_reply_debtor"
    intake = sample_team.definition_of(next(w for w in team["workflows"] if w["key"] == "levy_mail"), names, "a@b.test")
    starts = [n["parameters"]["workflow"] for n in intake["nodes"] if n["type"] == "ops.action.workflow"]
    assert starts == ["northfield_ops_levy_reply_document"], starts


def test_a_type_id_another_team_holds_fails_instead_of_counting_as_found() -> None:
    class Taken:
        """documents-service as another team's holder of the id leaves it: the create conflicts, the read is 404."""

        def post(self, *_: object, **__: object) -> httpx.Response:
            return httpx.Response(409, json={"success": False})

        def get(self, *_: object, **__: object) -> httpx.Response:
            return httpx.Response(404, json={"success": False})

    kinds = manifest()["documentTypes"]
    sample_team.FAILED.clear()
    sample_team.ensure_document_types(lambda _service: Taken(), kinds)  # pyright: ignore[reportArgumentType]
    assert [f"document type {kinds[0]['name']}"] == sample_team.FAILED


def test_the_first_admins_password_is_made_once_kept_private_and_never_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str] = []

    def bootstrap(_cmd: list[str], *, env: dict[str, str], check: bool) -> subprocess.CompletedProcess[str]:
        seen.append(env["OPS_BOOTSTRAP_ADMIN_PASSWORD"])
        return subprocess.CompletedProcess(_cmd, 0)

    monkeypatch.setattr(dev_admin, "ENV_FILE", tmp_path / "dev-admin.env")
    monkeypatch.setattr(dev_admin, "RUN_DIR", tmp_path)
    monkeypatch.setattr(dev_admin.subprocess, "run", bootstrap)
    assert dev_admin.main() == 0
    assert dev_admin.main() == 0
    assert len(seen) == 2 and seen[0] == seen[1] and len(seen[0]) >= 12
    assert stat.S_IMODE((tmp_path / "dev-admin.env").stat().st_mode) == 0o600
    assert seen[0] not in capsys.readouterr().out


def test_the_bank_secret_is_made_before_the_bank_module() -> None:
    text = (Path(sample_team.__file__)).read_text()
    assert text.index("ensure_fakes(admin, lead") < text.index("ensure_bank_module(builder, admin)")


def test_a_team_secret_is_posted_to_the_tools_api_for_that_team(monkeypatch: pytest.MonkeyPatch) -> None:
    """BANK_API_KEY is created the way a person does: POST /v1/secrets with teamId, by a Security admin."""
    posted: list[tuple[str, Any]] = []

    class Tools:
        def get(self, path: str, **_: object) -> httpx.Response:
            assert "teamId=team_demo" in path
            return httpx.Response(200, json={"success": True, "data": []})

        def post(self, path: str, **kwargs: object) -> httpx.Response:
            posted.append((path, kwargs["json"]))
            return httpx.Response(201, json={"success": True, "data": {"name": "BANK_API_KEY"}})

    class Platform:
        def get(self, path: str, **_: object) -> httpx.Response:
            assert path == "/v1/settings/workspace-teams"
            return httpx.Response(200, json={"success": True, "data": {"securityTeam": "team_security"}})

    class Admin:
        def __init__(self) -> None:
            self.urls = {"platform": "http://platform", "tools": "http://tools"}
            self.email, self.password = "admin@example.com", "x"

        def __call__(self, service: str) -> object:
            return {"platform": Platform(), "tools": Tools()}[service]

    def fake_sign_in(_urls: object, _email: str, _password: str, team: str | None = None) -> Admin:
        assert team == "team_security"
        return Admin()

    monkeypatch.setattr(sample_team, "sign_in", fake_sign_in)
    sample_team.FAILED.clear()
    sample_team.ensure_team_secret(Admin(), "team_demo", "BANK_API_KEY", "dev-bank-key")  # pyright: ignore[reportArgumentType]
    assert posted == [("/v1/secrets", {"name": "BANK_API_KEY", "value": "dev-bank-key", "teamId": "team_demo"})]
    assert sample_team.FAILED == []


def test_a_named_team_has_its_own_skill_names_and_mailbox_and_its_agents_pin_them() -> None:
    """A skill's slug and a mailbox address are unique in the workspace, so a second team that reused the first team's
    was refused at its skills (slug_taken) and its mailbox (address_taken)."""
    team = manifest()
    first = {s["name"] for s in team["skills"]}, team["mailbox"]["address"]
    sample_team.named(team, "Probe Team")
    skills = {s["name"] for s in team["skills"]}
    assert not skills & first[0] and team["mailbox"]["address"] == f"probe-team-{first[1]}"
    pinned = {n for a in team["agents"] for n in a["skills"]} | {n for a in team["agents"] for n in a["guardrails"]}
    assert pinned <= skills | {g["name"] for g in team["guardrails"]}
