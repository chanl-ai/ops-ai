"""Rewrite home paths and the machine login in board, docs, examples and scripts text.

uv run python scripts/scrub_board_paths.py              exit 1 when a leak remains
uv run python scripts/scrub_board_paths.py --apply      rewrite those files in place
uv run python scripts/scrub_board_paths.py --check a b  check only the named paths
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
HOME = Path.home()
# The login to scrub besides this machine's home path; set where it differs from the home folder's name.
LOGIN = os.environ.get("OPS_SCRUB_LOGIN", "")
LOGIN_TOKEN = "<" + "login" + ">"
SCOPES = ("docs", "examples", "scripts")
SKIP_PARTS = frozenset({"state"})
# A pattern that never matches stands in when no login is set.
NEVER = r"(?!x)x"
_LOGIN_HOME = rf"(?:/Users|/home)/{re.escape(LOGIN)}(?=/|$)|/Users/{re.escape(LOGIN[:3])}[A-Za-z0-9._-]*\.\.\."
HOME_RE = re.compile(_LOGIN_HOME if LOGIN else NEVER)
LOGIN_RE = re.compile(rf"\b{re.escape(LOGIN)}\b" if LOGIN else NEVER)


def _swap_prefix(text: str, old: Path, new: str) -> str:
    old_s = re.escape(str(old))
    text = re.sub(old_s + r"/", new, text)
    bare = new.rstrip("/") or "."
    return re.sub(old_s + r"(?=/|$)", bare, text)


def rewrite(text: str, *, repo: Path = ROOT, workspace: Path = WORKSPACE, home: Path = HOME) -> str:
    text = _swap_prefix(text, repo, "")
    text = _swap_prefix(text, workspace, "../")
    text = _swap_prefix(text, home, "~/")
    text = HOME_RE.sub("~", text)
    return LOGIN_RE.sub(LOGIN_TOKEN, text)


def leaks(text: str, *, home: Path = HOME) -> list[str]:
    found: list[str] = []
    home_s = str(home)
    if home_s and home_s in text:
        found.append("home path")
    if HOME_RE.search(text):
        found.append("login home")
    if LOGIN_RE.search(text):
        found.append("login")
    return found


def _is_text(path: Path) -> bool:
    """UTF-8 with no NUL byte. A compressed PDF can have no NUL byte, so that alone does not make a file text."""
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def iter_files(root: Path, named: list[str]) -> list[Path]:
    if named:
        return [root / n for n in named if (root / n).is_file() and _is_text(root / n)]
    out: list[Path] = []
    for scope in SCOPES:
        base = root / scope
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or not _is_text(path):
                continue
            rel = path.relative_to(base)
            if rel.parts and rel.parts[0] in SKIP_PARTS:
                continue
            out.append(path)
    return out


def apply_file(path: Path, *, write: bool, root: Path = ROOT) -> list[str]:
    original = path.read_text(encoding="utf-8")
    rel = path.relative_to(root) if path.is_relative_to(root) else path
    if not write:
        return [f"{rel}: {name}" for name in leaks(original)]
    updated = rewrite(original, repo=root, workspace=root.parent)
    if updated != original:
        if path.suffix == ".json":
            json.loads(updated)
        path.write_text(updated, encoding="utf-8")
    return [f"{rel}: {name}" for name in leaks(updated)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("files", nargs="*")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    hits: list[str] = []
    for path in iter_files(root, args.files):
        hits.extend(apply_file(path, write=args.apply, root=root))
    if hits:
        print(f"scrub_board_paths: {len(hits)} leak(s); run with --apply:\n" + "\n".join(f"  {h}" for h in hits))
        return 1
    print(f"scrub_board_paths: {len(list(iter_files(root, args.files)))} files clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
