"""Who started or did something, as `{kind, id, name}`, from the plain strings runs and records keep: a person's email,
`trigger:email:<mailbox>`, `run:<run id>`, `agent:<id>`, `key:<id>`, or `<email> via agent:<id>` for a person asking
through an agent. A page shows the name and never has to look anything up itself: the names are read here, a few
batched queries for a whole page."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from ops_engine import default_registry

from ..store.actor_names import ActorNames
from .deps import Runtime
from .key_summaries import PlatformKeySummaries
from .people_names import PlatformPeopleNames
from .schemas import Out

EMAIL_TRIGGER = "trigger:email:"
# How each kind of start by hand reads, from the trigger types that declare one: {"email": "test email", ...}.
START_VIA = {t.start.kind: t.start.via for t in default_registry().all() if t.start is not None} | {
    # Starts that are no trigger's own (c-535): a members-only hosted form and a row of a batch.
    "hosted_form": "hosted form",
    "batch": "batch",
}
CHILD_RUN = "run:"


class AgentRef(Out):
    # agent: the agent a person asked through; event: the service event that carried a person's request (c-258);
    # start: the start form a person filled by hand, named as its trigger names it ("test email", "form"; c-466).
    kind: Literal["agent", "event", "start"]
    id: str
    name: str


class ActorView(Out):
    # person: someone signed in; trigger: a mailbox or other trigger; run: another workflow's run (`runId`); agent; key:
    # an API key; sender: who sent an email; event: a service event (`<service>/<event>`).
    kind: Literal["person", "trigger", "run", "agent", "key", "sender", "event"]
    id: str
    # A mailbox's, workflow's or agent's name; a person's email until display names are served.
    name: str
    run_id: str | None = None
    # What a person asked through: an agent, or the service event that carried the request.
    via: AgentRef | None = None


@dataclass(frozen=True)
class Parsed:
    kind: str
    id: str
    # What a person asked through, when they did: ("agent", id) or ("event", "<service>/<event>").
    via: tuple[str, str] | None = None


def started_by_of(run: dict[str, Any]) -> str:
    """A run's starter as `actors` reads it: created_by, with the event that carried the request when there is one."""
    via = run.get("started_via")
    return f"{run['created_by']} via {via}" if via else str(run["created_by"])


def event_name(source_and_event: str) -> str:
    """`tools/tool_access.requested` as a reader sees it: tool_access.requested from tools."""
    source, _, event = source_and_event.partition("/")
    return f"{event} from {source}" if event else source


def parse(raw: str) -> Parsed:
    for marker, kind in ((" via agent:", "agent"), (" via event:", "event"), (" via start:", "start")):
        who, found, via = raw.partition(marker)
        if found:
            return Parsed("person", who, (kind, via))
    who = raw
    if who.startswith("event:"):
        return Parsed("event", who[len("event:") :])
    if who.startswith(EMAIL_TRIGGER):
        return Parsed("trigger", who[len(EMAIL_TRIGGER) :])
    if who.startswith("trigger:"):
        return Parsed("trigger", who.split(":", 1)[1])
    for prefix, kind in ((CHILD_RUN, "run"), ("agent:", "agent"), ("key:", "key")):
        if who.startswith(prefix):
            return Parsed(kind, who[len(prefix) :])
    return Parsed("person", who)


async def actors(rt: Runtime, raws: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Each raw string as `{kind, id, name}`, and `runId` for a run started by another run. People and API keys are
    named by platform-service: a person's display name, a key's label. Anything not found keeps its id as its name."""
    parsed = {raw: parse(raw) for raw in set(raws) if raw}
    addresses = {p.id for p in parsed.values() if p.kind == "trigger"}
    run_ids = {p.id for p in parsed.values() if p.kind == "run"}
    agent_ids = {p.id for p in parsed.values() if p.kind == "agent"} | {
        p.via[1] for p in parsed.values() if p.via and p.via[0] == "agent"
    }
    names = await ActorNames(rt.db).names(addresses=addresses, run_ids=run_ids, agent_ids=agent_ids)
    people = getattr(rt, "people_names", None)
    if isinstance(people, PlatformPeopleNames):
        emails = {p.id for p in parsed.values() if p.kind == "person" and "@" in p.id}
        names |= {("person", e): n for e, n in (await people.names(emails)).items()}
    key_ids = {p.id for p in parsed.values() if p.kind == "key"}
    keys = getattr(rt, "key_summaries", None)
    if key_ids and isinstance(keys, PlatformKeySummaries):
        # Revoked keys stay in the list, so a run a retired key started keeps its key's name.
        listed = await keys.list() or []
        names |= {("key", str(k["id"])): str(k["name"]) for k in listed if k["id"] in key_ids}
    out: dict[str, dict[str, Any]] = {}
    for raw, p in parsed.items():
        view: dict[str, Any] = {"kind": p.kind, "id": p.id, "name": names.get((p.kind, p.id), p.id)}
        if p.kind == "run":
            view["runId"] = p.id
        if p.kind == "event":
            view["name"] = event_name(p.id)
        if p.via:
            kind, via_id = p.via
            named = (
                names.get(("agent", via_id), via_id)
                if kind == "agent"
                else START_VIA.get(via_id, via_id)
                if kind == "start"
                else event_name(via_id)
            )
            view["via"] = {"kind": kind, "id": via_id, "name": named}
        out[raw] = view
    return out
