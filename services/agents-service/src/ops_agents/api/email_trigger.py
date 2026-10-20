"""The Email received trigger (c-187): a live workflow version whose trigger node is `ops.trigger.email` watches one
folder of one team mailbox, and each new message that matches its filters starts one run through `start_run`.

The trigger node in the live version is the binding. Going live already takes a publish request, so binding a mailbox
is decided there. A mailbox (connected on Channels > Email, `store/mailboxes.py`) belongs to one team of one tenant.
Only a workflow that team owns, in that tenant, binds it, and the publisher needs `deployments.create` in the team
(the workflow is put on a channel); the listener checks the same rule again before it reads, for a version that went
live before it held. The poll acts for no person: it was authorised when the version went live, and each run it
starts is recorded as started by `trigger:email:<mailbox>`. A paused mailbox is not read.
"""

from __future__ import annotations

import asyncio
import binascii
import contextlib
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from ops_access import can
from ops_email import CursorRefusedError, EmailFilter, InboundMessage, MailSource, drain
from ops_engine.store import DefinitionStore, RunStore
from ops_files_client import FilesClient, FilesRefused
from ops_service_kit.errors import Unprocessable
from ops_service_kit.logging import get_logger
from ops_store import isolation

from ..store.engine import AsyncEngine, EngineTransactions
from ..store.leases import LeaseHeldError, Leases
from ..store.mailboxes import MailboxRow, MailboxStore
from ..store.poll_cursors import PollCursor, PollCursors
from ..store.tenancy import MAIL_LISTENER
from ..store.trigger_events import Outcome, TriggerEvent, TriggerEvents
from .auth import Principal, caller_of
from .engine_runs import start_run
from .mailbox_gateway import is_idle

log = get_logger("ops_agents.api.email_trigger")
# The reader for one folder of one mailbox.
SourceFor = Callable[[MailboxRow, str], MailSource]
# A binding's poll lease is a thread lease with no thread: the sweeper leaves these alone.
POLL_LEASE_PREFIX = "poll_"

EMAIL_TRIGGER = "ops.trigger.email"
# The name an email's text is stored under in Files (c-259).
BODY_FILE = "email-body.txt"


@dataclass(frozen=True)
class EmailBinding:
    mailbox: str
    folder: str
    filter: EmailFilter
    # Runs the trigger may start in a UTC day; None for no cap.
    daily_cap: int | None = None


def binding_of(definition: dict[str, Any] | None) -> EmailBinding | None:
    """The definition's email trigger, or None when it starts some other way."""
    nodes = cast(list[dict[str, Any]], (definition or {}).get("nodes") or [])
    for node in nodes:
        if node.get("type") == EMAIL_TRIGGER:
            p = cast(dict[str, Any], node.get("parameters") or {})
            return EmailBinding(
                mailbox=str(p.get("mailbox") or ""),
                folder=str(p.get("folder") or "inbox"),
                filter=EmailFilter(
                    from_contains=str(p.get("fromContains") or ""),
                    subject_contains=str(p.get("subjectContains") or ""),
                    has_attachment=bool(p.get("hasAttachment")),
                ),
                daily_cap=int(p["dailyCap"]) if p.get("dailyCap") else None,
            )
    return None


async def bindable(mailboxes: MailboxStore, row: dict[str, Any], address: str) -> tuple[MailboxRow | None, str | None]:
    """The mailbox a stored version may watch, or None with the reason: the workflow must belong to a team, in the
    mailbox's tenant, and that team must own the mailbox. A workflow no team owns is seen by every team, so it would
    hand one team's mail to all of them."""
    team = row.get("team_id")
    if not team:
        return None, "An Email received trigger reads a team's mailbox, so the workflow must belong to a team."
    mailbox = await mailboxes.by_address(str(row["tenant_id"]), address)
    if mailbox is None:
        return None, f"{address or 'No mailbox'} is not a mailbox connected on Channels > Email."
    if mailbox.team_id != team:
        return None, f"{mailbox.address} is {mailbox.team_id}'s mailbox; a workflow {team} owns cannot watch it."
    return mailbox, None


async def require_binding(mailboxes: MailboxStore, me: Principal, row: dict[str, Any]) -> None:
    """Refuses to take a version live whose email trigger the publisher may not bind. A no-op for other triggers."""
    binding = binding_of(row.get("definition"))
    if binding is None:
        return
    mailbox, why = await bindable(mailboxes, row, binding.mailbox)
    if mailbox is None:
        code = "email_trigger_needs_team" if not row.get("team_id") else "mailbox_not_offered"
        raise Unprocessable(str(why), code=code, details={"field": "mailbox"})
    can(caller_of(me), "deployments", "create", team=mailbox.team_id, what=f"a watch on {mailbox.address}")


# files-service answers that will not change on a retry: the attachment is over the purpose's size limit, of a type the
# purpose does not allow, or refused for another reason. Read again, the message would fail the same way and block the
# mailbox behind it. Any 4xx but the retryable ones is a refusal, so a status added to files-service later cannot
# stall a mailbox. Retryable: 401 and 403 are this service's own token refused, which a fix gets past; 409 and 423 are
# the same upload in flight from another workflow on the mailbox (one idempotency key), which the next read replays.
REFUSED_FOR_GOOD = {413: "too_large", 415: "type_not_allowed"}
RETRYABLE_4XX = {401, 403, 408, 409, 423, 429}


def refusal(status: int) -> str | None:
    """Why files-service will never store the attachment, or None when a later read may succeed."""
    if status in REFUSED_FOR_GOOD:
        return REFUSED_FOR_GOOD[status]
    return "refused" if 400 <= status < 500 and status not in RETRYABLE_4XX else None


def run_key(fingerprint: str) -> str:
    """The run key for one message, from `InboundMessage.fingerprint`: equal for every delivery of the message, so
    `engine_runs`' unique key refuses a second run, and different for another message reusing its Message-ID."""
    return "email:" + hashlib.sha256(fingerprint.encode()).hexdigest()[:40]


@dataclass
class PollResult:
    workflow_id: str
    started: list[str] = field(default_factory=list[str])
    skipped: int = 0
    first_sync: bool = False
    busy: bool = False


@dataclass(frozen=True)
class Bound:
    """A live version's email trigger with the mailbox record it may read."""

    row: dict[str, Any]
    binding: EmailBinding
    mailbox: MailboxRow

    @property
    def tenant(self) -> str:
        return str(self.row["tenant_id"])

    @property
    def workflow(self) -> str:
        return str(self.row["workflow_id"])


class EmailTriggers:
    """The mailbox listener: reads every bound mailbox and starts a run per new matching message. One call of
    `poll_all` is one pass; the worker repeats it every `Settings.email_poll_seconds`."""

    # The lease's run id: every poller of a binding uses it, so the lease, not the id, says who polls.
    LEASE_RUN = "email-poll"

    def __init__(
        self,
        db: AsyncEngine,
        sources: SourceFor,
        files: FilesClient,
        leases: Leases,
        *,
        idle_seconds: float = 25.0,
    ) -> None:
        """`sources` gives the reader for one folder of one mailbox record: the dev folder, or the gateway source
        (`mailbox_gateway.py`) for a mailbox tools-service reads. `idle_seconds` is one IDLE's longest wait."""
        self.db = db
        self.sources = sources
        self.files = files
        self.leases = leases
        self.idle_seconds = idle_seconds
        self.cursors = PollCursors(db)
        self.events = TriggerEvents(db)
        self.mailboxes = MailboxStore(db)

    async def bindings(self) -> list[Bound]:
        """Every live version's email trigger whose mailbox it may read, in every tenant. A paused mailbox is left
        out: nothing reads it until it resumes."""
        out: list[Bound] = []
        for row in await DefinitionStore(EngineTransactions(self.db)).live_everywhere():
            binding = binding_of(row["definition"])
            if binding is None:
                continue
            mailbox, why = await bindable(self.mailboxes, row, binding.mailbox)
            if mailbox is None:
                log.warning("email_binding_refused", workflow=row["workflow_id"], mailbox=binding.mailbox, reason=why)
                continue
            if not mailbox.paused:
                out.append(Bound(row, binding, mailbox))
        return out

    def source(self, b: Bound) -> MailSource:
        return self.sources(b.mailbox, b.binding.folder)

    async def poll_all(self) -> list[PollResult]:
        out: list[PollResult] = []
        for b in await self.bindings():
            with isolation.tenant_wide(MAIL_LISTENER, tenant_id=b.tenant):
                # One failing mailbox must not stop the others; its cursor stayed, so its next pass retries.
                try:
                    out.append(await self.poll(b))
                except Exception as e:
                    log.exception("email_poll_failed", workflow=b.workflow, error=type(e).__name__)
        return out

    async def run_forever(self, stop: asyncio.Event, every: float) -> None:
        """A poll of every binding each `every` seconds, and beside it one IDLE task per binding whose mailbox can
        wait for new mail (IMAP): mail there starts its run within seconds, and the poll still reads it when IDLE
        fails or the server has none."""
        idlers: dict[str, asyncio.Task[None]] = {}
        try:
            while not stop.is_set():
                await self.poll_all()
                live: set[str] = set()
                for b in await self.bindings():
                    if not is_idle(self.source(b)):
                        continue
                    key = f"{b.tenant}:{b.workflow}:{b.row['version']}:{b.mailbox.id}:{b.mailbox.updated_at}"
                    live.add(key)
                    if key not in idlers or idlers[key].done():
                        idlers[key] = asyncio.create_task(self.idle_forever(b, stop, every))
                for key in set(idlers) - live:
                    idlers.pop(key).cancel()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), every)
        finally:
            for task in idlers.values():
                task.cancel()

    async def idle_forever(self, b: Bound, stop: asyncio.Event, every: float) -> None:
        """Waits on the binding's mailbox by IDLE and polls it as soon as mail arrives."""
        source = self.source(b)
        if not is_idle(source):
            return
        here = (b.binding.mailbox.lower(), b.binding.folder.lower())
        with isolation.tenant_wide(MAIL_LISTENER, tenant_id=b.tenant):
            while not stop.is_set():
                at = await self.cursors.get(f"email:{b.workflow}")
                if at is None or (at.source.lower(), at.folder.lower()) != here:
                    await _pause(stop, every)  # the poll takes the first cursor
                    continue
                try:
                    changed = await source.wait(at.cursor, self.idle_seconds)
                    if changed and (await self.poll(b)).busy:
                        await _pause(stop, 1.0)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning("email_idle_failed", workflow=b.workflow, error=type(e).__name__)
                    await _pause(stop, every)

    async def poll(self, b: Bound) -> PollResult:
        """One pass over one binding, under the binding's lease so two workers never read it at once."""
        result = PollResult(b.workflow)
        lease = POLL_LEASE_PREFIX + hashlib.sha256(f"{b.tenant}:{b.workflow}".encode()).hexdigest()[:32]
        try:
            await self.leases.acquire(lease, self.LEASE_RUN)
        except LeaseHeldError:
            result.busy = True
            return result
        try:
            await self._poll(b, result)
        finally:
            await self.leases.release(lease, self.LEASE_RUN)
        return result

    async def _poll(self, b: Bound, result: PollResult) -> None:
        binding_id = f"email:{b.workflow}"
        source = self.source(b)
        at = await self.cursors.get(binding_id)
        here = (b.binding.mailbox.lower(), b.binding.folder.lower())
        if at is None or (at.source.lower(), at.folder.lower()) != here:
            # First pass on this mailbox folder: mail already there is history, not new work. Take the cursor at the
            # folder's end without reading it; what arrives after starts runs.
            cursor = await source.cursor_now()
            result.first_sync = True
        else:

            async def handle(item: dict[str, Any]) -> None:
                msg = source.parse(item)
                if msg.removed:
                    result.skipped += 1
                    return
                if (failed := b.binding.filter.failed(msg)) is not None:
                    result.skipped += 1
                    await self._record(b, msg, "filtered", detail={"failed": failed})
                    return
                run_id = await self._start(b, msg)
                if run_id:
                    result.started.append(run_id)

            try:
                cursor, _ = await drain(source, at.cursor, handle)
            except CursorRefusedError:
                # Start again at the folder's end rather than fail every poll from now on, and say so: the mail that
                # arrived since the last read is not read, and a person has to look at the mailbox for it.
                log.warning("mailbox_cursor_reset", workflow=b.workflow, mailbox=b.binding.mailbox)
                cursor = await source.cursor_now()
                await self._skipped_since_last_read(b)
        await self.cursors.save(binding_id, PollCursor(b.binding.mailbox, b.binding.folder, cursor))

    async def _start(self, b: Bound, msg: InboundMessage) -> str | None:
        """Stores the attachments in Files, then starts the run. Returns the run id when this call created it."""
        key = run_key(msg.fingerprint)
        runs = RunStore(EngineTransactions(self.db))
        if (existing := await runs.by_key(b.workflow, key)) is not None:
            # A redelivery: its run exists, and its attachments are already in Files.
            await self._record(b, msg, "duplicate", run_id=str(existing["id"]))
            return None
        cap = b.binding.daily_cap
        # One poller per binding holds its lease, so counting then starting cannot let two runs past the cap.
        if cap is not None and await self.events.started_since(b.workflow, today()) >= cap:
            log.info("email_daily_cap", workflow=b.workflow, cap=cap)
            await self._record(b, msg, "daily_cap", detail={"dailyCap": cap})
            return None
        team = b.mailbox.team_id
        sender = f"trigger:email:{b.binding.mailbox}"
        attachments: list[dict[str, Any]] = []
        # Attachments not stored, with why: the run says what it did not get instead of the pass failing on them.
        skipped: list[dict[str, Any]] = []
        for i, a in enumerate(msg.attachments):
            try:
                data = a.data()
            except binascii.Error:
                log.warning("email_attachment_unreadable", workflow=b.workflow, name=a.name)
                skipped.append(
                    {"name": a.name, "reason": "unreadable", "message": "The attachment could not be decoded."}
                )
                continue
            try:
                stored = await self.files.write(
                    b.tenant,
                    team,
                    data,
                    name=a.name,
                    mime=a.mime or "application/octet-stream",
                    purpose="case_attachment",
                    uploaded_by=sender,
                    idempotency_key=f"{key}:{i}",
                )
            except FilesRefused as e:
                if (reason := refusal(e.status)) is None:
                    raise  # files-service down or this service's token refused: read the message again later
                log.info("email_attachment_refused", workflow=b.workflow, name=a.name, status=e.status, code=e.code)
                skipped.append({"name": a.name, "reason": reason, "message": e.message})
                continue
            attachments.append(
                {"fileId": stored.file.id, "name": a.name, "mime": stored.file.mime, "size": stored.file.size}
            )
        # The text as a file too, so a workflow reads a body-only email through Extract from file like an attachment,
        # with places and corrections (c-259); the plain body stays on the input for workflows that use it.
        body_file: dict[str, Any] | None = None
        if msg.body and msg.body.strip():
            try:
                stored = await self.files.write(
                    b.tenant,
                    team,
                    msg.body.encode("utf-8"),
                    name=BODY_FILE,
                    mime="text/plain",
                    purpose="email_body",
                    uploaded_by=sender,
                    idempotency_key=f"{key}:body",
                )
            except FilesRefused as e:
                if (reason := refusal(e.status)) is None:
                    raise
                skipped.append({"name": BODY_FILE, "reason": reason, "message": e.message})
            else:
                body_file = {
                    "fileId": stored.file.id,
                    "name": BODY_FILE,
                    "mime": stored.file.mime,
                    "size": stored.file.size,
                }
        envelope = {
            "messageId": msg.key,
            "from": msg.sender,
            "subject": msg.subject,
            "body": msg.body,
            "receivedAt": msg.received_at,
            "mailbox": b.binding.mailbox,
            "folder": b.binding.folder,
            "attachments": attachments,
            "bodyFile": body_file,
            "skipped": skipped,
        }
        run, created = await start_run(
            runs, b.row, team_id=team, mode="live", input=envelope, run_key=key, created_by=sender
        )
        if created:
            log.info("email_run_started", workflow=b.workflow, run=run["id"], message=msg.key)
        await self._record(b, msg, "started" if created else "duplicate", run_id=str(run["id"]))
        return str(run["id"]) if created else None

    async def _skipped_since_last_read(self, b: Bound) -> None:
        """A row on the workflow's trigger list and on Activity: the mailbox refused where reading had got to, so mail
        that arrived since the last read was skipped and reading starts again from now."""
        at = datetime.now(UTC).isoformat()
        await self.events.add(
            TriggerEvent(
                team_id=b.mailbox.team_id,
                workflow_id=b.workflow,
                source=f"email:{b.binding.mailbox}",
                event_key=f"cursor_reset:{at}",
                sender=b.binding.mailbox,
                subject="Mail since the last read was skipped",
                received_at=at,
                outcome="cursor_reset",
                detail={
                    "message": "The mailbox no longer accepts where reading had got to, so mail that arrived since "
                    "the last read was not read. Reading starts again from now. Check the mailbox for mail that "
                    "needs a run."
                },
            )
        )

    async def _record(
        self,
        b: Bound,
        msg: InboundMessage,
        outcome: Outcome,
        *,
        run_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        await self.events.add(
            TriggerEvent(
                team_id=b.mailbox.team_id,
                workflow_id=b.workflow,
                source=f"email:{b.binding.mailbox}",
                event_key=run_key(msg.fingerprint),
                sender=msg.sender,
                subject=msg.subject,
                received_at=msg.received_at,
                outcome=outcome,
                run_id=run_id,
                detail=detail,
            )
        )


def today() -> str:
    """The start of the current UTC day, comparable with the stored ISO times."""
    return datetime.now(UTC).date().isoformat()


async def _pause(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), seconds)
