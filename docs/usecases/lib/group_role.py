"""Makes a group holding one person, on the run's platform database: `python group_role.py <database url> <tenant id>
<actor user id> <member user id> <group name>`, printing the group's id.

No route and no screen makes a group or adds people to it yet; the store does (GroupStore). A use case that needs a
group seeds it here as a setup step; giving the group a role goes through the role's page (`POST /v1/roles/{id}/holders`).
"""

from __future__ import annotations

import asyncio
import sys

from ops_platform.store.groups import GroupStore
from ops_platform.store.identity import IdentityStore
from ops_service_kit.ids import new_id


async def main(url: str, tenant: str, actor: str, member: str, name: str) -> None:
    store = IdentityStore.open(url)
    try:
        groups = GroupStore(store)
        group = await groups.create(tenant, name=name, by=actor, request_id=new_id("req"))
        await groups.add_member(tenant, group, member, by=actor, request_id=new_id("req"))
        print(group)
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:6]))
