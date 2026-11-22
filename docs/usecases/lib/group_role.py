"""Gives a group a role in a team, on the run's platform database: `python group_role.py <database url> <tenant id>
<actor user id> <member user id> <role id> <team id> <group name>`, printing the group's id.

No route and no screen gives a role to a group yet; the store does (RoleStore.assign, GroupStore). A use case that
needs the state seeds it here, as a setup step, and proves what a person sees of it."""

from __future__ import annotations

import asyncio
import sys

from ops_platform.store.groups import GroupStore
from ops_platform.store.identity import IdentityStore
from ops_platform.store.roles import RoleStore
from ops_service_kit.ids import new_id


async def main(url: str, tenant: str, actor: str, member: str, role: str, team: str, name: str) -> None:
    store = IdentityStore.open(url)
    try:
        groups = GroupStore(store)
        group = await groups.create(tenant, name=name, by=actor, request_id=new_id("req"))
        await groups.add_member(tenant, group, member, by=actor, request_id=new_id("req"))
        await RoleStore(store).assign(
            tenant, subject_kind="group", subject_id=group, role_id=role, team_id=team, by=actor, request_id=new_id("req")
        )
        print(group)
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:8]))
