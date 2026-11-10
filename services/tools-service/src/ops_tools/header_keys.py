"""Sign-in header keys move onto their module's connection.

A tool's Authorization, X-Api-Key or Cookie header is refused on save now that every custom module is on a connection,
but tools saved before still carry one. At each start this moves the clear case: the module's connection signs in with
nothing (auth kind none), every sign-in header on its tools is the same one, and its value is exactly `{{NAME}}` (the
connection becomes api_key, sending NAME's value in that header) or `Bearer {{NAME}}` on Authorization (bearer, NAME
as the token). The header then comes off the tools and their published copy. Anything else is logged and left as it
is; the tool page says that tool still sends a sign-in header. Idempotent: a moved module has no header left to find.

  OPS_DATABASE_URL=... uv run python -m ops_tools.header_keys --dry-run   # logs what it would change
"""

from __future__ import annotations

import argparse
import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from ops_service_kit.logging import configure_logging, get_logger
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.database import open_database

from .connections.records import module_auth
from .modules.service import CREDENTIAL_HEADER
from .store.connections import ConnectionStore
from .store.modules import ModuleStore

log = get_logger("ops_tools.header_keys")

REFERENCE = re.compile(r"^\{\{([A-Z][A-Z0-9_]*)\}\}$")
BEARER = re.compile(r"^Bearer \{\{([A-Z][A-Z0-9_]*)\}\}$")
MOVED_BY = "sign-in header move"


@dataclass(frozen=True)
class Move:
    header: str
    kind: str  # api_key or bearer
    secret: str  # the team secret's name; its value is never read here


def _headers(op: dict[str, Any]) -> list[dict[str, str]]:
    return cast(list[dict[str, str]], op.get("headers") or [])


def sign_in_headers(op: dict[str, Any]) -> list[dict[str, str]]:
    return [
        h
        for h in _headers(op)
        if CREDENTIAL_HEADER.match(str(h.get("key") or "").strip()) and str(h.get("value") or "").strip()
    ]


def plan(module: dict[str, Any], conn: dict[str, Any] | None) -> Move | str | None:
    """What moves for one module: a Move, the reason it is left alone, or None when its tools send no sign-in header."""
    pairs = {(h["key"].strip(), h["value"].strip()) for o in module["operations"] for h in sign_in_headers(o)}
    if not pairs:
        return None
    if conn is None or conn["auth_kind"] != "none":
        return "its connection already signs in another way"
    if [u for u in cast(list[dict[str, Any]], conn.get("used_by") or []) if u["id"] != module["id"]]:
        return "its connection is shared with another module"
    if len({(k.lower(), v) for k, v in pairs}) > 1:
        return "its tools send different sign-in headers"
    key, value = next(iter(pairs))
    if key.lower() == "cookie":
        return "a Cookie header is not a key a connection sends"
    if found := REFERENCE.match(value):
        return Move(key, "api_key", found.group(1))
    if key.lower() == "authorization" and (found := BEARER.match(value)):
        return Move("Authorization", "bearer", found.group(1))
    return "the header holds a typed value, not a {{NAME}} reference"


def _without_sign_in(ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**o, "headers": [h for h in _headers(o) if h not in sign_in_headers(o)]} for o in ops]


async def _apply(
    modules: ModuleStore, connections: ConnectionStore, module: dict[str, Any], conn: dict[str, Any], move: Move
) -> None:
    at = datetime.now(UTC)
    secrets = {"key": move.secret} if move.kind == "api_key" else {"token": move.secret}
    settings = dict(conn.get("settings") or {})
    if move.kind == "api_key":
        settings["name"] = move.header
    await connections.change(
        str(module["tenant_id"]), str(conn["id"]), int(conn["revision"]),
        {"auth_kind": move.kind, "settings": settings, "secrets": secrets}, actor=MOVED_BY, at=at,
        detail={"header": move.header},
    )  # fmt: skip
    moved = await connections.get(str(module["tenant_id"]), str(conn["id"])) or conn
    baseline = module.get("baseline")
    await modules.put(
        {
            **module,
            "auth": module_auth(moved),
            "operations": _without_sign_in(module["operations"]),
            "baseline": None if baseline is None else _without_sign_in(baseline),
        },
        expected_revision=module["revision"],
    )


async def move_header_keys(
    modules: ModuleStore, connections: ConnectionStore, *, dry_run: bool = False, tenant_id: str | None = None
) -> list[tuple[str, str]]:
    """Moves every clear case (every tenant's, or `tenant_id`'s), each in its module's team; returns the (tenant,
    module) pairs moved, or that would be."""
    moved: list[tuple[str, str]] = []
    holders = {
        (str(r["tenant_id"]), str(r["team_id"]), str(r["module_id"]))
        for r in await modules.header_holders(tenant_id)
        if any(CREDENTIAL_HEADER.match(str(h.get("key") or "").strip()) for h in r["headers"])
    }
    for tenant, team_id, module_id in sorted(holders):
        with isolation.scope(tenant, team_id):
            module = await modules.get(tenant, module_id)
            if module is None:
                continue
            conn = await connections.get(tenant, str(module["connection_id"])) if module["connection_id"] else None
            decided = plan(module, conn)
            if decided is None:
                continue
            if isinstance(decided, str):
                log.warning("sign_in_header_left", tenant=tenant, module=module_id, reason=decided)
                continue
            log.info(
                "sign_in_header_moved",
                tenant=tenant, module=module_id, name=module["display_name"], header=decided.header,
                before="auth none, key in each tool's header", after=f"{decided.kind} naming secret {decided.secret}",
                dry_run=dry_run,
            )  # fmt: skip
            if not dry_run and conn is not None:
                await _apply(modules, connections, module, conn, decided)
            moved.append((tenant, module_id))
    return moved


async def move_at_start(modules: ModuleStore, connections: ConnectionStore) -> None:
    """The start-up job: one pass, with a failure logged rather than stopping the service."""
    try:
        await move_header_keys(modules, connections)
    except Exception as e:  # a blip leaves the headers where they were, which still sign in, until the next start
        log.warning("sign_in_header_move_failed", error=type(e).__name__)


def main(clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="log what would change and write nothing")
    p.add_argument("--tenant", help="only this tenant's modules")
    args = p.parse_args()
    configure_logging(service="tools-service")

    async def run() -> None:
        engine = open_database(Settings().database_url)
        try:
            found = await move_header_keys(
                ModuleStore(engine), ConnectionStore(engine), dry_run=args.dry_run, tenant_id=args.tenant
            )
            log.info("sign_in_header_pass", modules=len(found), dry_run=args.dry_run, at=clock().isoformat())
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
