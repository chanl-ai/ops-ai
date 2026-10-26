"""How a waiting workflow step is resumed (c-525): one deduped resume row per pause, written by a review decision, a
signed callback or a service event, whichever comes first; and the callback's token.

A resume row is keyed `resume:{run}:{node}:{iteration}`, so a second resume of the same pause finds the first and
changes nothing; the worker drops a row meant for a pause the run has already left (its interrupt id). The callback
token is derived when the step parks and derived again to check, never stored, like the approval token minted at the
call: an HMAC over the run, step, pass, interrupt, tenant, team and expiry with a key derived from the review key.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from dataclasses import dataclass
from typing import Any, cast

from ops_engine.store import RunStore, WorkQueue
from ops_engine.store.clock import now_iso
from ops_policy.tokens import HmacSigner

from ..store.engine import AsyncEngine, EngineTransactions
from ..store.events import EventLog

RESUME_PURPOSE = "workflow-resume"


def resume_key(run_id: str, waiting: dict[str, Any]) -> str:
    return f"resume:{run_id}:{waiting['node']}:{waiting['iteration']}"


async def enqueue_resume(
    db: AsyncEngine, run_id: str, waiting: dict[str, Any], resume: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """The pause's one resume row, and whether this call wrote it (False: something resumed it first)."""
    payload = {
        "resume": resume,
        "payload": waiting.get("payload"),
        "at": now_iso(),
        "interruptId": waiting.get("interruptId"),
    }
    # Writing a row claims nothing, so the lease length the queue is built with plays no part here.
    queue = WorkQueue(EngineTransactions(db), owner="api", ttl=60.0)
    return await queue.enqueue(run_id, "resume", resume_key(run_id, waiting), payload)


@dataclass(frozen=True)
class ResumeClaim:
    """What a callback token says: whose run, which pause, until when."""

    tenant: str
    team: str
    run_id: str
    node: str
    iteration: int
    interrupt_id: str
    expires_at: int


def _message(c: ResumeClaim) -> bytes:
    return "|".join([c.tenant, c.team, c.run_id, c.node, str(c.iteration), c.interrupt_id, str(c.expires_at)]).encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def resume_token(review_key: str, claim: ResumeClaim) -> str:
    """`<claim>.<signature>`: the claim names the pause so the route finds the run without a person's token."""
    head = _b64(json.dumps(claim.__dict__, separators=(",", ":")).encode())
    return f"{head}.{_b64(HmacSigner.derived(review_key, RESUME_PURPOSE).sign(_message(claim)))}"


class BadResumeToken(ValueError):
    """The token is not one this service signed, or it has expired."""


def read_token(review_key: str, token: str, *, now: float | None = None) -> ResumeClaim:
    """The claim a valid, unexpired token carries; BadResumeToken otherwise."""
    try:
        head, sig = token.split(".", 1)
        claim = ResumeClaim(**cast(dict[str, Any], json.loads(_unb64(head))))
        signature = _unb64(sig)
    except (ValueError, TypeError, binascii.Error) as e:
        raise BadResumeToken("not a resume token") from e
    if not HmacSigner.derived(review_key, RESUME_PURPOSE).verify(_message(claim), signature):
        raise BadResumeToken("the signature does not match")
    if claim.expires_at < (time.time() if now is None else now):
        raise BadResumeToken("the token has expired")
    return claim


def resume_link(
    review_key: str, *, tenant: str, team: str, run_id: str, waiting: dict[str, Any], seconds: float
) -> dict[str, str]:
    """The URL and token an outside system posts its result to, valid a day past the step's own limit."""
    claim = ResumeClaim(
        tenant=tenant,
        team=team,
        run_id=run_id,
        node=str(waiting["node"]),
        iteration=int(waiting["iteration"]),
        interrupt_id=str(waiting["interruptId"]),
        expires_at=int(time.time() + seconds + 86400),
    )
    return {"url": f"/v1/runs/{run_id}/steps/{claim.node}/resume", "token": resume_token(review_key, claim)}


async def resumed(
    db: AsyncEngine, run: dict[str, Any], waiting: dict[str, Any], resume: dict[str, Any], *, source: str
) -> bool:
    """Resumes a step parked on outside work (`source`: event or callback): writes the resume row, clears the wait,
    queues the run and records how it resumed; False when something resumed this pause first, which is recorded as
    ignored."""
    runs = RunStore(EngineTransactions(db))
    _, created = await enqueue_resume(db, str(run["id"]), waiting, resume)
    log = EventLog(db)
    if not created:
        await log.append(
            thread_id=run["id"], team_id=run["team_id"], run_id=run["id"], type_="resume_ignored",
            node=str(waiting["node"]), data={"source": source},
        )  # fmt: skip
        return False
    await runs.unpark(str(run["id"]), str(waiting["node"]), int(waiting["iteration"]))
    await runs.update(str(run["id"]), status="queued", waiting=None)
    await log.append(
        thread_id=run["id"], team_id=run["team_id"], run_id=run["id"], type_=f"resumed_by_{source}",
        node=str(waiting["node"]), data={},
    )  # fmt: skip
    return True


async def wake_parked(db: AsyncEngine, *, name: str, key: str, team_id: str, payload: dict[str, Any]) -> list[str]:
    """Resumes every step of `team_id` parked on event `name` with correlation key `key` (c-525); the runs woken. A
    wait row whose run has moved on is cleared instead."""
    if not key:
        return []
    runs = RunStore(EngineTransactions(db))
    woken: list[str] = []
    for wait in await runs.waits_for(name, key):
        if wait["team_id"] != team_id:
            continue  # the team is the reporting service's token's, never another team's step
        run = await runs.get(str(wait["run_id"])) or {}
        waiting = cast(dict[str, Any], run.get("waiting") or {})
        if run.get("status") != "waiting" or waiting.get("interruptId") != wait["interrupt_id"]:
            await runs.unpark(str(wait["run_id"]), str(wait["node_id"]), int(wait["iteration"]))
            continue
        if await resumed(db, run, waiting, {"event": payload}, source="event"):
            woken.append(str(run["id"]))
    return woken
