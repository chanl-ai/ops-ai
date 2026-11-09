"""Home paths and the machine login become repo-relative, sibling or <login>; first names stay."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# A made-up login, set before the module reads it.
os.environ["OPS_SCRUB_LOGIN"] = "probelogin"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scrub_board_paths import LOGIN, LOGIN_TOKEN, apply_file, iter_files, leaks, rewrite

REPO = Path("/tmp/ws/ops-ai")
WORKSPACE = REPO.parent
HOME = Path("/tmp/home") / LOGIN


def test_repo_path_becomes_relative() -> None:
    assert rewrite(f"see {REPO}/docs/a.md", repo=REPO, workspace=WORKSPACE, home=HOME) == "see docs/a.md"


def test_sibling_path_stays_a_valid_relative_link() -> None:
    src = f"ln -s {WORKSPACE}/ops-ai-plugins plugins"
    assert rewrite(src, repo=REPO, workspace=WORKSPACE, home=HOME) == "ln -s ../ops-ai-plugins plugins"


def test_other_home_path_becomes_tilde() -> None:
    assert rewrite(f"{HOME}/.cursor/plans", repo=REPO, workspace=WORKSPACE, home=HOME) == "~/.cursor/plans"


def test_a_first_name_stays() -> None:
    text = f"Alice said use {REPO}/docs/a.md and not {LOGIN}"
    assert rewrite(text, repo=REPO, workspace=WORKSPACE, home=HOME) == f"Alice said use docs/a.md and not {LOGIN_TOKEN}"


def test_rewritten_json_stays_valid() -> None:
    body = json.dumps({"p": f"{REPO}/a.json", "who": LOGIN})
    out = rewrite(body, repo=REPO, workspace=WORKSPACE, home=HOME)
    assert json.loads(out) == {"p": "a.json", "who": LOGIN_TOKEN}


def test_home_page_path_is_not_a_leak() -> None:
    text = "apps/console/src/app/home/page.tsx"
    assert rewrite(text, repo=REPO, workspace=WORKSPACE, home=HOME) == text
    assert leaks(text, home=HOME) == []


def test_leftover_login_fails_the_check() -> None:
    assert leaks(f"owned by {LOGIN}", home=HOME) == ["login"]


def test_truncated_home_dump_is_rewritten() -> None:
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
