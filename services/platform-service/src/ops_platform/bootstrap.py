"""`python -m ops_platform.bootstrap`: the first tenant, its Security team and one admin with a password, on an install
where nothing seeds (OPS_ENVIRONMENT=production). Every value comes from the OPS_BOOTSTRAP_* settings. The team takes
the deployment's security team id (OPS_SECURITY_TEAM_ID), which tools-service still reads from settings, and becomes
the workspace's security and default team. The admin is workspace admin and Security admin, so one person can
set egress, secrets and storage and invite everyone else.

It writes only until the admin has a password. From then on a run changes nothing, so a release command can call it
on every deploy without undoing a password the admin changed or a team they renamed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.logging import configure_logging, get_logger
from ops_service_kit.settings import Settings
from ops_signin import PasswordHasher

from .store.identity import IdentityStore
from .store.seeding import write_seed
from .store.signin import SignInStore
from .store.tenancy import TenantDb
from .store.workspace import WorkspaceStore

log = get_logger("ops_platform.bootstrap")
Outcome = Literal["created", "unchanged"]


@dataclass(frozen=True)
class FirstAdmin:
    tenant_id: str
    tenant_name: str
    team_id: str
    team_name: str
    email: str
    name: str
    password: str

    @classmethod
    def from_settings(cls, s: Settings) -> FirstAdmin:
        values = {
            "OPS_BOOTSTRAP_TENANT_ID": s.bootstrap_tenant_id,
            "OPS_BOOTSTRAP_TENANT_NAME": s.bootstrap_tenant_name,
            "OPS_BOOTSTRAP_TEAM_NAME": s.bootstrap_team_name,
            "OPS_BOOTSTRAP_ADMIN_EMAIL": s.bootstrap_admin_email,
            "OPS_BOOTSTRAP_ADMIN_NAME": s.bootstrap_admin_name,
            "OPS_BOOTSTRAP_ADMIN_PASSWORD": s.bootstrap_admin_password.get_secret_value()
            if s.bootstrap_admin_password
            else None,
        }
        missing = [k for k, v in values.items() if not (v or "").strip()]
        if missing:
            raise ValueError(f"bootstrap: set {', '.join(missing)}")
        password = values["OPS_BOOTSTRAP_ADMIN_PASSWORD"] or ""
        if len(password) < s.password_min_length:
            raise ValueError(
                f"bootstrap: OPS_BOOTSTRAP_ADMIN_PASSWORD needs at least {s.password_min_length} characters"
            )
        return cls(
            tenant_id=str(s.bootstrap_tenant_id),
            tenant_name=str(s.bootstrap_tenant_name),
            team_id=s.security_team_id,
            team_name=str(s.bootstrap_team_name),
            email=str(s.bootstrap_admin_email).strip().lower(),
            name=str(s.bootstrap_admin_name),
            password=password,
        )


async def bootstrap(database_url: str, admin: FirstAdmin, *, iterations: int) -> Outcome:
    db = TenantDb.open(database_url)
    try:
        signin = SignInStore(db, security_team=admin.team_id)
        # Found by email, so the id comes from the one id generator and a second run names the same person.
        known = [u for u in await IdentityStore(db).users_by_email(admin.email) if u.tenant_id == admin.tenant_id]
        user_id = known[0].id if known else new_id("usr")
        # Keyed on the admin's password, the last write: a run stopped between the two writes finishes on the next.
        if known and await signin.password_hash(admin.tenant_id, user_id) is not None:
            return "unchanged"
        empty: list[str] = []
        seed: dict[str, Any] = {
            "tenant": {"id": admin.tenant_id, "name": admin.tenant_name, "allowedDomains": empty},
            "teams": [{"id": admin.team_id, "name": admin.team_name, "ownerGroups": empty, "scope": "all"}],
            "people": [
                {
                    "id": user_id,
                    "name": admin.name,
                    "email": admin.email,
                    "teams": {admin.team_id: "admin"},
                    # Workspace admin and Security admin in every team, so one person can set up the rest.
                    "everyTeam": ["admin", "security_admin"],
                }
            ],
        }
        await write_seed(db, seed, security_team=admin.team_id)
        # The team is the workspace's security team and the one people join when nothing else names one.
        await WorkspaceStore(db, fallback_security_team=admin.team_id).set(
            admin.tenant_id,
            security_team=admin.team_id,
            default_team=admin.team_id,
            by=user_id,
            at=now_iso(),
            request_id="bootstrap",
        )
        encoded = await asyncio.to_thread(PasswordHasher(iterations).hash, admin.password)
        await signin.set_password(admin.tenant_id, user_id, encoded, at=now_iso())
        return "created"
    finally:
        await db.engine.dispose()


def main() -> None:
    configure_logging()
    settings = Settings()
    try:
        admin = FirstAdmin.from_settings(settings)
    except ValueError as e:
        raise SystemExit(str(e)) from e
    outcome = asyncio.run(bootstrap(settings.database_url, admin, iterations=settings.password_hash_iterations))
    log.info("bootstrap", outcome=outcome, tenant=admin.tenant_id, team=admin.team_id, email=admin.email)


if __name__ == "__main__":
    main()
