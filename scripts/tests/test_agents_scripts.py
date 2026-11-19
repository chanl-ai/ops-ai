"""The agent scripts' own red and green cases, by failure mode: a profile table read by the wrong column, a changed
file grouped into the wrong layer, a test that cannot fail reported as fine, a planted bug scored as caught when the
report never named it. Each script carries the cases as `--self-test`; this file runs them where `make python-verify`
and CI run, and keeps the profile reader's cases here. The mutation run's cases (`test_audit.py --self-test`) start a
pytest process per fault and run under `make agent-scripts-test`, not here."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "scripts" / "agents"
sys.path.insert(0, str(AGENTS))

from project_profile import parse  # noqa: E402

PROFILE = """# Profile

## Console

| Setting | Value |
|---|---|
| Console origin | `http://localhost:3016` |

| Role for walks | Email | Password |
|---|---|---|
| admin | `a@example.test` | `pw` |

## Layers

| Layer | Paths | Read | Check |
|---|---|---|---|
| service | `services/*/src/**` | `docs/architecture/api.md` | `make test PKG=services/<name>` |
"""


def test_a_value_is_read_from_the_key_value_table_not_the_roles_table() -> None:
    profile = parse(PROFILE, Path("p.md"), ROOT)
    assert profile.value("Console", "Console origin") == "http://localhost:3016"
    assert profile.table("Console", "Role for walks")[0]["Email"] == "`a@example.test`"


def test_an_unknown_section_or_row_is_an_error_not_an_empty_answer() -> None:
    profile = parse(PROFILE, Path("p.md"), ROOT)
    with pytest.raises(KeyError):
        profile.tables("Nowhere")
    with pytest.raises(KeyError):
        profile.value("Console", "Widths")


def test_a_bar_escaped_in_a_cell_stays_in_the_value() -> None:
    profile = parse("# P\n\n## T\n\n| A | B |\n|---|---|\n| x | `a\\|b` |\n", Path("p.md"), ROOT)
    assert profile.table("T")[0]["B"] == "`a|b`"


def test_the_real_profile_has_every_table_the_scripts_read() -> None:
    profile = parse(
        (ROOT / ".claude/project-profile.md").read_text(encoding="utf-8"), ROOT / ".claude/project-profile.md", ROOT
    )
    assert profile.table("Layers", "Paths")
    assert profile.table("Checks a review runs first", "Check")
    assert profile.table("Public surface", "Surface")
    assert profile.table("Tests", "Runner (from the code's folder)")
    assert profile.value("Tests", "URL template", "Test database")
    assert profile.table("Console", "Role for walks")
    assert profile.value("Console", "Widths") == "1440 and 390"


@pytest.mark.parametrize("script", ["review_context.py", "seed_canaries.py"])
def test_a_script_s_own_cases_pass(script: str) -> None:
    done = subprocess.run(
        [sys.executable, str(AGENTS / script), "--self-test"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0 and "FAIL" not in done.stdout, done.stdout + done.stderr


def test_the_walk_s_own_cases_pass() -> None:
    if not (ROOT / "node_modules").exists():
        pytest.skip("node_modules missing: run pnpm install")
    done = subprocess.run(
        ["node", str(AGENTS / "ui_walk.mjs"), "--self-test"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if "Executable doesn't exist" in done.stderr or "browserType.launch" in done.stderr:
        pytest.skip("no Chromium for Playwright here: run npx playwright install chromium")
    assert done.returncode == 0 and "FAIL" not in done.stdout, done.stdout + done.stderr
