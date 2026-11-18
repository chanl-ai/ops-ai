"""The typed-boundary check, by failure mode: a new untyped site not seen; a print or a standard-library logger let
through by a baseline; a route body or reply that is not a model not tied to its service's file; and a baseline that
could be raised by rewriting it."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_typed_boundaries as c  # pyright: ignore[reportMissingImports]

CODE = '''
"""Mentions dict[str, Any], asyncio.gather( and print( in a docstring only."""
import asyncio, logging
from typing import Any

async def read(conn) -> list[dict[str, Any]]:
    a, b = await asyncio.gather(one(), two())
    asyncio.create_task(later())
    config = ConfigDict(extra="allow")
    log = logging.getLogger(__name__)
    print("done")
    shaped: dict[str, int] = {}
'''
STORE = "services/kb-service/src/ops_kb/store/bases.py"


def repo(tmp_path: Path, source: str = CODE) -> Path:
    file = tmp_path / STORE
    file.parent.mkdir(parents=True)
    file.write_text(source)
    return tmp_path


def run(root: Path, monkeypatch: pytest.MonkeyPatch, *flags: str) -> int:
    monkeypatch.setattr(sys, "argv", ["check_typed_boundaries.py", *flags])
    return c.main(root)


def test_a_new_site_fails_and_one_on_the_baseline_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clean = CODE.replace('    log = logging.getLogger(__name__)\n    print("done")\n', "")
    root = repo(tmp_path, clean)
    assert run(root, monkeypatch, "--strict") == 1
    assert run(root, monkeypatch, "--update") == 0
    assert run(root, monkeypatch, "--strict") == 0
    (root / STORE).write_text(clean + "    more = asyncio.gather(three())\n")
    capsys.readouterr()
    assert run(root, monkeypatch, "--strict") == 1
    assert "bases.py: 2 gather (allowed 1)" in capsys.readouterr().err


def test_a_print_or_a_logger_fails_whatever_the_baseline_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path)
    baseline = root / "services/kb-service" / c.BASELINE_NAME
    baseline.write_text(f"1 print {STORE}\n1 logging {STORE}\n")
    run(root, monkeypatch, "--update")
    assert "print" not in baseline.read_text() and "logging" not in baseline.read_text()
    assert run(root, monkeypatch, "--strict") == 1
    err = capsys.readouterr().err
    assert "1 print (allowed 0)" in err and "1 logging (allowed 0)" in err


def test_a_route_finding_is_held_to_its_own_services_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path, "x = 1\n")
    found = Counter({("body", "services/kb-service#kb_create_base"): 1})
    monkeypatch.setattr(c, "routes", lambda _root: found)  # pyright: ignore[reportUnknownLambdaType]
    run(root, monkeypatch, "--update")
    assert "1 body kb_create_base" in (root / "services/kb-service" / c.BASELINE_NAME).read_text()
    assert run(root, monkeypatch, "--strict") == 0
    found[("reply", "services/kb-service#kb_create_base")] = 1
    capsys.readouterr()
    assert run(root, monkeypatch, "--strict") == 1
    assert "services/kb-service#kb_create_base: 1 reply (allowed 0)" in capsys.readouterr().err


def test_update_lowers_a_row_and_never_raises_or_adds_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repo(tmp_path)
    baseline = root / "services/kb-service" / c.BASELINE_NAME
    baseline.write_text(f"5 gather {STORE}\n")
    run(root, monkeypatch, "--update")
    assert baseline.read_text().splitlines()[1:] == [f"1 gather {STORE}"], "lowered to today, nothing added"
    (root / STORE).write_text(CODE + "    asyncio.gather(x())\n")
    run(root, monkeypatch, "--update")
    assert baseline.read_text().splitlines()[1:] == [f"1 gather {STORE}"], "never raised"


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=env).stdout.strip()


def test_a_baseline_row_raised_or_a_file_added_waits_for_a_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = tmp_path / "services/kb-service"
    kb.mkdir(parents=True)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github/standards-maintainers.txt").write_text(
        f"# maintainers\n{hashlib.sha256(b'owner-login').hexdigest()}\n"
    )
    (kb / c.BASELINE_NAME).write_text("# header\n2 gather services/kb-service/src/app.py\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "the baselines begin")
    monkeypatch.setattr(c, "BASELINES_BEGAN", _git(tmp_path, "rev-parse", "HEAD"))
    monkeypatch.setenv("OPS_STANDARDS_REVIEW", "required")
    (kb / c.BASELINE_NAME).write_text("# header\n1 gather services/kb-service/src/app.py\n")
    _git(tmp_path, "commit", "-qam", "a gather became a task group")
    assert c.commit_problems(tmp_path) == []
    (kb / c.BASELINE_NAME).write_text("# header\n3 gather services/kb-service/src/app.py\n")
    _git(tmp_path, "commit", "-qam", "a gather back in code")
    [raised] = c.commit_problems(tmp_path)
    assert "gather services/kb-service/src/app.py (1 -> 3)" in raised
    monkeypatch.setenv("OPS_STANDARDS_REVIEW", "approved")
    assert c.commit_problems(tmp_path) == []
    monkeypatch.setenv("OPS_STANDARDS_REVIEW", "required")
    # Deleting the file and regenerating it with `--update` is a new file holding every row: a rise.
    (kb / c.BASELINE_NAME).unlink()
    _git(tmp_path, "commit", "-qam", "drop the baseline")
    (kb / c.BASELINE_NAME).write_text("# header\n9 task services/kb-service/src/app.py\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "regenerate the baseline")
    assert any("task services/kb-service/src/app.py (0 -> 9)" in p for p in c.commit_problems(tmp_path))


def test_main_commits_flag_exits_1_on_a_raised_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(c, "commit_problems", lambda _root: ["abc raises x"])  # pyright: ignore[reportUnknownLambdaType]
    assert run(tmp_path, monkeypatch, "--commits") == 1
    assert "abc raises x" in capsys.readouterr().out


def test_a_service_with_routes_and_no_walk_script_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path, "x = 1\n")
    app = root / "services/runner-service/src/ops_runner/app.py"
    app.parent.mkdir(parents=True)
    app.write_text('@app.post("/v1/runs")\nasync def run(): ...\n')
    monkeypatch.setattr(c, "routes", lambda _root: Counter())  # pyright: ignore[reportUnknownLambdaType]
    assert run(root, monkeypatch, "--strict") == 1
    assert "services/runner-service: has routes and no scripts/check_openapi.py" in capsys.readouterr().err
    script = root / "services/runner-service/scripts/check_openapi.py"
    script.parent.mkdir()
    script.write_text("")
    assert run(root, monkeypatch, "--strict") == 0


FORMS = """
import asyncio as aio
import logging as lg
from asyncio import create_task, gather as fan
from logging import getLogger


async def go(loop):
    await fan(one(), two())
    create_task(later())
    aio.ensure_future(later())
    asyncio.get_running_loop().create_task(later())
    loop.create_task(later())
    async with aio.TaskGroup() as tg:
        tg.create_task(child())
    log = getLogger(__name__)
    other = lg.getLogger(__name__)


class M(BaseModel):
    model_config = {"extra": "allow"}
    fine = {"extra": "forbid"}
"""


MAPPINGS = (
    "from typing import Any, Mapping\n"
    "from collections.abc import Mapping as M\n"
    "a: dict[str, object]\n"
    "b: Mapping[str, Any]\n"
    "c: M[str, object]\n"
    "d: dict[str, int]\n"
    "e: Mapping[str, str]\n"
)
APP = "services/kb-service/src/ops_kb/app.py"
KINDS = [("dict-any", 6), ("extra-allow", 9), ("gather", 7), ("logging", 10), ("print", 11), ("task", 8)]


@pytest.mark.parametrize(
    ("source", "path", "found"),
    [
        # Each kind once; a docstring that only mentions one is not a finding. A store file also answers for its rows.
        (CODE, STORE, sorted([*KINDS, ("store-dict", 6)])),
        (CODE, APP, KINDS),
        # A call through an alias or a loop and a plain-dict config are found; a task group's child is not.
        (
            FORMS,
            APP,
            [
                ("extra-allow", 21),
                ("gather", 9),
                ("logging", 16),
                ("logging", 17),
                ("task", 10),
                ("task", 11),
                ("task", 12),
                ("task", 13),
            ],
        ),
        # An object- or mapping-valued dict is a dict-any; a typed one is not.
        (MAPPINGS, "x/app.py", [("dict-any", 3), ("dict-any", 4), ("dict-any", 5)]),
    ],
    ids=["store", "app", "forms", "mappings"],
)
def test_each_kind_is_found_in_every_form_and_look_alikes_are_not(
    source: str, path: str, found: list[tuple[str, int]]
) -> None:
    assert sorted(c.findings(source, path)) == found
