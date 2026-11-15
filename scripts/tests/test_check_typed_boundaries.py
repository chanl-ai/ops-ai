"""The typed-boundary check, by failure mode: a new untyped site not seen; a print or a standard-library logger let
through by a baseline; a route body or reply that is not a model not tied to its service's file; and a baseline that
could be raised by rewriting it."""

from __future__ import annotations

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


def test_each_kind_is_found_and_text_that_only_mentions_one_is_not() -> None:
    assert sorted(c.findings(CODE, STORE)) == [
        ("dict-any", 6),
        ("extra-allow", 9),
        ("gather", 7),
        ("logging", 10),
        ("print", 11),
        ("store-dict", 6),
        ("task", 8),
    ]
    assert ("store-dict", 6) not in c.findings(CODE, "services/kb-service/src/ops_kb/app.py")


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
