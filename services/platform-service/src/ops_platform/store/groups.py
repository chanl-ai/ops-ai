"""Groups: sets of people a role is given to, in one team or in every team (`RoleStore.assign` with a group subject).

A group is kept by hand or mirrors a sign-in provider's group by the value it sends. Every change commits with its
audit entry and raises the tenant's permission version, so the next token of everyone in the group carries what the
group now gives them. Who is in a group feeds `holdings_with`, the one read of what applies to a person.
"""

from __future__ import annotations

from typing import ClassVar, Literal

import sqlalchemy as sa

from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee

from .audit import record
from .roles import bump_version
from .tables import group_members, groups, role_assignments
from .tenancy import TenantDb


class GroupNameTakenError(Exception):
    """Another group of the workspace has that name."""


class GroupStore(TenantDb):
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    async def create(
        self,
        tenant_id: str,
        *,
        name: str,
        by: str,
        request_id: str,
        provider_id: str | None = None,
        external_value: str | None = None,
    ) -> str:
        """A group, audited as `group.create`; GroupNameTakenError when the name is used, case aside."""
        group_id = new_id("grp")
        async with self.tenant_tx(tenant_id) as c:
            taken = await c.execute(sa.select(groups.c.id).where(sa.func.lower(groups.c.name) == name.lower()))
            if taken.first() is not None:
                raise GroupNameTakenError
            await c.execute(
                groups.insert().values(
                    tenant_id=tenant_id, id=group_id, name=name, provider_id=provider_id,
                    external_value=external_value, created_by=by, created_at=now_iso(),
                )
            )  # fmt: skip
            await record(
                c, tenant_id=tenant_id, team_id=None, actor=by, action="group.create", target_kind="group",
                target_id=group_id, request_id=request_id, detail={"name": name, "providerId": provider_id},
            )  # fmt: skip
        return group_id

    async def add_member(
        self,
        tenant_id: str,
        group_id: str,
        user_id: str,
        *,
        by: str,
        request_id: str,
        source: Literal["manual", "provider"] = "manual",
    ) -> bool:
        """Puts the person in the group, audited as `group.member_add`; False when they are in it already."""
        async with self.tenant_tx(tenant_id) as c:
            held = sa.and_(group_members.c.group_id == group_id, group_members.c.user_id == user_id)
            if (await c.execute(sa.select(group_members.c.user_id).where(held))).first() is not None:
                return False
            await c.execute(
                group_members.insert().values(
                    tenant_id=tenant_id, group_id=group_id, user_id=user_id, source=source, added_by=by,
                    added_at=now_iso(),
                )
            )  # fmt: skip
            await bump_version(c, tenant_id)
            await record(
                c, tenant_id=tenant_id, team_id=None, actor=by, action="group.member_add", target_kind="person",
                target_id=user_id, request_id=request_id, detail={"groupId": group_id, "source": source},
            )  # fmt: skip
        return True

    async def remove_member(self, tenant_id: str, group_id: str, user_id: str, *, by: str, request_id: str) -> bool:
        """Takes the person out of the group, audited as `group.member_remove`: they lose only what the group's
        assignments gave them. False when they were not in it."""
        async with self.tenant_tx(tenant_id) as c:
            gone = await c.execute(
                group_members.delete().where(group_members.c.group_id == group_id, group_members.c.user_id == user_id)
            )
            if not gone.rowcount:
                return False
            await bump_version(c, tenant_id)
            await record(
                c, tenant_id=tenant_id, team_id=None, actor=by, action="group.member_remove", target_kind="person",
                target_id=user_id, request_id=request_id, detail={"groupId": group_id},
            )  # fmt: skip
        return True

    async def delete(self, tenant_id: str, group_id: str, *, by: str, request_id: str) -> bool:
        """Deletes the group, its people and every role given to it, audited as `group.delete`; False when no such
        group."""
        async with self.tenant_tx(tenant_id) as c:
            await c.execute(
                role_assignments.delete().where(
                    role_assignments.c.subject_kind == "group", role_assignments.c.subject_id == group_id
                )
            )
            await c.execute(group_members.delete().where(group_members.c.group_id == group_id))
            gone = await c.execute(groups.delete().where(groups.c.id == group_id))
            if not gone.rowcount:
                return False
            await bump_version(c, tenant_id)
            await record(
                c, tenant_id=tenant_id, team_id=None, actor=by, action="group.delete", target_kind="group",
                target_id=group_id, request_id=request_id, detail={},
            )  # fmt: skip
        return True
