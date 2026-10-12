"""The mailbox channel: Graph delta results in, find-or-create thread and run calls out (E6).

Every step is idempotent, so a poll can be repeated after a crash: the thread is found by its external key
(deployment id + Message-ID), a run's id is derived from the same key so a repeat replays instead of re-running, a
reply's inbox entry is keyed by its own Message-ID, and attachment ids are derived from the message. The ledger
(`channel_messages`) records what was handled, which turns redeliveries and folder moves into no-ops, and the delta
cursor is saved only after the last page, so a poll that dies part-way starts again from the previous cursor.

The adapter talks to the thread API over HTTP (the four calls plus the inbox), so nothing in a graph knows that mail
exists: the graph receives an `email` with attachment references.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from ops_service_kit.ids import now_iso

from ....store.channels import ChannelStore, Deployment
from .graph_port import MailSource

Hook = Callable[[dict[str, Any]], Awaitable[None]]


def text_at(d: Any, *path: str) -> str:
    """The string at `path` in Graph's JSON, or "" when a step is missing; Graph omits empty properties."""
    for step in path:
        if not isinstance(d, dict):
            return ""
        d = cast(dict[str, Any], d).get(step)
    return "" if d is None else str(d)


def normalise_message_id(raw: str) -> str:
    """Message-IDs arrive with and without angle brackets and with varying case. The local part is case-sensitive by
    RFC 5322 and kept as is; the domain is not, and is lower-cased."""
    mid = raw.strip().strip("<>").strip()
    local, at, domain = mid.rpartition("@")
    return f"{local}@{domain.lower()}" if at else mid


def message_key(item: dict[str, Any]) -> str:
    raw = text_at(item, "internetMessageId")
    if raw:
        return normalise_message_id(raw)
    # No Message-ID: key on who sent it, when and the subject, so a redelivery of the same message still matches.
    sender = text_at(item, "from", "emailAddress", "address").lower()
    basis = f"{sender}|{text_at(item, 'receivedDateTime')}|{text_at(item, 'subject').strip()}"
    return "synthetic:" + hashlib.sha256(basis.encode()).hexdigest()[:32]


def references(item: dict[str, Any]) -> list[str]:
    """In-Reply-To first, then References newest to oldest: the order in which to look for the case."""
    raw_headers: list[Any] = list(item.get("internetMessageHeaders") or [])
    headers = {text_at(h, "name").lower(): text_at(h, "value") for h in raw_headers}
    refs: list[str] = []
    if headers.get("in-reply-to"):
        refs.append(normalise_message_id(headers["in-reply-to"]))
    for raw in reversed(headers.get("references", "").split()):
        ref = normalise_message_id(raw)
        if ref not in refs:
            refs.append(ref)
    return refs


@dataclass
class PollReport:
    items: int = 0
    new_cases: int = 0
    duplicates: int = 0
    delivered: int = 0
    queued: int = 0
    followups: int = 0
    deferred: int = 0
    removed: int = 0
    pages: int = 0
    errors: list[str] = field(default_factory=list[str])


class MailboxAdapter:
    def __init__(
        self,
        api: httpx.AsyncClient,
        source: MailSource,
        channels: ChannelStore,
        deployment_id: str,
        *,
        before_item: Hook | None = None,
        after_item: Hook | None = None,
    ) -> None:
        self.api = api
        self.source = source
        self.channels = channels
        self.deployment_id = deployment_id
        # Tests and measurements only: run around each item, e.g. to hold a case's lease so a reply arrives mid-run.
        self.before_item = before_item
        self.after_item = after_item

    def _key(self, key: str) -> str:
        return f"{self.deployment_id}:{key}"

    async def poll(self) -> PollReport:
        report = PollReport()
        deployment = await self.channels.deployment(self.deployment_id)
        if deployment is None:
            raise LookupError(f"deployment {self.deployment_id} does not exist")
        if not deployment.paused:
            for row in await self.channels.deferred(self.deployment_id):
                await self._handle(deployment, row["payload"], report, retry=True)
        link = await self.channels.cursor(self.deployment_id)
        while True:
            page = await self.source.delta(link)
            report.pages += 1
            for item in page.items:
                await self._handle(deployment, item, report)
            if page.next_link is not None:
                link = page.next_link
                continue
            assert page.delta_link is not None
            # Only now: a poll that dies before here starts again from the previous cursor, and the ledger makes the
            # replayed items no-ops.
            await self.channels.save_cursor(self.deployment_id, page.delta_link, now_iso())
            return report

    async def _handle(self, d: Deployment, item: dict[str, Any], report: PollReport, *, retry: bool = False) -> None:
        if "@removed" in item:
            report.removed += 1  # deleted or moved out of the folder: the case, if any, is unaffected
            return
        report.items += 1
        key = message_key(item)
        seen = (await self.channels.seen(self.deployment_id, [key])).get(key)
        if seen is not None and seen["status"] == "handled":
            report.duplicates += 1
            return
        if seen is not None and seen["status"] == "deferred" and not retry:
            return  # retried at the start of a poll, once the deployment is running again
        if self.before_item:
            await self.before_item(item)
        try:
            case = await self._case_for(references(item))
            if case is None:
                await self._new_case(d, key, item, report)
            else:
                await self._reply(d, key, item, case, report)
        finally:
            if self.after_item:
                await self.after_item(item)

    async def _case_for(self, refs: list[str]) -> str | None:
        if not refs:
            return None
        seen = await self.channels.seen(self.deployment_id, refs)
        for ref in refs:
            if (row := seen.get(ref)) is not None and row["thread_id"]:
                return str(row["thread_id"])
        # The referenced message may be mid-delivery on another poller: its case exists, its ledger row does not yet.
        for ref in refs:
            if (thread := await self.channels.thread_for_key(self._key(ref))) is not None:
                return thread
        return None

    async def _email(self, key: str, item: dict[str, Any]) -> dict[str, Any]:
        attachments: list[dict[str, str]] = []
        raw_attachments: list[Any] = list(item.get("attachments") or [])
        for i, a in enumerate(raw_attachments):
            # Bytes go to the files stub under an id derived from the message, never into graph state (E4).
            file_id = "file_" + hashlib.sha256(f"{self._key(key)}#{i}".encode()).hexdigest()[:24]
            name = text_at(a, "name") or f"attachment-{i}"
            content = text_at(a, "contentBytes")
            await self.channels.put_file(
                file_id,
                name=name,
                content_type=text_at(a, "contentType") or "text/plain",
                content=content,
                sha256=hashlib.sha256(content.encode()).hexdigest(),
            )
            attachments.append({"name": name, "file_id": file_id})
        return {
            "sender": text_at(item, "from", "emailAddress", "address"),
            "subject": text_at(item, "subject"),
            "body": text_at(item, "body", "content"),
            "attachments": attachments,
        }

    async def _open(self, d: Deployment, key: str, item: dict[str, Any], *, parent: str | None) -> str | None:
        """Find-or-create the case for this message and start its run. None when the deployment is paused."""
        body: dict[str, Any] = {
            "graph": d.graph,
            "externalKey": self._key(key),
            "deploymentId": d.id,
            "metadata": {"channel": "mailbox", "subject": item.get("subject")},
        }
        if parent:
            body["parentThreadId"] = parent
        r = await self.api.post("/v1/threads", json=body)
        if r.status_code == 409 and r.json()["error"]["code"] == "deployment_paused":
            return None
        r.raise_for_status()
        thread_id = str(r.json()["data"]["threadId"])
        run_id = "run_" + hashlib.sha256(self._key(key).encode()).hexdigest()[:16]
        async with self.api.stream(
            "POST",
            f"/v1/threads/{thread_id}/runs/stream",
            json={"runId": run_id, "input": {"email": await self._email(key, item)}},
        ) as res:
            # 409: the run is active or the case already moved on; either way this message's run exists.
            if res.status_code not in (200, 409):
                await res.aread()
                res.raise_for_status()
            async for _ in res.aiter_bytes():
                pass
        return thread_id

    async def _new_case(self, d: Deployment, key: str, item: dict[str, Any], report: PollReport) -> None:
        thread_id = await self._open(d, key, item, parent=None)
        if thread_id is None:
            report.deferred += 1
            await self.channels.record(
                self.deployment_id, key, thread_id=None, role="new", status="deferred", now=now_iso(), payload=item
            )
            return
        report.new_cases += 1
        await self.channels.record(
            self.deployment_id, key, thread_id=thread_id, role="new", status="handled", now=now_iso()
        )

    async def _reply(self, d: Deployment, key: str, item: dict[str, Any], case: str, report: PollReport) -> None:
        r = await self.api.post(
            f"/v1/threads/{case}/inbox",
            json={"kind": "customer_reply", "messageKey": key, "payload": {"email": await self._email(key, item)}},
        )
        if r.status_code == 409:
            code = r.json()["error"]["code"]
            if code == "thread_closed":
                followup = await self._open(d, key, item, parent=case)
                if followup is None:
                    report.deferred += 1
                    await self.channels.record(
                        self.deployment_id,
                        key,
                        thread_id=None,
                        role="followup",
                        status="deferred",
                        now=now_iso(),
                        payload=item,
                    )
                    return
                report.followups += 1
                await self.channels.record(
                    self.deployment_id, key, thread_id=followup, role="followup", status="handled", now=now_iso()
                )
                return
            # The deployment refuses messages while the case runs (multitask reject): try again next poll.
            report.deferred += 1
            await self.channels.record(
                self.deployment_id, key, thread_id=case, role="reply", status="deferred", now=now_iso(), payload=item
            )
            return
        r.raise_for_status()
        status = r.json()["data"]["status"]
        report.delivered += status == "delivered"
        report.queued += status == "queued"
        await self.channels.record(
            self.deployment_id, key, thread_id=case, role="reply", status="handled", now=now_iso()
        )
