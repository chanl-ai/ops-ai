"""The tenant egress allow-list: a module names only listed hosts, a host in use stays listed, every change is
audited, and only private networks are listable as ranges. The migration moves each module's old host list onto
its tenant's list. At connect time the policy resolves once and dials only an address it checked."""

from __future__ import annotations

import ipaddress
import os
import subprocess
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpcore
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.settings import Settings
from ops_tools.egress import CURRENT_TENANT, EgressBackend, EgressDenied, EgressPolicy, address_allowed
from ops_tools.store.egress import EgressStore

from .conftest import Api

SERVICE = Path(__file__).parents[1]
OP = {
    "name": "get_statement",
    "description": "Monthly statement",
    "access": "read",
    "method": "GET",
    "url": "https://statements.example.com/v1/accounts/{accountId}/statement",
}


async def test_a_module_names_only_listed_hosts(api: Api) -> None:
    r = await api.call("POST", "/mod_document_service/operations", json=OP)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "egress_host_not_allowed"
    assert "statements.example.com" in r.json()["error"]["message"]
    added = await api.client.post("/v1/egress/hosts", json={"value": "Statements.Example.com", "note": "statements"})
    assert added.status_code == 201 and added.json()["data"]["value"] == "statements.example.com"
    r = await api.call("POST", "/mod_document_service/operations", json=OP)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["egressHosts"] == ["statements.example.com"]


async def test_a_host_in_use_stays_listed_and_every_change_is_audited(api: Api, engine: Any) -> None:
    await api.client.post("/v1/egress/hosts", json={"value": "statements.example.com"})
    await api.call("POST", "/mod_document_service/operations", json=OP)
    used = await api.client.post("/v1/egress/hosts/remove", json={"value": "statements.example.com"})
    assert used.status_code == 409 and used.json()["error"]["details"]["modules"] == ["mod_document_service"]
    await api.client.post("/v1/egress/hosts", json={"value": "spare.example.com"})
    gone = await api.client.post("/v1/egress/hosts/remove", json={"value": "spare.example.com"})
    assert gone.status_code == 200
    listed = (await api.client.get("/v1/egress")).json()["data"]["hosts"]
    assert "spare.example.com" not in [h["host"] for h in listed]
    trail = [(a["value"], a["action"]) for a in await EgressStore(engine).audit(api.tenant)]
    assert ("spare.example.com", "added") in trail and ("spare.example.com", "removed") in trail
    assert ("statements.example.com", "removed") not in trail, "a refused removal leaves no entry"


async def test_only_private_networks_are_listable_as_ranges(api: Api) -> None:
    ok = await api.client.post("/v1/egress/ranges", json={"value": "10.20.0.0/16", "note": "core banking"})
    assert ok.status_code == 201, ok.text
    for refused in ("169.254.0.0/16", "127.0.0.0/8", "8.8.8.0/24", "10.20.0.1/16", "corebank"):
        r = await api.client.post("/v1/egress/ranges", json={"value": refused})
        assert r.status_code == 400, refused
    r = await api.client.post("/v1/egress/hosts", json={"value": "10.20.0.5"})
    assert r.status_code == 400, "an address is listed as a range, never as a host"


def _alembic(url: str, *args: str) -> None:
    env = {**os.environ, "OPS_DATABASE_URL": url}
    subprocess.run(["uv", "run", "alembic", *args], cwd=SERVICE, env=env, check=True, capture_output=True)


async def test_the_migration_moves_module_hosts_onto_the_tenant_list() -> None:
    url = make_url(Settings().database_url)
    scratch = url.set(database=f"{url.database}_tools_egress")
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch.database}"'))
        await c.execute(sa.text(f'CREATE DATABASE "{scratch.database}"'))
    await admin.dispose()
    target = scratch.render_as_string(hide_password=False)
    _alembic(target, "upgrade", "tools_0003_executor")
    e = create_async_engine(target)
    async with e.begin() as c:
        await c.execute(
            sa.text(
                "INSERT INTO tool_modules (tenant_id, id, team_id, name, display_name, system, description, type, "
                "status, owner_team, owner_contacts, endpoint, auth, timeout_ms, egress_hosts, data_classification, "
                "reachable, drift, version, pending, revision, created_at, updated_at) VALUES ('t', 'mod_a', 'team', "
                "'a', 'A', 'A', '', 'http', 'draft', 'Platform', '[]', '', '{}', 8000, "
                "'[\"api.one.test\", \"api.two.test\"]', 'internal', true, false, '0.1.0', '[]', 1, now(), now())"
            )
        )
    await e.dispose()
    _alembic(target, "upgrade", "head")
    e = create_async_engine(target)
    async with e.connect() as c:
        listed = (await c.execute(sa.text("SELECT host FROM egress_hosts ORDER BY host"))).scalars().all()
        links = (
            (
                await c.execute(
                    sa.text("SELECT host FROM module_egress_hosts WHERE module_id = 'mod_a' ORDER BY position")
                )
            )
            .scalars()
            .all()
        )
        audited = (await c.execute(sa.text("SELECT count(*) FROM egress_audit"))).scalar_one()
    await e.dispose()
    assert list(listed) == ["api.one.test", "api.two.test"]
    assert list(links) == ["api.one.test", "api.two.test"]
    assert audited == 2
    _alembic(target, "downgrade", "tools_0003_executor")


# The egress policy at connect time. A scripted resolver stands in for DNS, and a recording backend stands in for the
# network: like the operating system, it resolves a name it is given, so connecting by name would resolve again.


class ScriptedResolver:
    """Answers each lookup of a name with the next scripted answer, the last one repeating."""

    def __init__(self, answers: dict[str, list[list[str]]]) -> None:
        self.answers = answers
        self.lookups: list[str] = []

    async def resolve(self, host: str, port: int) -> list[str]:
        self.lookups.append(host)
        script = self.answers[host]
        return script.pop(0) if len(script) > 1 else script[0]


class Dialled(Exception):
    def __init__(self, address: str) -> None:
        super().__init__(address)
        self.address = address


class RecordingNetwork(httpcore.AsyncNetworkBackend):
    def __init__(self, resolver: ScriptedResolver) -> None:
        self.resolver = resolver

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            ipaddress.ip_address(host)
            address = host
        except ValueError:
            address = (await self.resolver.resolve(host, port))[0]
        raise Dialled(address)

    async def sleep(self, seconds: float) -> None:
        return None


async def _dial(backend: EgressBackend, host: str) -> str:
    try:
        await backend.connect_tcp(host, 443)
    except Dialled as d:
        return d.address
    raise AssertionError("the backend neither dialled nor refused")


@pytest.fixture
async def listed(engine: Any, tenant: str) -> AsyncIterator[EgressStore]:
    store = EgressStore(engine)
    now = datetime.now(UTC)
    for host in ("api.bank.test", "core.bank.test"):
        await store.add(tenant, "host", host, actor="test", note="", at=now)
    await store.add(tenant, "range", "10.20.0.0/16", actor="test", note="", at=now)
    token = CURRENT_TENANT.set(tenant)
    yield store
    CURRENT_TENANT.reset(token)


def _backend(store: EgressStore, answers: dict[str, list[list[str]]]) -> tuple[EgressBackend, ScriptedResolver]:
    resolver = ScriptedResolver(answers)
    return EgressBackend(EgressPolicy(store, resolver), RecordingNetwork(resolver)), resolver


async def test_dns_cannot_rebind_between_the_check_and_the_connection(listed: EgressStore) -> None:
    backend, resolver = _backend(listed, {"api.bank.test": [["93.184.216.34"], ["10.0.0.5"]]})
    assert await _dial(backend, "api.bank.test") == "93.184.216.34"
    assert resolver.lookups == ["api.bank.test"], "resolved once; the connection went to the checked address"


async def test_an_allowed_host_resolving_to_an_unlisted_private_address_is_refused(listed: EgressStore) -> None:
    for address in (
        "10.0.0.5",
        "127.0.0.1",
        "169.254.169.254",
        "::ffff:169.254.169.254",
        "fd00:ec2::254",
        "100.64.0.9",
    ):
        backend, _ = _backend(listed, {"api.bank.test": [[address]]})
        with pytest.raises(EgressDenied):
            await _dial(backend, "api.bank.test")
    backend, _ = _backend(listed, {"api.bank.test": [["93.184.216.34", "10.0.0.5"]]})
    with pytest.raises(EgressDenied):
        await _dial(backend, "api.bank.test")


async def test_a_listed_host_inside_a_listed_range_connects(listed: EgressStore) -> None:
    backend, _ = _backend(listed, {"core.bank.test": [["10.20.4.7"]]})
    assert await _dial(backend, "core.bank.test") == "10.20.4.7"


async def test_an_unlisted_host_is_refused_before_it_is_resolved(listed: EgressStore) -> None:
    backend, resolver = _backend(listed, {"evil.example.com": [["93.184.216.34"]]})
    with pytest.raises(EgressDenied):
        await _dial(backend, "evil.example.com")
    assert resolver.lookups == []


async def test_only_https_to_a_listed_host_on_the_default_port_passes_the_url_check(
    listed: EgressStore, tenant: str
) -> None:
    policy = EgressPolicy(listed, ScriptedResolver({}))
    assert await policy.check_url(tenant, "https://api.bank.test/v1/x") == "api.bank.test"
    for url in ("http://api.bank.test/v1/x", "https://api.bank.test:8443/v1/x", "https://evil.example.com/x"):
        with pytest.raises(EgressDenied):
            await policy.check_url(tenant, url)


def test_loopback_link_local_and_metadata_stay_denied_even_when_a_range_covers_them() -> None:
    # The listing rules refuse such ranges; this holds if one reaches the table some other way.
    covering = ["127.0.0.0/8", "169.254.0.0/16", "fd00::/8"]
    for address in ("127.0.0.1", "169.254.169.254", "fd00:ec2::254", "::ffff:127.0.0.1"):
        assert not address_allowed(address, covering), address
    assert address_allowed("10.20.0.7", ["10.20.0.0/16"])
