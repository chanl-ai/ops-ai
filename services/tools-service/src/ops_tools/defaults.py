"""tools-service's team defaults (c-616 provisioning, the API's pattern): what every team gets from this service,
declared here, and the reconciler that makes it so. The defaults are the built-in apps' modules (modules/seed.py
BUILT_IN), each the team's own published copy, protected as the platform's.

The reconciler is idempotent: it creates what a team lacks and replaces a copy nobody changed when the declaration is
newer, and it leaves a copy a person changed, and a tool the team already holds in a module of its own, as they are.
DEFAULTS_VERSION rises with any change to the declarations; each start brings every team behind it up to date."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from ops_service_kit.logging import get_logger
from ops_store.team_scope import acting_as

from .modules.seed import BUILT_IN, built_in_module
from .store.modules import ModuleStore, StaleModuleError
from .store.team_defaults import TeamDefaults

log = get_logger("ops_tools.defaults")

DEFAULTS_VERSION = 1


async def ensure_defaults(
    store: ModuleStore,
    defaults: TeamDefaults,
    *,
    tenant_id: str,
    team_id: str,
    at: datetime,
    version: int = DEFAULTS_VERSION,
) -> bool:
    """Brings one team's defaults to `version`; False when the team already had it."""
    if await defaults.version(tenant_id, team_id) >= version:
        return False
    with acting_as(team_id):
        mine = [m for m in await store.all(tenant_id) if m["team_id"] == team_id]
    for app in BUILT_IN:
        wanted: list[str] = list(app["operations"])
        module_id = built_in_module(app, wanted, tenant_id=tenant_id, team_id=team_id, at=at)["id"]
        # A tool the team holds in a module of its own (one it made, or a seed's) stays where it is: two of the team's
        # modules holding one tool name would leave the gateway to pick between them.
        elsewhere = {str(o["name"]) for m in mine if m["id"] != module_id for o in m["operations"]}
        names = [n for n in wanted if n not in elsewhere]
        if not names:
            continue
        module = built_in_module(app, names, tenant_id=tenant_id, team_id=team_id, at=at)
        held = next((m for m in mine if m["id"] == module_id), None)
        try:
            if held is None:
                await store.insert_if_missing(module)
            elif held["revision"] == 0:
                await store.put({**module, "created_at": held["created_at"]}, expected_revision=0, seeded=True)
        except StaleModuleError:
            # Another start or event wrote this team's copy at the same moment; theirs stands.
            continue
        except Exception as e:
            # The same race on insert (the store's IntegrityError; only store packages import the driver).
            if type(e).__name__ != "IntegrityError":
                raise
            continue
    await defaults.record(tenant_id, team_id, version, at)
    return True


async def catch_up(
    store: ModuleStore, defaults: TeamDefaults, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> list[tuple[str, str]]:
    """Every team behind this release's defaults version, brought up to date at start; returns the teams written."""
    written: list[tuple[str, str]] = []
    for tenant_id, team_id in await defaults.behind(DEFAULTS_VERSION):
        if await ensure_defaults(store, defaults, tenant_id=tenant_id, team_id=team_id, at=clock()):
            written.append((tenant_id, team_id))
    if written:
        log.info("team_defaults_caught_up", teams=len(written), version=DEFAULTS_VERSION)
    return written


async def catch_up_at_start(store: ModuleStore, defaults: TeamDefaults) -> None:
    """The start-up job: `catch_up` once, with a failure logged rather than stopping the service."""
    try:
        await catch_up(store, defaults)
    except Exception as e:  # a database blip at start leaves teams behind until the next start or event, nothing worse
        log.warning("team_defaults_catch_up_failed", error=type(e).__name__)
