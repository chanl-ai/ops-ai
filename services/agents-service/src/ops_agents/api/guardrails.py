"""Guardrails as versioned attachments (c-063): the views the console reads, the publish an approval runs, and the
pin check an agent save calls. Store: `store/guardrails.py`.

A guardrail version is immutable, so an agent version snapshots each pinned version's rule (`guardrailPins[]` with
`name`, `kind`, `topics`, `message`, and `scopes` when the version has them) when it is saved; the runtime serves
that snapshot with no lookup per turn.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ops_service_kit.errors import Conflict, Unprocessable, ValidationFailed

from ..store.guardrails import GuardrailRegistry
from .agent_registry import SEED_TEAM, seed_agent_version
from .agent_registry import registry as agent_registry
from .auth import Principal, review_teams
from .deps import Runtime

KINDS = ("blocked_topics",)


def guardrails(rt: Runtime) -> GuardrailRegistry:
    return GuardrailRegistry(rt.db)


def check_config(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    """The rule a version holds, normalised; refused when it could never fire or says nothing to the person."""
    if kind not in KINDS:
        raise ValidationFailed(f"Guardrail kind {kind} is not built yet; kinds: {', '.join(KINDS)}.", code="bad_kind")
    raw: list[Any] = list(cast(list[Any], config.get("topics") or []))
    topics = [str(t).strip() for t in raw if str(t).strip()]
    message = str(config.get("message") or "").strip()
    if not topics:
        raise ValidationFailed("Name at least one blocked topic.", code="no_topics")
    if not message:
        raise ValidationFailed("Write the message the person reads when the guardrail refuses.", code="no_message")
    topics = list(dict.fromkeys(topics))
    given = cast(dict[str, Any], config.get("scopes") or {})
    if not isinstance(given, dict):  # pyright: ignore[reportUnnecessaryIsInstance] - JSON from a request or a seed
        raise ValidationFailed("Scopes map each topic to what it covers.", code="bad_scopes")
    # A scope for a topic the version no longer blocks is dropped; a version with none keeps the shape it had before
    # scopes existed, so its digest does not move.
    scopes = {t: str(given[t]).strip() for t in topics if str(given.get(t) or "").strip()}
    # Hold until checked (off by default: the answer streams and is replaced on a hit). Kept only when on, so a version
    # saved before the setting existed keeps its digest.
    hold = {"holdUntilChecked": True} if config.get("holdUntilChecked") else {}
    return {"topics": topics, "message": message, **({"scopes": scopes} if scopes else {}), **hold}


async def pinned_by(rt: Runtime, guardrail_id: str) -> list[str]:
    """Agents whose newest or published version pins the guardrail, and published workflows whose agent steps
    carry it."""
    from .skills import workflows_pinning  # noqa: PLC0415 - skills imports this module

    reg = agent_registry(rt)
    names: list[str] = []
    for row in await reg.rows():
        for n in {row["version"], row["published_version"]} - {None}:
            spec = (await reg.version(row["id"], int(n)))["spec"]
            pins: list[dict[str, Any]] = list(spec.get("guardrailPins") or [])
            if any(p.get("guardrailId") == guardrail_id for p in pins):
                names.append(str(spec["name"]))
                break
    names.extend(await workflows_pinning(rt, "guardrails", "guardrail_id", guardrail_id))
    return sorted(set(names))


async def view(rt: Runtime, guardrail_id: str) -> dict[str, Any]:
    reg = guardrails(rt)
    row = await reg.row(guardrail_id)
    versions = await reg.versions(guardrail_id)
    by_n = {v["version"]: v for v in versions}
    current = by_n.get(row["published_version"]) or by_n[row["version"]]
    pending = [r for r in await agent_registry(rt).requests("guardrail", guardrail_id) if r["status"] == "pending"]
    return {
        "id": row["id"],
        "slug": row["slug"],
        "name": row["name"],
        "kind": row["kind"],
        "owner": row["owner"],
        "status": row["status"],
        "version": row["version"],
        "publishedVersion": row["published_version"],
        "config": current["config"],
        "usedBy": await pinned_by(rt, guardrail_id),
        "pendingRequestId": pending[0]["id"] if pending else None,
        "versions": [
            {
                "version": v["version"],
                "config": v["config"],
                "state": "published" if v["published_at"] else "draft",
                "note": v["note"],
                "savedBy": v["saved_by"],
                "savedAt": v["saved_at"],
                "publishedAt": v["published_at"],
                "publishedBy": v["published_by"],
            }
            for v in versions
        ],
        "updatedAt": row["updated_at"],
    }


async def publish(rt: Runtime, req: dict[str, Any], by: str) -> None:
    await guardrails(rt).publish(req["subject_id"], int(req["version"]), by=by, review_id=req["id"])


async def decide(  # noqa: PLR0917 - the route passes each part of the decision
    rt: Runtime,
    approver: Principal,
    guardrail_id: str,
    request_id: str,
    decision: str,
    reason: str | None,
) -> None:
    """A guardrail publish is decided by a reviewer or admin of the guardrail's team (c-122), and not by who asked or
    saved the version while requesterMayDecide is off, as an agent's is."""
    from .publish_reviews import require_not_asker, require_publish_reviewer  # noqa: PLC0415 - imports this module

    reg = agent_registry(rt)
    req = await reg.request(request_id)
    await require_publish_reviewer(rt, req, review_teams(approver))
    if req["kind"] != "guardrail" or req["subject_id"] != guardrail_id:
        raise Unprocessable(f"{request_id} is not a publish request for {guardrail_id}.")
    if decision not in ("approved", "rejected"):
        raise ValidationFailed(f"Unknown decision {decision}.")
    if req["status"] != "pending":
        raise Conflict(f"{request_id} was already {req['status']}.", code="already_decided")
    await require_not_asker(rt, req, approver)
    reason = (reason or "").strip() or None
    if decision == "rejected" and reason is None:
        raise ValidationFailed("A reason is required to reject.", code="reason_required")
    if not await reg.decide_request(request_id, decision, approver.email, reason):
        raise Conflict(f"{request_id} was decided by someone else first.", code="already_decided")
    if decision == "approved":
        await publish(rt, req, approver.email)


async def load_seed(rt: Runtime, path: Path) -> None:
    """Seeds each guardrail in `path` that has no row yet, published at v1, and pins it on the agents it names
    (`seed_agent_version`: published in dev, reviewed elsewhere, never over a person's draft). An existing guardrail
    is left as it is, so an unpin or a later version made in the console survives a restart."""
    if not path.is_file():
        return
    reg = guardrails(rt)
    seeds: list[dict[str, Any]] = json.loads(path.read_text())
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
        for aid in cast(list[str], g.get("pinnedBy") or []):

            async def add_pin(spec: dict[str, Any], gid: str = g["id"]) -> dict[str, Any]:
                held: list[dict[str, Any]] = list(spec.get("guardrailPins") or [])
                pins = [p for p in held if p.get("guardrailId") != gid]
                spec["guardrailPins"] = await resolve_pins(rt, [*pins, {"guardrailId": gid, "version": 1}], pins)
                return spec

            await seed_agent_version(rt, aid, add_pin, f"Pinned {g['name']} v1")


def seed_path(seed_dir: Path, agents_seed_file: Path | None) -> Path:
    """guardrails.json beside the agents seed: the demo's seed/ holds the demo guardrail, test fixtures hold none."""
    return (agents_seed_file.parent if agents_seed_file else seed_dir) / "guardrails.json"


async def resolve_pins(rt: Runtime, pins: list[dict[str, Any]], held: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The pins to save, each with its version's rule snapshotted. A new pin must name a published version of a live
    guardrail; a pin the agent already holds is kept as it was while its guardrail is deprecated (no new pins only)."""
    reg = guardrails(rt)
    kept = {(p["guardrailId"], int(p["version"])): p for p in held if p.get("guardrailId")}
    out: list[dict[str, Any]] = []
    for pin in pins:
        gid, n = str(pin.get("guardrailId") or ""), int(pin.get("version") or 0)
        # The builder's on/off switch; a pin that names none stays on.
        enabled = bool(pin.get("enabled", True))
        if (gid, n) in kept:
            out.append({**kept[(gid, n)], "enabled": enabled})
            continue
        row = await reg.find(gid)
        if row is None:
            raise Unprocessable(f"Guardrail {gid} does not exist.", code="unknown_guardrail")
        if row["status"] == "deprecated":
            raise Unprocessable(f"{row['name']} is deprecated and takes no new pins.", code="guardrail_deprecated")
        # A new pin that names no version (the picker's choice) takes the published one.
        n = n or int(row["published_version"] or 0)
        v = await reg.version(gid, n)
        if v is None or v["published_at"] is None:
            raise Unprocessable(
                f"{row['name']} v{n} is not published; only published versions can be pinned.", code="not_published"
            )
        rule = {"guardrailId": gid, "version": n, "name": row["name"], "kind": row["kind"], **v["config"]}
        out.append({**rule, "enabled": enabled})
    if len({p["guardrailId"] for p in out}) != len(out):
        raise Unprocessable("A guardrail can be pinned once per agent.", code="duplicate_pin")
    return out
