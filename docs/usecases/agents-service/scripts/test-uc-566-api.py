"""uc-566 agents starts and a chat turn saves its checkpoint, api layer:
docs/usecases/agents-service/agents-starts-and-a-chat-turn-saves-its.md. agents-service on the scripted model sends
one chat message, and the turn's checkpoint is read back in the person's team and not in another team of the tenant.

    python test-uc-566-api.py                   PostgreSQL: the harness's database, created and migrated
    python test-uc-566-api.py <head bundle>     SQL Server: a database installed from the bundle (`make uc-sql-server`)

The SQL Server form runs where sqlcmd is (the test image) against OPS_MSSQL_SERVER with MSSQL_SA_PASSWORD.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, quote_plus
from uuid import uuid4

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from usecase_harness import AGENTS_PORT, DB, LOG_DIR, TEAM, agents, check, data, finish, pg_url, sse

from ops_checkpointer import RLS_ROLE
from ops_checkpointer.tables import ops_checkpoints
from ops_store import isolation

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "deploy" / "database"))

TENANT = "local"
# Each request of the database's sessions that waits, what it waits on and who blocks it, then every session holding a
# transaction open with the last statement it ran.
WAITS = """
SELECT 'waiting', r.session_id, r.blocking_session_id, r.wait_type, r.wait_time, r.wait_resource,
       LEFT(t.text, 400)
  FROM sys.dm_exec_requests r CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
 WHERE r.database_id = DB_ID(:db) AND r.session_id <> @@SPID
UNION ALL
SELECT 'open tx', s.session_id, NULL, s.status, s.open_transaction_count, NULL, LEFT(t.text, 400)
  FROM sys.dm_exec_sessions s JOIN sys.dm_exec_connections c ON c.session_id = s.session_id
 CROSS APPLY sys.dm_exec_sql_text(c.most_recent_sql_handle) t
 WHERE s.database_id = DB_ID(:db) AND s.open_transaction_count > 0
"""
OTHER_TEAM = "team_other"


@contextmanager
def no_knowledge_bases() -> Generator[str]:
    """A knowledge service that knows no knowledge base. agents refuses a chat when none answers, and kb-service does
    not run on SQL Server yet (c-550), nor on the runner, which has no PostgreSQL."""

    class Empty(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps({"success": True, "data": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Empty)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


async def checkpoints(url: str, team: str, thread_id: str, *, role: str | None) -> int:
    """The thread's checkpoints a reader in `team` sees, under the tables' security policy."""
    eng = create_async_engine(url)
    try:
        with isolation.scope(TENANT, team):
            async with isolation.isolated_tx(eng, role=role) as c:
                query = sa.select(sa.func.count()).where(ops_checkpoints.c.thread_id == thread_id)
                return int((await c.execute(query)).scalar_one())
    finally:
        await eng.dispose()


def agents_log(secret: str | None) -> str:
    """The end of agents-service's log, with the database password masked: the runner's output is kept in Fly's logs."""
    path = LOG_DIR / f"agents-{AGENTS_PORT}.log"
    tail = path.read_text(errors="replace")[-6000:] if path.exists() else "(no log)"
    for form in (secret, quote_plus(secret or ""), quote(secret or "")) if secret else ():
        tail = tail.replace(form, "***")
    return tail


def bounded(call: Callable[[], httpx.Response], seconds: float) -> httpx.Response | None:
    """`call()`, or None when it has not answered in `seconds`: a stream that keeps sending pings never times out."""
    done: list[httpx.Response] = []
    worker = threading.Thread(target=lambda: done.append(call()), daemon=True)
    worker.start()
    worker.join(seconds)
    return done[0] if done else None


def walk(
    url: str,
    env: dict[str, str],
    role: str | None,
    *,
    kb_url: str | None = None,
    secret: str | None = None,
    waits: Callable[[], str] | None = None,
) -> None:
    try:
        stack = agents(env=env, kb_url=kb_url)
        api = stack.__enter__()
    except SystemExit as e:
        check("1 agents starts on the database", False, str(e)[-2500:])
        return
    try:
        check("1 agents starts on the database", True)
        made = api.post("/chat/threads", json={"agentId": "ag_branch", "kbIds": []}, headers=TEAM)
        if not check("2 a chat starts", made.status_code == 201, made.text[:500]):
            print(agents_log(secret), flush=True)
            return
        thread_id = data(made)["id"]
        res = bounded(
            lambda: api.post(
                f"/chat/threads/{thread_id}/messages",
                json={"content": "What are your opening hours?"},
                headers={**TEAM, "Accept": "text/event-stream"},
            ),
            120,
        )
        if res is None:
            check("3 the reply streams back", False, "no answer in 120 s")
            print(waits() if waits else "", flush=True)
            print(agents_log(secret), flush=True)
            return
        events = sse(res.text) if res.status_code == 200 else []
        types = [e["type"] for e in events]
        if not check("3 the reply streams back", types[:1] == ["start"] and types[-1:] == ["done"], res.text[:800]):
            print(agents_log(secret), flush=True)
        team = TEAM["X-Team-Id"]
        mine = asyncio.run(checkpoints(url, team, thread_id, role=role))
        check("4 the turn's checkpoint is there in the person's team", mine > 0, mine)
        theirs = asyncio.run(checkpoints(url, OTHER_TEAM, thread_id, role=role))
        check("4 another team of the tenant reads none of it", theirs == 0, theirs)
        stored = api.get(f"/chat/threads/{thread_id}", headers=TEAM)
        roles = [m["role"] for m in data(stored)["messages"]] if stored.status_code == 200 else stored.text[:500]
        check("5 a reload shows the conversation", roles == ["user", "assistant"], roles)
    finally:
        stack.__exit__(None, None, None)


def main(head: Path | None) -> None:
    if head is None:
        walk(pg_url(DB), {}, RLS_ROLE)
        return
    from mssql_live import drop, engine, install, password, url  # noqa: PLC0415  # needs the test image's sqlcmd

    def waits() -> str:
        """Who waits on whom in the install's database, and the sessions holding a transaction open."""
        eng = engine("master")
        try:
            with eng.connect() as c:
                rows = c.execute(sa.text(WAITS), {"db": database}).all()
        finally:
            eng.dispose()
        return "\n".join("WAITS " + " | ".join(str(v) for v in r) for r in rows) or "WAITS none"

    database = f"ops_uc566_{uuid4().hex[:8]}"
    try:
        install(head, database)
        target = url(database, "mssql+aioodbc").render_as_string(hide_password=False)
        with no_knowledge_bases() as kb:
            env = {"OPS_DATABASE_URL": target, "OPS_USECASE_INSTALLED": "1"}
            walk(target, env, None, kb_url=kb, secret=password(), waits=waits)
    except SystemExit as e:
        check("1 agents starts on the database", False, str(e)[-2500:])
    finally:
        drop(database)


main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
finish()
