"""Home paths and the machine login become repo-relative, sibling or <login>; first names stay."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# A made-up login, set before the module reads it.
os.environ["OPS_SCRUB_LOGIN"] = "probelogin"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scrub_board_paths import LOGIN, LOGIN_TOKEN, apply_file, iter_files, leaks, rewrite

REPO = Path("/tmp/ws/ops-ai")
WORKSPACE = REPO.parent
HOME = Path("/tmp/home") / LOGIN


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"see {REPO}/docs/a.md", "see docs/a.md"),
        # A sibling checkout stays a valid relative link.
        (f"ln -s {WORKSPACE}/ops-ai-plugins plugins", "ln -s ../ops-ai-plugins plugins"),
        (f"{HOME}/.cursor/plans", "~/.cursor/plans"),
        # A first name stays; only the machine login is replaced.
        (f"Alice said use {REPO}/docs/a.md and not {LOGIN}", f"Alice said use docs/a.md and not {LOGIN_TOKEN}"),
        # A route folder called home is no home directory.
        ("apps/console/src/app/home/page.tsx", "apps/console/src/app/home/page.tsx"),
    ],
    ids=["repo", "sibling", "home", "first-name", "home-route"],
)
def test_a_path_or_login_is_rewritten_and_nothing_else(text: str, expected: str) -> None:
    out = rewrite(text, repo=REPO, workspace=WORKSPACE, home=HOME)
    assert out == expected
    assert leaks(out, home=HOME) == []


def test_rewritten_json_stays_valid() -> None:
    body = json.dumps({"p": f"{REPO}/a.json", "who": LOGIN})
    out = rewrite(body, repo=REPO, workspace=WORKSPACE, home=HOME)
    assert json.loads(out) == {"p": "a.json", "who": LOGIN_TOKEN}


def test_a_leftover_login_and_a_truncated_home_dump_fail_the_check() -> None:
    assert leaks(f"owned by {LOGIN}", home=HOME) == ["login"]
    text = f'File "/Users/{LOGIN[:3]}.../tmp/x"'
    assert "/Users/" not in rewrite(text, repo=REPO, workspace=WORKSPACE, home=HOME)
    assert leaks(text, home=HOME) == ["login home"]


def test_apply_clears_a_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text(f"{tmp_path}/x and {LOGIN}\n", encoding="utf-8")
    assert apply_file(path, write=True, root=tmp_path) == []
    assert path.read_text(encoding="utf-8") == f"x and {LOGIN_TOKEN}\n"


def test_binary_without_nul_bytes_is_skipped(tmp_path: Path) -> None:
    """A compressed PDF has no NUL byte but is not UTF-8; checking it as text crashed the pre-commit check."""
    (tmp_path / "form.pdf").write_bytes(b"%PDF-1.3\n%\x93\x8c\x8b\x9e stream")
    (tmp_path / "notes.md").write_text("plain", encoding="utf-8")
    assert [p.name for p in iter_files(tmp_path, ["form.pdf", "notes.md"])] == ["notes.md"]
