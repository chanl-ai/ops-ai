"""The kb migrations that move rows, by failure mode: on SQL Server a security policy hides every tenant's rows from the
migrator, so a backfill run under it moves nothing; a piece with a long title and section fails the copy into units;
a base set to keyword search on purpose is moved to both lanes with the defaults; and the downgrade leaves moved bases
on both lanes."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
MSSQL_OFFLINE = "mssql+aioodbc://offline:offline@localhost:1/offline"
TENANT = "t_kb_backfill"


@contextlib.contextmanager
def _in_service() -> Generator[None]:
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        yield
    finally:
        os.chdir(cwd)


def _mssql(span: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("OPS_DATABASE_URL", MSSQL_OFFLINE)
    out = io.StringIO()
    with _in_service(), contextlib.redirect_stdout(out):
        command.upgrade(Config(str(ROOT / "alembic.ini")), span, sql=True)
    return out.getvalue()


@pytest.mark.parametrize(
    ("span", "table", "write"),
    [("kb_0015:kb_0016", "kb_chunks", "INSERT INTO kb_units"), ("kb_0020:kb_0021", "kb_bases", "UPDATE kb_bases")],
)
def test_a_sql_server_backfill_runs_with_the_table_s_policy_off(
    span: str, table: str, write: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sql = _mssql(span, monkeypatch)
    drop = sql.find(f"DROP SECURITY POLICY ops_security.{table}_isolation")
    moved = sql.find(write)
    back = sql.find(f"CREATE SECURITY POLICY ops_security.{table}_isolation")
    assert -1 < drop < moved < back, sql


async def _sql(url: str, *statements: str) -> list[Any]:
    engine = create_async_engine(url)
    rows: list[Any] = []
    async with engine.begin() as c:
        for text in statements:
            result = await c.execute(sa.text(text))
            if result.returns_rows:
                rows += list(result)
    await engine.dispose()
    return rows


def test_a_long_title_and_section_are_cut_to_the_unit_heading(database_url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, "kb_0015")
    try:
        asyncio.run(
            _sql(
                database_url,
                # The piece alone is what the copy reads; its item is not.
                "SET LOCAL session_replication_role = replica",
                "INSERT INTO kb_chunks (tenant_id, team_id, id, item_id, version, position, title, section, tokens, "
                f"text) VALUES ('{TENANT}', 'team_a', 'chk_long', 'itm_x', 1, 0, '{'T' * 400}', '{'S' * 400}', 3, "
                "'the text')",
            )
        )
        command.upgrade(cfg, "kb_0016")
        (heading,) = asyncio.run(_sql(database_url, f"SELECT heading FROM kb_units WHERE tenant_id = '{TENANT}'"))[0]
        assert heading == ("T" * 400 + " " + "S" * 400)[:800]
    finally:
        asyncio.run(_sql(database_url, f"DELETE FROM kb_chunks WHERE tenant_id = '{TENANT}'"))
        command.upgrade(cfg, "head")


OLD_BALANCED: dict[str, Any] = {
    "searchMode": "keyword",
    "hybridWeight": 0.6,
    "rerank": False,
    "reranker": "hosted",
    "chunkLimit": 8,
    "threshold": 0.5,
    "asOf": "",
    "rewrite": "off",
    "expandCount": 3,
    "rewriteInstructions": "",
    "scopeSourceIds": [],
    "answerShape": "answer_with_citations",
    "model": "bank-standard",
    "temperature": 0.1,
    "maxTokens": 800,
    "instructions": "Answer only from the provided context. If the context does not contain the answer, say so.",
    "citationStyle": "inline",
    "includeChunks": True,
    "noAnswerMessage": "I could not find that in the knowledge base.",
    "filters": {"match": "all", "conditions": []},
    "tagsInclude": [],
    "tagsExclude": [],
    "includeUntagged": True,
    "structuredTables": False,
}


def _base(kb_id: str, retrieval: dict[str, Any]) -> str:
    text = json.dumps(retrieval).replace("'", "''")
    return (
        "INSERT INTO kb_bases (tenant_id, id, team_id, name, slug, description, color, owner, collections, retrieval, "
        f"created_by, created_at) VALUES ('{TENANT}', '{kb_id}', 'team_a', '{kb_id}', '{kb_id}', '', 'gray', 'o@x', "
        f"CAST('[]' AS json), CAST('{text}' AS json), 'o@x', now())"
    )


def _modes(url: str) -> dict[str, str]:
    rows = asyncio.run(_sql(url, f"SELECT id, CAST(retrieval AS TEXT) FROM kb_bases WHERE tenant_id = '{TENANT}'"))
    return {kb_id: json.loads(text)["searchMode"] for kb_id, text in rows}


def test_only_bases_still_on_the_old_default_move_to_both_lanes_and_back(database_url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, "kb_0020")
    try:
        asyncio.run(
            _sql(
                database_url,
                _base("kb_default", OLD_BALANCED),
                _base("kb_chosen", {**OLD_BALANCED, "temperature": 0.3}),
            )
        )
        command.upgrade(cfg, "kb_0021")
        assert _modes(database_url) == {"kb_default": "hybrid", "kb_chosen": "keyword"}
        command.downgrade(cfg, "kb_0020")
        assert _modes(database_url) == {"kb_default": "keyword", "kb_chosen": "keyword"}
        (text,) = asyncio.run(
            _sql(database_url, "SELECT CAST(retrieval AS TEXT) FROM kb_bases WHERE id = 'kb_default'")
        )[0]
        assert text == json.dumps(OLD_BALANCED)
    finally:
        asyncio.run(_sql(database_url, f"DELETE FROM kb_bases WHERE tenant_id = '{TENANT}'"))
        command.upgrade(cfg, "head")
