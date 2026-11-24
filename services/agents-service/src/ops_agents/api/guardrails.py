"""Guardrails as versioned attachments: the views the console reads, the publish an approval runs, and the
pin check an agent save calls. Store: `store/guardrails.py`.

A guardrail version is immutable, so an agent version snapshots each pinned version's rule (`guardrailPins[]` with
`name`, `kind`, `topics`, `message`, and `scopes` when the version has them) when it is saved; the runtime serves
that snapshot with no lookup per turn.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from pydantic import JsonValue

from ops_service_kit.errors import Conflict, Unprocessable, ValidationFailed
from ops_service_kit.http import Json, JsonList

from ..store.agent_registry import PublishRequestRow
from ..store.guardrails import GuardrailConfig, GuardrailRegistry, GuardrailRow
from ..store.pin_users import PinUsers
from .agent_registry import SEED_TEAM, seed_agent_version
from .agent_registry import registry as agent_registry
from .auth import Principal, review_teams
from .deps import Runtime

KINDS = ("blocked_topics",)


def guardrails(rt: Runtime) -> GuardrailRegistry:
    return GuardrailRegistry(rt.db)


class RuleFields(TypedDict, total=False):
    """The fields of a rule check_config reads, as the create route and the seed name them."""

    topics: list[str]
    message: str
    scopes: dict[str, str]
    holdUntilChecked: bool


def check_config(kind: str, config: Json | RuleFields) -> GuardrailConfig:
    """The rule a version holds, normalised; refused when it could never fire or says nothing to the person."""
    if kind not in KINDS:
        raise ValidationFailed(f"Guardrail kind {kind} is not built yet; kinds: {', '.join(KINDS)}.", code="bad_kind")
    raw: JsonList = list(cast(JsonList, config.get("topics") or []))
    topics = [str(t).strip() for t in raw if str(t).strip()]
    message = str(config.get("message") or "").strip()
    if not topics:
        raise ValidationFailed("Name at least one blocked topic.", code="no_topics")
    if not message:
        raise ValidationFailed("Write the message the person reads when the guardrail refuses.", code="no_message")
    topics = list(dict.fromkeys(topics))
    given = cast(Json, config.get("scopes") or {})
    if not isinstance(given, dict):  # pyright: ignore[reportUnnecessaryIsInstance] - JSON from a request or a seed
        raise ValidationFailed("Scopes map each topic to what it covers.", code="bad_scopes")
    # A scope for a topic the version no longer blocks is dropped; a version with none keeps the shape it had before
    # scopes existed, so its digest does not move.
    scopes = {t: str(given[t]).strip() for t in topics if str(given.get(t) or "").strip()}
    # Hold until checked (off by default: the answer streams and is replaced on a hit). Kept only when on, so a version
    # saved before the setting existed keeps its digest.
    rule: GuardrailConfig = {"topics": topics, "message": message}
    if scopes:
        rule["scopes"] = scopes
    if config.get("holdUntilChecked"):
        rule["holdUntilChecked"] = True
    return rule


async def pinned_by(rt: Runtime, guardrail_id: str) -> list[str]:
    """Agents whose newest or published version pins the guardrail, and published workflows whose agent steps
    carry it."""
    return (await users_of(rt, [guardrail_id]))[guardrail_id]


async def users_of(rt: Runtime, guardrail_ids: list[str]) -> dict[str, list[str]]:
    """`pinned_by` for each of `guardrail_ids`, read once for the lot: every agent's newest and published version in
    one query, and the published workflows once. An agent is named by the first of its versions that pins it."""
    from .skills import workflows_pinning_each  # noqa: PLC0415 - skills imports this module

    wanted = set(guardrail_ids)
    names: dict[str, set[str]] = {g: set() for g in guardrail_ids}
    named: dict[str, set[str]] = {g: set() for g in guardrail_ids}
    for held in await PinUsers(rt.db).held_versions():
        pins = held.spec.get("guardrailPins")
        pinned: set[str] = set()
        for p in pins if isinstance(pins, list) else []:
            if isinstance(p, dict):
                pinned.add(str(p.get("guardrailId")))
        for gid in pinned & wanted:
            if held.agent_id not in named[gid]:
                named[gid].add(held.agent_id)
                names[gid].add(str(held.spec["name"]))
    by_workflow = await workflows_pinning_each(rt, "guardrails", "guardrail_id")
    return {g: sorted(names[g] | by_workflow.get(g, set())) for g in guardrail_ids}


class VersionView(TypedDict):
    version: int
    config: dict[str, JsonValue]
    state: str
    note: str
    savedBy: str
    savedAt: str
    publishedAt: str | None
    publishedBy: str | None


class GuardrailView(TypedDict):
    id: str
    slug: str
    name: str
    kind: str
    owner: str
    status: str
    version: int
    publishedVersion: int | None
    config: dict[str, JsonValue]
    usedBy: list[str]
    pendingRequestId: str | None
    versions: list[VersionView]
    updatedAt: str


async def view(rt: Runtime, guardrail_id: str) -> GuardrailView:
    return (await views(rt, [await guardrails(rt).row(guardrail_id)]))[0]


async def views(rt: Runtime, rows: list[GuardrailRow]) -> list[GuardrailView]:
    """The console's view of each guardrail row, in order, with a fixed number of reads however many rows there are:
    the versions, pending requests and users of the lot are each read once."""
    ids = [r.id for r in rows]
    versions = await guardrails(rt).versions_of(ids)
    pending = await PinUsers(rt.db).pending("guardrail", ids)
    used = await users_of(rt, ids)
    out: list[GuardrailView] = []
    for row in rows:
        gid = row.id
        by_n = {v.version: v for v in versions[gid]}
        published = by_n.get(row.published_version) if row.published_version is not None else None
        current = published or by_n[row.version]
        asked = pending.get(gid)
        out.append(
            {
                "id": gid,
                "slug": row.slug,
                "name": row.name,
                "kind": row.kind,
                "owner": row.owner,
                "status": row.status,
                "version": row.version,
                "publishedVersion": row.published_version,
                "config": current.config,
                "usedBy": used[gid],
                "pendingRequestId": asked.id if asked else None,
                "versions": [
                    {
                        "version": v.version,
                        "config": v.config,
                        "state": "published" if v.published_at else "draft",
                        "note": v.note,
                        "savedBy": v.saved_by,
                        "savedAt": v.saved_at,
                        "publishedAt": v.published_at,
                        "publishedBy": v.published_by,
                    }
                    for v in versions[gid]
                ],
                "updatedAt": row.updated_at,
            }
        )
    return out


async def publish(rt: Runtime, req: PublishRequestRow, by: str) -> None:
    await guardrails(rt).publish(req.subject_id, int(req.version), by=by, review_id=req.id)


async def decide(  # noqa: PLR0917 - the route passes each part of the decision
    rt: Runtime,
    approver: Principal,
    guardrail_id: str,
    request_id: str,
    decision: str,
    reason: str | None,
) -> None:
    """A guardrail publish is decided by a reviewer or admin of the guardrail's team, and not by who asked or
    saved the version unless they hold Approvals decide in that team, as an agent's is."""
    from .publish_reviews import require_not_asker, require_publish_reviewer  # noqa: PLC0415 - imports this module

    reg = agent_registry(rt)
    req = await reg.request(request_id)
    await require_publish_reviewer(rt, req, review_teams(approver))
    if req.kind != "guardrail" or req.subject_id != guardrail_id:
        raise Unprocessable(f"{request_id} is not a publish request for {guardrail_id}.")
    if decision not in ("approved", "rejected"):
        raise ValidationFailed(f"Unknown decision {decision}.")
    if req.status != "pending":
        raise Conflict(f"{request_id} was already {req.status}.", code="already_decided")
    await require_not_asker(rt, req, approver)
    reason = (reason or "").strip() or None
    if decision == "rejected" and reason is None:
        raise ValidationFailed("A reason is required to reject.", code="reason_required")
    if not await reg.decide_request(request_id, decision, approver.email, reason):
        raise Conflict(f"{request_id} was decided by someone else first.", code="already_decided")
    if decision == "approved":
        await publish(rt, req, approver.email)


class GuardrailSeed(TypedDict):
    """One guardrail in guardrails.json: its row, its rule (read by check_config) and the agents it is pinned on."""

    id: str
    name: str
    kind: str
    owner: str
    topics: NotRequired[list[str]]
    message: NotRequired[str]
    scopes: NotRequired[dict[str, str]]
    holdUntilChecked: NotRequired[bool]
    pinnedBy: NotRequired[list[str]]


async def load_seed(rt: Runtime, path: Path) -> None:
    """Seeds each guardrail in `path` that has no row yet, published at v1, and pins it on the agents it names
    (`seed_agent_version`: published in dev, reviewed elsewhere, never over a person's draft). An existing guardrail
    is left as it is, so an unpin or a later version made in the console survives a restart."""
    if not path.is_file():  # noqa: ASYNC240
        return
    reg = guardrails(rt)
    seeds = cast(list[GuardrailSeed], json.loads(path.read_text()))  # noqa: ASYNC240
    for g in seeds:
        if await reg.find(g["id"]) is not None:
            continue
        config = check_config(g["kind"], g)
        await reg.create(
            name=g["name"],
            kind=g["kind"],
            config=config,
            owner=g["owner"],
            team_id=SEED_TEAM,
            by="seed",
            guardrail_id=g["id"],
            published=True,
        )
        for aid in g.get("pinnedBy") or []:

            async def add_pin(spec: Json, gid: str = g["id"]) -> Json:
                held = list(cast(list[Json], spec.get("guardrailPins") or []))
                pins = [p for p in held if p.get("guardrailId") != gid]
                spec["guardrailPins"] = await resolve_pins(rt, [*pins, {"guardrailId": gid, "version": 1}], pins)
                return spec

            await seed_agent_version(rt, aid, add_pin, f"Pinned {g['name']} v1")


def seed_path(seed_dir: Path, agents_seed_file: Path | None) -> Path:
    """guardrails.json beside the agents seed: the demo's seed/ holds the demo guardrail, test fixtures hold none."""
    return (agents_seed_file.parent if agents_seed_file else seed_dir) / "guardrails.json"


async def resolve_pins(rt: Runtime, pins: Sequence[Json], held: Sequence[Json]) -> JsonList:
    """The pins to save, each with its version's rule snapshotted. A new pin must name a published version of a live
    guardrail; a pin the agent already holds is kept as it was while its guardrail is deprecated (no new pins only)."""
    reg = guardrails(rt)
    kept = {(p["guardrailId"], int(cast(int | float | str, p["version"]))): p for p in held if p.get("guardrailId")}
    out: JsonList = []
    ids: list[str] = []
    for pin in pins:
        gid, n = str(pin.get("guardrailId") or ""), int(cast(int | float | str, pin.get("version") or 0))
        # The builder's on/off switch; a pin that names none stays on.
        enabled = bool(pin.get("enabled", True))
        if (gid, n) in kept:
            out.append({**kept[(gid, n)], "enabled": enabled})
            ids.append(gid)
            continue
        row = await reg.find(gid)
        if row is None:
            raise Unprocessable(f"Guardrail {gid} does not exist.", code="unknown_guardrail")
        if row.status == "deprecated":
            raise Unprocessable(f"{row.name} is deprecated and takes no new pins.", code="guardrail_deprecated")
        # A new pin that names no version (the picker's choice) takes the published one.
        n = n or row.published_version or 0
        v = await reg.version(gid, n)
        if v is None or v.published_at is None:
            raise Unprocessable(
                f"{row.name} v{n} is not published; only published versions can be pinned.", code="not_published"
            )
        rule: dict[str, JsonValue] = {"guardrailId": gid, "version": n, "name": row.name, "kind": row.kind, **v.config}
        out.append({**rule, "enabled": enabled})
        ids.append(gid)
    if len(set(ids)) != len(out):
        raise Unprocessable("A guardrail can be pinned once per agent.", code="duplicate_pin")
    return out
