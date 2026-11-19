"""test-impacted picks by failure mode: a one-file change runs the whole suite; a changed file's importer is missed; a
test beside a console file is missed; a build-file change is guessed at; a nothing-to-run pick reads as a failure; the
service Makefile ignores T, which is what made `make test PKG= T=` run everything."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from impacted_tests import commands, pick  # pyright: ignore[reportMissingImports]

ROOT = Path(__file__).resolve().parents[2]


def test_a_one_file_change_picks_its_importers_not_the_suite() -> None:
    py, node, _ = pick(["packages/ops_store/src/ops_store/audit.py"])
    assert py and len(py) < 10 and not node
    assert all("imports ops_store.audit" in why[0] for why in py.values())


def test_a_changed_script_picks_its_own_test() -> None:
    py, _, _ = pick(["scripts/dependants.py"])
    assert "scripts/tests/test_dependants.py" in py


def test_a_console_file_picks_the_test_beside_it() -> None:
    _, node, notes = pick(["apps/console/src/lib/egress.ts", "apps/console/src/lib/ui-only-file.tsx"])
    assert ("apps/console", "src/lib/egress.test.ts") in node
    assert any("ui-only-file.tsx: no test beside it" in n for n in notes)


def test_a_root_build_file_is_reported_and_not_guessed_at() -> None:
    py, node, notes = pick(["uv.lock"])
    assert not py and not node and "full check" in notes[0]


def test_docs_alone_pick_nothing() -> None:
    assert pick(["docs/guide/x.md", "services/kb-service/README.md"]) == ({}, [], [])


def test_python_picks_run_through_make_test_with_t_so_one_file_runs_one_file() -> None:
    cmds = commands({"services/kb-service/tests/test_a.py": ["x"]}, [])
    assert cmds[0][0] == ["make", "-s", "test", "PKG=services/kb-service", "T=tests/test_a.py"]


def test_every_service_test_target_passes_t_through_to_pytest() -> None:
    for makefile in sorted((ROOT / "services").glob("*/Makefile")):
        text = makefile.read_text()
        if "\ntest:" in text:
            recipe = text.split("\ntest:", 1)[1].split("\n\n", 1)[0]
            assert "$(T)" in recipe or "$(or $(T)" in recipe, makefile


def test_the_make_target_prints_the_pick_and_the_reason() -> None:
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "impacted_tests.py"), "--list", "--files", "scripts/dependants.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "pick scripts/tests/test_dependants.py" in out and "tests scripts/dependants.py" in out
