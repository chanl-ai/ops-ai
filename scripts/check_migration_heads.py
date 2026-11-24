"""Refuse a migration chain with more than one head.

Two migrations that follow the same revision (a second 0120 from two branches merged one after the other) both pass
their own pull request, and Alembic then refuses `upgrade head` at the deploy. This check reads each chain's
`revision` and `down_revision` and fails while any chain has two heads, naming both, so the pull request goes red
instead. A merge revision's tuple `down_revision` closes the heads it names. It also fails on a revision id longer
than 32 characters, the width of `alembic_version.version_num`: such a revision runs its changes, then fails writing
its own id.

  python3 scripts/check_migration_heads.py [<versions_dir> ...]

With no argument it reads every `services/*/migrations/versions` folder. Exit 1 when a chain has more than one head.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# alembic_version.version_num is VARCHAR(32) on both databases.
REVISION_WIDTH = 32


def _value(node: ast.expr) -> list[str] | None:
    """The revision ids a `revision` or `down_revision` value names: a string, None, or a tuple or list of strings."""
    if isinstance(node, ast.Constant) and (node.value is None or isinstance(node.value, str)):
        return [node.value] if node.value else []
    if isinstance(node, (ast.Tuple, ast.List)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return None


def read(path: Path) -> tuple[str, list[str]] | None:
    """(revision, down_revisions) of one migration file, or None for a file that is not a migration."""
    names: dict[str, list[str]] = {}
    for node in ast.parse(path.read_text(), filename=str(path)).body:
        target, value = None, None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            target, value = node.target.id, node.value
        if target in ("revision", "down_revision") and value is not None:
            ids = _value(value)
            if ids is not None:
                names[target] = ids
    revision = names.get("revision")
    if not revision or "down_revision" not in names:
        return None
    return revision[0], names["down_revision"]


def heads(versions: Path) -> list[str]:
    """The revisions in one chain that no other revision follows."""
    chain = [m for p in sorted(versions.glob("*.py")) if (m := read(p)) is not None]
    followed = {down for _, downs in chain for down in downs}
    return sorted(rev for rev, _ in chain if rev not in followed)


def chains(root: Path) -> list[Path]:
    return sorted(p for p in (root / "services").glob("*/migrations/versions") if p.is_dir())


def main(argv: list[str]) -> int:
    folders = [Path(a) for a in argv] or chains(ROOT)
    failed = False
    for versions in folders:
        found = heads(versions)
        shown = versions.relative_to(ROOT) if versions.is_relative_to(ROOT) else versions
        for rev, _ in (m for p in sorted(versions.glob("*.py")) if (m := read(p)) is not None):
            if len(rev) > REVISION_WIDTH:
                failed = True
                print(
                    f"check-migration-heads: {shown}: revision {rev} is {len(rev)} characters; at most {REVISION_WIDTH}"
                )
        if len(found) > 1:
            failed = True
            print(f"check-migration-heads: {shown}: {len(found)} heads: {', '.join(found)}")
            print("  point the later migration's down_revision at the other head, or add a merge revision")
        elif not found:
            failed = True
            print(f"check-migration-heads: {shown}: no head (an empty folder or a cycle in down_revision)")
        else:
            print(f"check-migration-heads: {shown}: one head ({found[0]})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
