"""Starting a run by hand: one adapter per kind of trigger turns the start form its trigger declares
(`ops_engine.starts`) into what the trigger's real source produces, and starts the run through that source's own entry.

`email` builds the `InboundMessage` a mailbox would deliver, with each attachment's bytes read back from Files, and
hands it to `EmailStarts.start`, the function the mailbox listener calls for every message: attachments, body file,
input and run key take one path, and only who started it differs. `form` passes the values as the run's input, as
`POST /v1/runs` does. A new kind of trigger adds a `StartSpec` to its node type and an adapter here; the console draws
its form without a change.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, cast

from ops_email import InboundAttachment, InboundMessage
from ops_engine import default_registry
from ops_engine.node_types import start_form
from ops_engine.store import DefinitionRow, RunRow, RunStore
from ops_files_client import FileNotFound, FileNotReady, FilesClient, FilesRefused
from ops_service_kit.errors import Conflict, ServiceUnavailable, Unprocessable
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.ids import now_iso
from ops_service_kit.narrow import an_object

from ..store.engine import EngineTransactions
from ..store.tenancy import current_tenant
from .auth import Principal, approves_own_writes, started_by
from .deps import Runtime
from .email_trigger import EmailStarts, Target, binding_of
from .engine_runs import checked_values, start_run

REGISTRY = default_registry()
Mode = Literal["live", "test"]


@dataclass(frozen=True)
class HandStart:
    """One start by hand: who, on which definition row, the form's values, the mode, and `started_via`."""

    me: Principal
    stored: DefinitionRow
    values: Json
    mode: Mode
    via: str


Adapter = Callable[[Runtime, HandStart], Awaitable[RunRow]]
# The prefix of `started_via` for a run started by hand; the kind follows, and actors read it as the form's `via`.
VIA_PREFIX = "start:"


async def by_form(rt: Runtime, h: HandStart) -> RunRow:
    run, _ = await start_run(
        RunStore(EngineTransactions(rt.db)),
        h.stored,
        team_id=h.me.team_id,
        mode=h.mode,
        input=h.values,
        run_key=None,
        created_by=started_by(h.me),
        started_via=h.via,
        started_by_approver=approves_own_writes(h.me),
    )
    return run


def _text(values: Json, key: str) -> str:
    v = values.get(key)
    return v.strip() if isinstance(v, str) else ""


async def _attachment(files: FilesClient, tenant: str, team: str, ref: JsonValue) -> InboundAttachment:
    """A file in Files as the attachment a mailbox would have delivered: its name, type and bytes. A file the team
    cannot see, or one not scanned clean, is refused, as files-service refuses to hand its bytes to anyone."""
    file_id = str(ref.get("fileId") if isinstance(ref, dict) else ref or "")
    try:
        info = await files.get(tenant, team, file_id)
        data = await files.read(tenant, team, file_id)
    except FileNotFound as e:
        raise Unprocessable(
            f"Attachment {file_id or '(empty)'} is not in your team's Files.", code="attachment_not_found"
        ) from e
    except FileNotReady as e:
        raise Unprocessable(
            "An attachment has not passed its malware scan, so it cannot be sent.", code="attachment_not_clean"
        ) from e
    except FilesRefused as e:
        raise ServiceUnavailable(f"Files did not hand over an attachment: {e.message}") from e
    return InboundAttachment(name=info.name, mime=info.mime, content=base64.b64encode(data).decode())


async def by_email(rt: Runtime, h: HandStart) -> RunRow:
    me, stored, values = h.me, h.stored, h.values
    files = cast(FilesClient | None, rt.start_files)
    if files is None:
        raise ServiceUnavailable("A test email stores its attachments in Files, and this service has no Files URL.")
    sender = _text(values, "from")
    if not sender:
        raise Unprocessable("A test email needs who sent it.", code="invalid_input", details={"field": "from"})
    tenant, team = current_tenant(), me.team_id
    refs = cast(list[JsonValue], values.get("attachments") or [])
    msg = InboundMessage(
        # A Message-ID of its own, so each test email is a new message with its own run key.
        key=f"<{uuid.uuid4().hex}@test-email.ops-ai>",
        sender=sender,
        subject=_text(values, "subject"),
        body=str(values.get("body") or ""),
        received_at=now_iso(),
        attachments=tuple([await _attachment(files, tenant, team, r) for r in refs]),
    )
    binding = binding_of(stored.definition)
    assert binding is not None  # the start form said email
    if (failed := binding.filter.failed(msg)) is not None:
        raise Unprocessable(
            "The trigger's filters would skip this email, so no run starts.",
            code="email_filtered",
            details={"failed": failed},
        )
    started = await EmailStarts(rt.db, files).start(
        Target(stored, binding, team), msg, mode=h.mode, by=started_by(me), via=h.via
    )
    if started.run is None:
        raise Conflict("The workflow has started as many runs today as its trigger allows.", code="daily_cap")
    return started.run


ADAPTERS: dict[str, Adapter] = {"form": by_form, "email": by_email, "schedule": by_form}


def filled(form: Json, values: Json) -> Json:
    """The start form's values as a run takes them: its defaults, and text read as each field's declared type, or
    422 `invalid_input` naming the field and the reason, as the console's start dialog says it. `details.path` is the
    schema property."""
    return checked_values(an_object(form.get("schema") or {}, "start form schema"), values)


async def start(rt: Runtime, me: Principal, stored: DefinitionRow, values: Json, mode: Mode) -> RunRow:
    """Starts the run on `stored` from the start form's `values` with the adapter for its trigger's kind."""
    form = start_form(stored.definition, REGISTRY)
    adapter = ADAPTERS.get(str(form["kind"])) if form else None
    if form is None or adapter is None:
        raise Unprocessable("This workflow's trigger is started only by its source, not by hand.", code="no_start_form")
    return await adapter(rt, HandStart(me, stored, filled(form, values), mode, VIA_PREFIX + str(form["kind"])))
