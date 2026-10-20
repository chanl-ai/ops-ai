"""The portable-store warning (c-067 T005, T006), by failure mode: a Postgres-only construct in new code not seen, a
docstring that mentions one warned about, a new unbounded key column or overlong name not seen, and code already on
the baseline warned about again."""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_portable_store as c  # pyright: ignore[reportMissingImports]

CODE = '''
"""Mentions RETURNING and ON CONFLICT in a docstring only."""
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

A = text("INSERT INTO t (id) VALUES (:id) ON CONFLICT DO NOTHING RETURNING id")
B = text("SELECT id FROM work FOR UPDATE SKIP LOCKED")
C = text("SELECT pg_try_advisory_xact_lock(:k)")
D = text("SELECT body->>'name' FROM docs WHERE body @> :q")
E = insert(t).values(id=1).on_conflict_do_update(index_elements=["id"], set_={"id": 1}).returning(t.c.id)
F = select(t).with_for_update(skip_locked=True)
G = select(sa.func.pg_try_advisory_xact_lock(1))
H = sa.Column("body", JSONB)
I = op.create_index("ix_once", "calls", ["key"], unique=True, postgresql_where=sa.text("effect"))
J = sa.Index("ix_open", t.c.due, postgresql_where=OPEN, mssql_where=OPEN)
K = sa.Index("ix_gin", t.c.tsv, postgresql_using="gin", mssql_where=OPEN)
L = select(t).where(t.c.at < sa.func.now() + sa.func.make_interval(0, 0, 0, 0, 0, 0, 5))
M = postgresql.insert(t).values(id=1)
N = select(t).with_for_update()
O = sa.insert(t).values(id=1).returning(t.c.id)
P = re.compile("(?:ssn|card)?|#")
'''


def test_each_postgres_only_construct_in_code_is_found() -> None:
    found = c.sql_findings(CODE)  # pyright: ignore[reportUnknownMemberType]
    by_line: dict[int, set[str]] = {}
    for line, construct in found:
        by_line.setdefault(line, set()).add(construct)
    assert by_line == {
        6: {"ON CONFLICT", "RETURNING"},
        7: {"SKIP LOCKED"},
        8: {"advisory lock"},
        9: {"JSONB operator"},
        # Core's returning() renders OUTPUT on SQL Server, so only on_conflict is found on line 10 (and nothing on 21).
        10: {"ON CONFLICT"},
        11: {"SKIP LOCKED", "row lock"},
        12: {"advisory lock"},
        13: {"JSONB type"},
        14: {"postgresql_where option"},
        # 15: a partial index with its SQL Server twin is portable (c-342); a twin for another option is not.
        16: {"postgresql_using option"},
        17: {"database clock"},
        18: {"dialect insert"},
        19: {"row lock"},
        4: {"dialect insert"},
    }, found


def test_unbounded_key_columns_and_long_names_are_found() -> None:
    md = sa.MetaData()
    t = sa.Table(
        "things",
        md,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("slug", sa.Text, unique=True),
        sa.Column("note", sa.Text),
        sa.Column("owner", sa.String(64), index=True),
        sa.Column("a_column_name_that_runs_well_past_what_some_databases_accept_x", sa.Integer),
    )
    found = {f for _, f in c.meta_findings([("m", t)])}  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    assert found == {
        "unbounded key column things.id",
        "unbounded key column things.slug",
        "column name over 60 characters things.a_column_name_that_runs_well_past_what_some_databases_accept_x",
    }, found


def test_only_findings_above_the_baseline_warn() -> None:
    key = "sql services/x/src/m.py RETURNING"
    where = {key: ["services/x/src/m.py:3", "services/x/src/m.py:9"]}
    assert c.warnings(Counter({key: 2}), Counter({key: 2}), where) == []  # pyright: ignore[reportUnknownMemberType]
    [warning] = c.warnings(Counter({key: 2}), Counter({key: 1}), where)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    assert "services/x/src/m.py:9" in warning and "RETURNING (2 > 1)" in warning and "ops_store" in warning


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=env).stdout.strip()


def test_a_baseline_row_raised_without_the_trailer_fails_and_with_it_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "portable-baseline.txt"
    _git(tmp_path, "init", "-q")
    base.write_text("# header\n2 sql a.py row lock\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "the baseline begins")
    monkeypatch.setattr(c, "ROOT", tmp_path)
    monkeypatch.setattr(c, "BASELINE", base)
    monkeypatch.setattr(c, "BASELINE_BEGAN", _git(tmp_path, "rev-parse", "HEAD"))
    base.write_text("# header\n1 sql a.py row lock\n")
    _git(tmp_path, "commit", "-qam", "a lock moved into ops_store: lowering needs no trailer")
    assert c.commit_problems() == []  # pyright: ignore[reportUnknownMemberType]
    base.write_text("# header\n1 sql a.py row lock\n1 sql b.py ON CONFLICT\n")
    _git(tmp_path, "commit", "-qam", "a new upsert outside ops_store")
    [problem] = c.commit_problems()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    assert "sql b.py ON CONFLICT (0 -> 1)" in problem
    _git(tmp_path, "commit", "-q", "--amend", "-m", "an upsert\n\nStandards-exception: b.py upsert, approved by orch")
    assert c.commit_problems() == []  # pyright: ignore[reportUnknownMemberType]
