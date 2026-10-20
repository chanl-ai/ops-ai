"""The access checker's gaps (c-338), by failure mode: a refusal raised as a typed error goes unseen, a 409 that decides
access goes unseen, an allowlist line names a row the register does not hold (or one already resolved), a line is
added on a row the owner has not decided, and an exception line lands with no Standards-exception: trailer naming its
approver."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def checker() -> ModuleType:
    path = ROOT / "scripts/check_access_exceptions.py"
    spec = importlib.util.spec_from_file_location("check_access_exceptions", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_access_exceptions"] = mod
    spec.loader.exec_module(mod)
    return mod


MAPPER = """
class NotAllowedError(Exception): ...
class Locked(Conflict): ...

def _status(e):
    if isinstance(e, NotAllowedError | OtherError):
        return Forbidden(str(e), code="role_required")
"""
RAISES = """
def change(who):
    if not who.edits:
        raise NotAllowedError("no")
    if who.seeded:
        raise Locked("seeded")
    raise Conflict("taken", code="name_taken")
"""


def test_a_typed_refusal_and_a_typed_conflict_are_found_where_they_are_raised() -> None:
    c = checker()
    c.TYPED.clear()
    c.TYPED.update(c._typed([ast.parse(MAPPER)]))
    tree = ast.parse(RAISES)
    lines = RAISES.splitlines()
    refusals = c._refusals("services/x/src/x/routes.py", tree, lines)
    conflicts = c._conflicts("services/x/src/x/routes.py", tree, lines)
    assert [(f.kind, f.key) for f in refusals] == [("refusal", "role_required")]
    assert sorted(f.key for f in conflicts) == ["conflict", "name_taken"]


def _run(
    c: ModuleType,
    tmp: Path,
    allow: str,
    *,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    base: set[tuple[str, str, str]] | None = None,
) -> tuple[int, str]:
    (tmp / "allow.txt").write_text(allow)
    (tmp / "page.md").write_text(REGISTER)
    monkeypatch.setattr(c, "ALLOWLIST", tmp / "allow.txt")
    monkeypatch.setattr(c, "REGISTER_PAGE", tmp / "page.md")
    monkeypatch.setattr(c, "findings", lambda: [c.Finding("a.py", 3, "conflict", "seeded", "raise Conflict(...)")])
    monkeypatch.setattr(c, "committed", lambda: base)
    code = c.main([])
    return code, capsys.readouterr().out


REGISTER = (
    "## Exceptions register\n\n| Row | Exception | Status |\n|---|---|---|\n"
    "| E01 | x | decided |\n| E02 | y | **resolved** |\n| E03 | z | no decision |\n"
)


@pytest.mark.parametrize(
    ("allow", "says"),
    [
        ("", "new   a.py:3  conflict seeded"),
        ("a.py conflict seeded 1 E09\n", "E09 is not a row of the register"),
        ("a.py conflict seeded 1 E02\n", "E02 is resolved"),
        ("a.py conflict seeded 1 open\n", "`open` names only a policy's open default"),
        ("a.py conflict seeded 1 E01\n* conflict gone 0 state\n", "stale *  conflict gone"),
    ],
)
def test_a_conflict_fails_until_classified_against_a_live_register_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], allow: str, says: str
) -> None:
    code, out = _run(checker(), tmp_path, allow, monkeypatch=monkeypatch, capsys=capsys)
    assert code == 1 and says in out, out


def test_a_conflict_on_a_decided_row_or_classified_as_state_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    c = checker()
    assert _run(c, tmp_path, "a.py conflict seeded 1 E01\n", monkeypatch=monkeypatch, capsys=capsys)[0] == 0
    assert _run(c, tmp_path, "* conflict seeded 0 state\n", monkeypatch=monkeypatch, capsys=capsys)[0] == 0


def test_a_line_added_on_a_row_with_no_decision_fails_and_one_already_there_goes_to_the_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    c = checker()
    allow = "a.py conflict seeded 1 E03\n"
    code, out = _run(c, tmp_path, allow, monkeypatch=monkeypatch, capsys=capsys, base=set())
    assert code == 1 and "E03 has no decision" in out, out
    there = {("a.py", "conflict", "seeded")}
    code, out = _run(c, tmp_path, allow, monkeypatch=monkeypatch, capsys=capsys, base=there)
    assert code == 0 and "no decision, for the owner: E03" in out, out


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=env).stdout.strip()


def test_an_exception_line_added_without_the_trailer_fails_and_with_it_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = checker()
    allow = tmp_path / "access-exceptions-allowlist.txt"
    _git(tmp_path, "init", "-q")
    allow.write_text("a.py refusal x 1 E01\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "the list begins")
    began = _git(tmp_path, "rev-parse", "HEAD")
    allow.write_text("a.py refusal x 1 E01\n* conflict taken 0 state\n")
    _git(tmp_path, "commit", "-qam", "a state conflict needs no trailer")
    monkeypatch.setattr(c, "ROOT", tmp_path)
    monkeypatch.setattr(c, "ALLOWLIST", allow)
    monkeypatch.setattr(c, "LIST_BEGAN", began)
    page = tmp_path / "page.md"
    page.write_text(REGISTER)
    monkeypatch.setattr(c, "REGISTER_PAGE", page)
    assert c.commit_problems() == []
    allow.write_text(allow.read_text() + "b.py refusal y 1 E02\n")
    _git(tmp_path, "commit", "-qam", "an exception with no trailer")
    assert [p.split("`")[1] for p in c.commit_problems()] == ["b.py refusal y 1 E02"]
    _git(tmp_path, "commit", "-q", "--amend", "-m", "an exception\n\nStandards-exception: E02, approved by me")
    assert [p.split("`")[1] for p in c.commit_problems()] == ["b.py refusal y 1 E02"], "the trailer names no approver"
    _git(tmp_path, "commit", "-q", "--amend", "-m", "an exception\n\nStandards-exception: E02, approved by proto-orch")
    assert c.commit_problems() == []
    allow.write_text(allow.read_text() + "c.py refusal z 1 E03\n")
    _git(tmp_path, "commit", "-qam", "undecided\n\nStandards-exception: E03, approved by proto-orch")
    assert [p.split()[0] for p in c.commit_problems()] == ["row"], "a row with no decision fails even when approved"
