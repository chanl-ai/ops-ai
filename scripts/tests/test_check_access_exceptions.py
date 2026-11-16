"""The access checker's gaps, by failure mode: a refusal raised as a typed error or returned as a (403, code) tuple
goes unseen, a 409 that decides
access goes unseen, an allowlist line names a row the register does not hold (or one already resolved), a line is
added on a row the owner has not decided, and an exception line lands with no Standards-exception: trailer naming its
approver."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import subprocess
import sys
from collections.abc import Callable
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


def test_a_refusal_returned_as_a_status_and_code_tuple_is_found() -> None:
    """The tools gateway answers a call with `return 403, "CODE", message, details`, never a raised Forbidden."""
    c = checker()
    c.TYPED.clear()
    source = (
        'def refuse(m):\n    if m.off:\n        return 403, "APP_OFF", "off", {}\n    return 409, "STATE", "x", {}\n'
    )
    found = c._refusals("services/x/src/x/gateway.py", ast.parse(source), source.splitlines())
    assert [(f.kind, f.key, f.line) for f in found] == [("refusal", "APP_OFF", 3)]


def _committed(files: dict[str, str]) -> Callable[[str], str | None]:
    """Stands in for the lane files at HEAD: the text of each lane named, None for one not committed yet."""

    def at_head(lane: str) -> str | None:
        return files.get(lane)

    return at_head


def _lanes(c: ModuleType, tmp: Path, monkeypatch: pytest.MonkeyPatch, **rows: str) -> None:
    """An empty baseline file per lane in the temp tree, with `rows` as the text of the lanes named."""
    (tmp / "lanes").mkdir(exist_ok=True)
    for lane in c.LANES:
        (tmp / "lanes" / f"{lane}.txt").write_text(rows.get(lane, ""))
    monkeypatch.setattr(c, "BASELINES", tmp / "lanes")
    monkeypatch.setattr(c, "committed_baseline", _committed({}))


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
    _lanes(c, tmp, monkeypatch)
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
    kept = "a.py conflict seeded 1 E01  # keep agents: a seeded record\n"
    assert _run(c, tmp_path, kept, monkeypatch=monkeypatch, capsys=capsys)[0] == 0
    assert _run(c, tmp_path, "* conflict seeded 0 state\n", monkeypatch=monkeypatch, capsys=capsys)[0] == 0


def test_a_line_on_a_row_with_no_decision_fails_whether_added_or_already_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    c = checker()
    allow = "a.py conflict seeded 1 E03\n"
    code, out = _run(c, tmp_path, allow, monkeypatch=monkeypatch, capsys=capsys, base=set())
    assert code == 1 and "E03 has no decision" in out, out
    there = {("a.py", "conflict", "seeded")}
    code, out = _run(c, tmp_path, allow, monkeypatch=monkeypatch, capsys=capsys, base=there)
    assert code == 1 and "E03 has no decision" in out, out


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=env).stdout.strip()


def test_an_exception_line_added_without_the_trailer_fails_and_with_it_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = checker()
    allow = tmp_path / "access-exceptions-allowlist.txt"
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github/standards-maintainers.txt").write_text(
        f"# maintainers\n{hashlib.sha256(b'owner-login').hexdigest()}\n"
    )
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
    _git(tmp_path, "commit", "-q", "--amend", "-m", "an exception\n\nStandards-exception: approved by intruder: E02")
    assert [p.split("`")[1] for p in c.commit_problems()] == ["b.py refusal y 1 E02"], "the approver is not listed"
    _git(tmp_path, "commit", "-q", "--amend", "-m", "an exception\n\nStandards-exception: approved by owner-login: E02")
    assert c.commit_problems() == []
    allow.write_text(allow.read_text() + "c.py refusal z 1 E03\n")
    _git(tmp_path, "commit", "-qam", "undecided\n\nStandards-exception: approved by owner-login: E03")
    assert [p.split()[0] for p in c.commit_problems()] == ["row"], "a row with no decision fails even when approved"


def test_an_annotated_line_needs_the_trailer_and_annotating_a_line_already_there_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A line carries its outcome as a comment, so `E\\d+` no longer ends it; the comment must not hide a new line."""
    c = checker()
    allow = tmp_path / "access-exceptions-allowlist.txt"
    _git(tmp_path, "init", "-q")
    allow.write_text("a.py refusal x 1 E01\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "the list begins")
    monkeypatch.setattr(c, "ROOT", tmp_path)
    monkeypatch.setattr(c, "ALLOWLIST", allow)
    monkeypatch.setattr(c, "LIST_BEGAN", _git(tmp_path, "rev-parse", "HEAD"))
    monkeypatch.setattr(c, "BASELINES", tmp_path / "lanes")
    (tmp_path / "page.md").write_text(REGISTER)
    monkeypatch.setattr(c, "REGISTER_PAGE", tmp_path / "page.md")
    allow.write_text("a.py refusal x 1 E01  # keep agents: the asker rule\n")
    _git(tmp_path, "commit", "-qam", "an outcome on a line already there")
    assert c.commit_problems() == []
    allow.write_text(allow.read_text() + "b.py refusal y 1 E01  # keep agents: said so\n")
    _git(tmp_path, "commit", "-qam", "a new line behind a comment")
    assert [p.split("`")[1] for p in c.commit_problems()] == ["b.py refusal y 1 E01"]
    allow.write_text(allow.read_text().replace("a.py refusal x 1", "a.py refusal x 2"))
    _git(tmp_path, "commit", "-qam", "a raised count")
    assert [p.split("`")[1] for p in c.commit_problems()] == ["a.py refusal x 2 E01", "b.py refusal y 1 E01"]


def test_a_lane_baseline_may_only_fall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An owner compare has no allowlist line, so its lane's file is its only ceiling: raising it to fit new code
    fails against the committed file, and the same row already committed passes."""
    c = checker()
    site = "services/tools-service/src/ops_tools/a.py"
    row = f"{site} owner-compare owner 1\n"
    (tmp_path / "allow.txt").write_text("")
    (tmp_path / "page.md").write_text(REGISTER)
    monkeypatch.setattr(c, "ALLOWLIST", tmp_path / "allow.txt")
    monkeypatch.setattr(c, "REGISTER_PAGE", tmp_path / "page.md")
    monkeypatch.setattr(c, "committed", lambda: None)
    monkeypatch.setattr(c, "findings", lambda: [c.Finding(site, 3, "owner-compare", "owner", "x.owner == me.sub")])
    _lanes(c, tmp_path, monkeypatch, tools=row)
    monkeypatch.setattr(c, "committed_baseline", _committed(dict.fromkeys(c.LANES, "")))
    assert c.main([]) == 1
    assert "tools.txt owner-compare rose from 0 to 1" in capsys.readouterr().out
    monkeypatch.setattr(c, "committed_baseline", _committed({**dict.fromkeys(c.LANES, ""), "tools": row}))
    assert c.main([]) == 0, capsys.readouterr().out
    _lanes(c, tmp_path, monkeypatch)
    assert c.main([]) == 1
    assert f"new   {site}:3  owner-compare owner" in capsys.readouterr().out


def test_the_self_test_plants_each_shape_and_each_turns_the_checker_red() -> None:
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_access_exceptions.py"), "--self-test"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    for planted in ("flag", "role-set", "owner-compare", "policy-read", "role-name", "no decision", "outcome"):
        assert f"red   {planted}" in run.stdout, run.stdout


PLANTED = {
    "open-read": (
        "services/x-service/src/x/api/routers/things.py",
        'from fastapi import APIRouter\nrouter = APIRouter()\n\n@router.get("/things")\nasync def things(caller):\n'
        "    return await rows()\n",
    ),
    "grid-eval": (
        "services/x-service/src/x/store/roles.py",
        "from ops_access import effective\n\ndef is_admin(p):\n    return effective(p.access, p.grids)\n",
    ),
    "raw-role": (
        "services/x-service/src/x/api/hitl.py",
        "def decider(who, team, role):\n    return role in (who.access.get(team) or [who.roles.get(team)])\n",
    ),
}
CHECKED = (
    "services/x-service/src/x/api/routers/things.py",
    'from fastapi import APIRouter, Depends\nrouter = APIRouter()\n\n@router.get("/things")\n'
    'async def things(caller=Depends(reader_of("things"))):\n    return await rows()\n',
)


# Strict: the day the checker finds these kinds again this passes, and the mark must go.
@pytest.mark.xfail(
    strict=True,
    reason="The finder for these kinds was reverted with its allow list; it returns once every read is checked.",
)
def test_a_new_unchecked_read_grid_evaluation_or_raw_role_compare_is_found_where_it_lands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = checker()
    monkeypatch.setattr(c, "ROOT", tmp_path)
    found: dict[str, set[str]] = {}
    for kind, (rel, text) in PLANTED.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        found[kind] = {f.kind for f in c._python(path)}  # pyright: ignore[reportPrivateUsage]
    assert {k: kind in v for k, v in found.items() for kind in [k]} == dict.fromkeys(PLANTED, True), found
    # A read behind reader_of is no finding: the check is not simply flagging every route.
    (tmp_path / CHECKED[0]).write_text(CHECKED[1])
    assert "open-read" not in {f.kind for f in c._python(tmp_path / CHECKED[0])}  # pyright: ignore[reportPrivateUsage]
