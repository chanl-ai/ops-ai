"""The mail source behind a port: Microsoft Graph's message delta query, or a fake that replays a fixture.

Graph delta returns pages of changed messages: follow `@odata.nextLink` to the end, then keep `@odata.deltaLink` for
the next poll. A message deleted or moved out of the folder comes back as an item with `@removed`; one moved in comes
back as a new item with the same `internetMessageId`, which the adapter's ledger turns into a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class DeltaPage:
    items: list[dict[str, Any]]
    next_link: str | None
    delta_link: str | None


class MailSource(Protocol):
    async def delta(self, link: str | None) -> DeltaPage:
        """`link` is None for the first sync, else the nextLink or deltaLink the previous page returned."""
        ...


class GraphMailSource:
    """Microsoft Graph delta over the inbox. Not yet run against a tenant: the fake source drives every test."""

    SELECT = "internetMessageId,subject,from,receivedDateTime,body,internetMessageHeaders,hasAttachments"

    def __init__(self, client: httpx.AsyncClient, mailbox: str) -> None:
        self.client = client
        self.mailbox = mailbox

    async def delta(self, link: str | None) -> DeltaPage:
        url = (
            link
            or f"/v1.0/users/{self.mailbox}/mailFolders/inbox/messages/delta?$select={self.SELECT}&$expand=attachments"
        )
        r = await self.client.get(url, headers={"Prefer": "odata.maxpagesize=50"})
        r.raise_for_status()
        body: dict[str, Any] = r.json()
        return DeltaPage(list(body.get("value", [])), body.get("@odata.nextLink"), body.get("@odata.deltaLink"))
