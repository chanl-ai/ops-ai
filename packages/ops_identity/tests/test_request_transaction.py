"""One transaction per request, through the real `Tx` dependency, auth dependency and timing middleware, on each
database, by failure mode: store calls of one request each paying their own transaction; a widened read leaving the
connection wide for the read after it; a caught database error ending the request's transaction; a stream holding
the request's transaction while it sends; two tasks sharing one connection; and a request that waits on the pool for
a second connection while it holds one."""

# No `from __future__ import annotations`: the test routes name local objects in Depends().

import asyncio
import io
import json
import logging
import os
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_identity import Auth, CurrentPrincipal, Identity, ServiceAuth, install_auth
from ops_identity.fastapi import Tx
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import Ed25519Signer, mint
from ops_service_kit.errors import Conflict
from ops_service_kit.http import install_error_handlers
from ops_service_kit.logging import configure_logging
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.backends import backends
from ops_store.conformance import engine_for, sql_server_database
from ops_store.database import open_database
from ops_store.dialect import dialect_of
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.store import Store

ISSUER = Ed25519Signer.generate("platform-1")
ROLE = "ops_request_tx_test"
OWNER = "the owning team a refusal is decided on"
POOL = 5
SQL_SERVER = (os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD"))

meta = sa.MetaData()
notes = sa.Table(
    "identity_test_request_tx_notes",
    meta,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("team_id", sa.String(64), nullable=True),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


class Notes(Store):
    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(engine)
        self.connections: list[AsyncConnection] = []

    async def add(self, note_id: str, team: str = "team_a") -> None:
        async with self.tx() as c:
            self.connections.append(c)
            await c.execute(notes.insert().values(id=note_id, tenant_id=isolation.tenant(), team_id=team))

    async def ids(self) -> list[str]:
        async with self.tx() as c:
            self.connections.append(c)
            q = sa.select(notes.c.id).where(notes.c.tenant_id == isolation.tenant()).order_by(notes.c.id)
            return [str(i) for i in (await c.execute(q)).scalars()]

    async def carried(self) -> dict[str, str]:
        """What the database itself says the transaction carries: the values its policies read, and who runs it."""
        async with self.tx() as c:
            return await carried(c)


class RoleNotes(Notes):
    role = ROLE


async def carried(c: AsyncConnection) -> dict[str, str]:
    if dialect_of(c) == "mssql":
        # SQL Server's session context keys are SETTINGS' keys, the names its security predicates read.
        cols = ", ".join(f"CAST(SESSION_CONTEXT(N'{key}') AS nvarchar(64))" for key in isolation.SETTINGS)
        row = (await c.execute(sa.text(f"SELECT {cols}, N'-'"))).one()
    else:
        cols = ", ".join(f"current_setting('{name}', true)" for name in isolation.SETTINGS.values())
        row = (await c.execute(sa.text(f"SELECT {cols}, current_user"))).one()
    return dict(zip(("tenant", "team", "scope", "user"), (str(v or "") for v in row), strict=True))


@pytest.fixture(params=["postgresql", "mssql"])
async def engine(request: pytest.FixtureRequest) -> AsyncIterator[AsyncEngine]:
    with sql_server_database("ops_request_tx", *SQL_SERVER) as mssql:
        if request.param == "mssql":
            if mssql is None:
                pytest.skip("set OPS_MSSQL_SERVER and MSSQL_SA_PASSWORD to run on SQL Server")
            url = mssql
        else:
            (backend,) = backends(Settings().database_url)
            await (await engine_for(backend)).dispose()  # creates the conformance database on first use
            url = backend.url
        # A short wait: a request that needs a second connection while the pool is held fails the test, not the run.
        e = open_database(url, pool_size=POOL, max_overflow=0, pool_timeout=5)
        async with e.begin() as c:
            await c.run_sync(meta.drop_all)
            await c.run_sync(meta.create_all)
            if request.param == "postgresql":
                await c.execute(
                    sa.text(
                        f"DO $$ BEGIN CREATE ROLE {ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
                    )
                )
                await c.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {notes.name} TO {ROLE}"))
        yield e
        async with e.begin() as c:
            await c.run_sync(meta.drop_all)
        await e.dispose()


@pytest.fixture
def out() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    root = logging.getLogger()
    level = root.level
    configure_logging(service="identity-test", stream=stream)
    yield stream
    root.setLevel(level)
    for h in [h for h in root.handlers if getattr(h, "stream", None) is stream]:
        root.removeHandler(h)


def request_lines(stream: io.StringIO, route: str) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in stream.getvalue().splitlines()]
    return [r for r in rows if r["event"] == "http.request" and r["http.route"] == route]


async def _jwks() -> dict[str, Any]:
    return {"keys": [ISSUER.public_jwk()]}


async def _no_keys(_key: str) -> dict[str, Any] | None:
    return None


def headers(tenant: str) -> dict[str, str]:
    """A person of `tenant` signed in to team_a, so every request starts in a team scope."""
    claims = {
        "sub": "usr_1",
        "email": "ana@bank.test",
        "name": "Ana",
        "tenant_id": tenant,
        "team_ids": ["team_a"],
        "roles": {"team_a": "builder"},
        "kind": "person",
        "auth_method": "session",
        "aud": ["agents"],
    }
    return {"Authorization": f"Bearer {mint(claims, ISSUER, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": "team_a"}


def build(engine: AsyncEngine) -> tuple[FastAPI, Notes]:
    st, as_role = Notes(engine), RoleNotes(engine)
    services = ServiceAuth(audience="agents", verifiers={}, scopes={})
    app = FastAPI()
    install_error_handlers(app)
    install_auth(app, Auth(Identity(audience="agents", jwks=_jwks, introspect=_no_keys, services=services), services))

    @app.post("/notes")
    async def add(p: CurrentPrincipal, _: Tx, fail: bool = False) -> list[str]:  # pyright: ignore[reportUnusedFunction]
        await st.add("n1")
        await st.add("n2")
        if fail:
            raise Conflict("refused after both writes")
        return await st.ids()

    @app.get("/widened")
    async def widened(p: CurrentPrincipal, _: Tx) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        with isolation.tenant_wide(OWNER, tenant_id=p.tenant_id):
            await st.add("theirs", team="team_b")
        seen: dict[str, Any] = {"as_role": await as_role.carried(), "no_role": await st.carried()}
        async with st.tx() as conn:
            with isolation.tenant_wide(OWNER):
                seen["wide"] = await st.carried()
            seen["owners"] = await st.owner_teams(conn, notes, {"theirs"}, OWNER)
            # The block that was open around the widened reads goes on with the scope it entered with.
            seen["after"] = await carried(conn)
        return seen

    @app.post("/claim")
    async def claim(p: CurrentPrincipal, _: Tx, savepoint: bool = True) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        await st.add("first")
        taken = False
        if savepoint:
            async with st.tx() as conn:
                try:
                    async with st.attempt(conn):
                        await conn.execute(notes.insert().values(id="first", tenant_id=p.tenant_id, team_id="team_a"))
                except IntegrityError:
                    taken = True
        else:
            try:
                await st.add("first")
            except IntegrityError:
                taken = True
        await st.add("second")
        return {"taken": taken, "ids": await st.ids()}

    @app.post("/stream")
    async def stream(p: CurrentPrincipal, _: Tx) -> StreamingResponse:  # pyright: ignore[reportUnusedFunction]
        await st.add("streamed")
        mine = st.connections[-1]

        async def frames() -> AsyncIterator[str]:
            closed_before_first_frame = mine.closed
            ids = await st.ids()
            yield json.dumps({"closed": closed_before_first_frame, "ids": ids, "own": st.connections[-1] is not mine})

        return StreamingResponse(frames(), media_type="application/json")

    @app.get("/fan")
    async def fan(p: CurrentPrincipal, _: Tx) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        async with st.tx() as mine:
            before = len(st.connections)
            both = await asyncio.gather(st.ids(), st.ids())
            child = await asyncio.create_task(st.ids())
            others = st.connections[before:]
            again = await st.ids()
        return {
            "results": [*both, child, again],
            "own_connections": len({id(c) for c in others}),
            "shared": [c is mine for c in others],
            "rejoined": st.connections[-1] is mine,
        }

    @app.get("/nested")
    async def nested(p: CurrentPrincipal, _: Tx) -> list[str]:  # pyright: ignore[reportUnusedFunction]
        async with st.tx():
            await asyncio.sleep(0.01)  # every request holds its connection while the others arrive
            return await st.ids()

    return app, st


def client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t")


async def test_store_calls_of_one_request_share_one_transaction_and_a_refusal_undoes_them(
    engine: AsyncEngine, out: io.StringIO
) -> None:
    app, st = build(engine)
    refused, saved = headers(f"ten_{uuid4().hex[:8]}"), headers(f"ten_{uuid4().hex[:8]}")
    async with client(app) as c:
        r = await c.post("/notes?fail=true", headers=refused)
        assert r.status_code == 409, r.text
        r = await c.post("/notes", headers=saved)
        assert (r.status_code, r.json()) == (200, ["n1", "n2"]), r.text
    assert len({id(conn) for conn in st.connections[-3:]}) == 1
    # The refused request's line is not counted: clearing SQL Server's session context after a rollback begins again.
    (_, committed) = request_lines(out, "/notes")
    assert committed["db.tx_count"] == 1, committed
    assert committed["db.pool.in_use"] == 1 and committed["db.pool.limit"] == POOL and committed["db.tx_open_ms"] > 0
    with isolation.tenant_wide("test", tenant_id="-"):
        async with isolation.isolated_tx(engine) as conn:
            tenants = set((await conn.execute(sa.select(notes.c.tenant_id))).scalars())
    assert len(tenants) == 1, "the refused request's two writes were rolled back and the other's committed"


async def test_a_widened_read_or_another_role_leaves_the_next_read_as_the_caller(
    engine: AsyncEngine, out: io.StringIO
) -> None:
    app, _ = build(engine)
    tenant = f"ten_{uuid4().hex[:8]}"
    async with client(app) as c:
        r = await c.get("/widened", headers=headers(tenant))
    assert r.status_code == 200, r.text
    seen = r.json()
    team = {"tenant": tenant, "team": "team_a", "scope": "team"}
    wide = {"tenant": tenant, "team": "", "scope": "tenant"}
    assert {k: seen["wide"][k] for k in wide} == wide
    assert seen["owners"] == {"theirs": "team_b"}
    for step in ("as_role", "no_role", "after"):
        assert {k: seen[step][k] for k in team} == team, step
    if dialect_of(engine) == "postgresql":
        login = seen["no_role"]["user"]
        assert seen["as_role"]["user"] == ROLE and login != ROLE and seen["after"]["user"] == login
    (line,) = request_lines(out, "/widened")
    assert line["db.tx_count"] == 1, line


async def test_a_caught_database_error_keeps_the_transaction_only_inside_a_savepoint(engine: AsyncEngine) -> None:
    app, _ = build(engine)
    kept, lost = headers(f"ten_{uuid4().hex[:8]}"), headers(f"ten_{uuid4().hex[:8]}")
    async with client(app) as c:
        r = await c.post("/claim", headers=kept)
        assert (r.status_code, r.json()) == (200, {"taken": True, "ids": ["first", "second"]}), r.text
        # Caught with no savepoint: the request fails whole on both databases, rather than answering 200 with its
        # writes rolled back (PostgreSQL) or half kept (SQL Server).
        r = await c.post("/claim?savepoint=false", headers=lost)
        assert r.status_code == 500, r.text
        r = await c.post("/notes", headers=lost)
        assert r.json() == ["n1", "n2"], "nothing of the failed request was committed"


async def test_a_stream_sends_its_first_frame_after_the_request_transaction_closed(
    engine: AsyncEngine, out: io.StringIO
) -> None:
    app, _ = build(engine)
    async with client(app) as c:
        r = await c.post("/stream", headers=headers(f"ten_{uuid4().hex[:8]}"))
    assert (r.status_code, r.json()) == (200, {"closed": True, "ids": ["streamed"], "own": True}), r.text
    (line,) = request_lines(out, "/stream")
    assert line["db.tx_count"] == 2, line


async def test_a_gather_branch_and_a_child_task_each_open_their_own_transaction(
    engine: AsyncEngine, out: io.StringIO
) -> None:
    app, _ = build(engine)
    async with client(app) as c:
        r = await c.get("/fan", headers=headers(f"ten_{uuid4().hex[:8]}"))
    assert r.status_code == 200, r.text
    assert r.json() == {"results": [[], [], [], []], "own_connections": 3, "shared": [False] * 3, "rejoined": True}
    (line,) = request_lines(out, "/fan")
    assert line["db.tx_count"] == 4, line


async def test_fifty_concurrent_requests_each_hold_one_connection_of_a_pool_of_five(
    engine: AsyncEngine, out: io.StringIO
) -> None:
    app, _ = build(engine)
    auth = headers(f"ten_{uuid4().hex[:8]}")
    async with client(app) as c:
        answers = await asyncio.gather(*(c.get("/nested", headers=auth) for _ in range(50)))
    assert [r.status_code for r in answers] == [200] * 50
    lines = request_lines(out, "/nested")
    assert len(lines) == 50 and {line["db.tx_count"] for line in lines} == {1}
    assert max(line["db.pool.in_use"] for line in lines) <= POOL
    waited = max(line["db.pool.wait_ms"] for line in lines)
    assert 0 < waited < 5000, f"the longest wait for a connection was {waited} ms"
