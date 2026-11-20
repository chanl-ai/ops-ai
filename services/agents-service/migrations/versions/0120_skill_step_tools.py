"""Each skill step that names its one tool only in its sentence stores that tool in `use`

Revision ID: 0120_skill_step_tools
Revises: 0119_unattributed_side_tables

A step runs only the tool stored in its `use`. Before this revision a step with no `use` whose `do` sentence named
exactly one tool, agent or workflow (`@tool:get_account`) ran that one, worked out each time a version was read. Steps
saved under that reading hold no `use`, so without this fill their tool stops being the step's tool, and a write tool
the step guarded becomes callable outside the skill.

The rule is frozen here, apart from the code that read it: a step that is an object with no `use` (absent or null)
and a string `do` gets `use` = {"kind", "id"} of the one reference to a tool, agent or workflow among the distinct
`@kind:id` tokens in its `do` (the token pattern of ops_contracts.skill_run REF_TOKEN). A step naming none or more
than one, a step that already has `use`, and anything that is not a step are left as they are. So is a step whose
sentence forbids the one tool it names ("Never use @tool:x here": a negating word before the token in the same
sentence): stored as the step's tool it would run what it forbids. Such a step is printed for its builder, and the
publish check then blocks it until they mark the tool or take it out. A rewritten step keeps its keys in order and
gains `use`. Each version written is printed by table, id and version.

Two tables hold steps: registry_skill_versions (`content.steps`, with `digest`, the sha256 of the canonical JSON of
`content`) and registry_agent_versions (`spec.skillPins[].steps`, each pin a copy of a skill version, with `digest` of
`spec`). Every version of both, draft or published, is read in key order BATCH rows at a time and only the rows that
change are written, with the digest worked out as the stores do (store/agent_registry.py digest_of). `tokens` (the
lengths of each step's `do` and check) and `changes` do not depend on `use` and stay. Every tenant's rows are read, so
each table's own policy is set aside, one batch at a time: a batch sets the policy aside, reads and writes its rows,
puts the policy back and ends its transaction (on SQL Server the policy is dropped and made again inside that
transaction). The table is locked for one batch, never for the whole fill, and no other session sees it without its
policy, so the upgrade runs while agents-service serves. A pass over both tables that writes nothing ends the upgrade;
a pass that wrote is followed by another, and the upgrade stops if PASSES of them all wrote. A second run changes
nothing. A version the earlier release saves after the last pass keeps a step with no stored tool: that step runs
nothing, and the publish check and the attach refuse it until its builder marks the tool.

Two other copies of steps are left as they are. A template copy's `base` (template_copies) is the template's body the
next update merges against: given the stored tools, it would differ from a template without them, and the update
would take the template's steps over the team's. A running skill's program in its thread's checkpoint is the one the
skill finishes on.

Rendered as SQL (`alembic --sql`) the revision writes no statement: only a database that ran a build reading a step's
tool from its sentence can hold such a step, no release did, and a database upgraded from generated SQL starts from a
release.

The down path changes nothing: a stored `use` is the tool the earlier reading chose, and the earlier code reads a
stored `use` first. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any, cast

import sqlalchemy as sa
from alembic import op

from ops_service_kit.ids import canonical_json
from ops_store.schema import TENANT_SCOPED, backfill_ddl

revision = "0120_skill_step_tools"
down_revision = "0119_unattributed_side_tables"
branch_labels = None
depends_on = None

CHAIN = "agents"
# Rows read per statement and written per UPDATE; under 5000, where SQL Server escalates row locks to a table lock.
BATCH = 1000
# Passes over both tables before the upgrade gives up on a release that keeps saving steps without their tool.
PASSES = 4
REF_TOKEN = re.compile(
    r"(?<![\w@])@(tool|knowledge|skill|agent|workflow):([A-Za-z0-9](?:[A-Za-z0-9_.-]{0,126}[A-Za-z0-9_])?)"
)
# The references a step runs; a skill or a knowledge base named in the sentence is not one.
RUNS = ("tool", "agent", "workflow")

# A word before the token, in the same sentence, that makes the sentence forbid the tool rather than ask for it.
FORBIDS = re.compile(
    r"\b(never|not|no|without|avoid|avoids|avoiding|don't|dont|cannot|can't|mustn't|shouldn't|won't|isn't|n't)\b[^.!?;]*$",
    re.IGNORECASE,
)

Json = dict[str, Any]
# (the body rewritten, the steps that gained a tool, the steps left for their builder as "step N")
Rewrite = Callable[[Any], tuple[Any, list[str], list[str]]]


def _versions(name: str, parent_key: str, body: str) -> sa.Table:
    """A version table as far as the fill and its policy need, as of this revision."""
    return sa.Table(
        name,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column(parent_key, sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column(body, sa.JSON),
        sa.Column("digest", sa.String(64)),
        info=TENANT_SCOPED,
    )


SKILL_VERSIONS = _versions("registry_skill_versions", "skill_id", "content")
AGENT_VERSIONS = _versions("registry_agent_versions", "agent_id", "spec")


def _object(value: Any) -> Json | None:
    return cast(Json, value) if isinstance(value, dict) else None


def _list(value: Any) -> list[Any] | None:
    return cast(list[Any], value) if isinstance(value, list) else None


def _use(step: Json) -> tuple[Json | None, bool]:
    """The `use` to store on `step` (None when it is left as it is), and whether it is left because its sentence
    forbids the one tool it names."""
    do = step.get("do")
    if step.get("use") is not None or not isinstance(do, str):
        return None, False
    named: dict[str, tuple[str, str, int]] = {}
    for m in REF_TOKEN.finditer(do):
        named.setdefault(m.group(0), (m.group(1), m.group(2), m.start()))
    runs = [ref for ref in named.values() if ref[0] in RUNS]
    if len(runs) != 1:
        return None, False
    kind, ref_id, at = runs[0]
    if FORBIDS.search(do[:at]):
        return None, True
    return {"kind": kind, "id": ref_id}, False


def _with_tools(holder: Any) -> tuple[Any, list[str], list[str]]:
    """`holder` (a skill version's content, or one pin) with each step's tool stored, the steps that gained one and
    the steps left for their builder. Anything that is not an object, a `steps` that is not a list and a step that is
    not an object stay as they are."""
    held = _object(holder)
    steps = _list(held.get("steps")) if held is not None else None
    if held is None or steps is None:
        return holder, [], []
    out: list[Any] = []
    gained: list[str] = []
    left: list[str] = []
    for n, step in enumerate(steps, start=1):
        each = _object(step)
        use, forbidden = _use(each) if each is not None else (None, False)
        if forbidden:
            left.append(f"step {n}")
        if each is None or use is None:
            out.append(step)
        else:
            out.append({**each, "use": use})
            gained.append(f"{n}")
    return ({**held, "steps": out} if gained else holder), gained, left


def _pins_with_tools(spec: Any) -> tuple[Any, list[str], list[str]]:
    """An agent version's spec with each step of each skill pin's tool stored; steps are named with their skill."""
    held = _object(spec)
    pins = _list(held.get("skillPins")) if held is not None else None
    if held is None or pins is None:
        return spec, [], []
    out: list[Any] = []
    gained: list[str] = []
    left: list[str] = []
    for pin in pins:
        rewritten, got, kept = _with_tools(pin)
        skill = str((_object(pin) or {}).get("skillId") or "")
        out.append(rewritten)
        gained += [f"{skill}:{n}" for n in got]
        left += [f"{skill} {n}" for n in kept]
    return ({**held, "skillPins": out} if gained else spec), gained, left


def _digest(body: Any) -> str:
    """As the stores digest a spec or content (store/agent_registry.py digest_of)."""
    return hashlib.sha256(canonical_json(body).encode()).hexdigest()


def _page(t: sa.Table, body: str, last: tuple[str, int] | None) -> list[tuple[str, int, Any]]:
    """The next BATCH rows after `last` as (parent id, version, body), in key order. SQL Server compares no row
    values, so the key after the last one read is spelled out."""
    parent, version = t.c[t.primary_key.columns.keys()[0]], t.c.version
    q = sa.select(parent, version, t.c[body]).order_by(parent, version).limit(BATCH)
    if last is not None:
        q = q.where(sa.or_(parent > last[0], sa.and_(parent == last[0], version > last[1])))
    return [(str(r[0]), int(r[1]), r[2]) for r in op.get_bind().execute(q).all()]


def _commit() -> None:
    """Ends the transaction a batch ran in and opens the next one: alembic's autocommit block commits on the way in
    and begins again on the way out."""
    with op.get_context().autocommit_block():
        pass


def _fill(t: sa.Table, body: str, rewrite: Rewrite, dialect: str, *, first: bool) -> tuple[int, int]:
    """One pass over `t`, storing the tools of every version that needs one; (versions written, steps that gained a
    tool). Each batch is its own transaction: the table's policy is set aside, BATCH rows are read and the changed
    ones written, the policy is put back, and the transaction ends, so the table is locked for one batch at a time
    and no other session ever sees it without its policy. The first pass prints each step it leaves for its
    builder; every pass prints each version it writes."""
    parent = t.primary_key.columns.keys()[0]
    keyed = sa.and_(t.c[parent] == sa.bindparam("k_parent"), t.c.version == sa.bindparam("k_version"))
    update = t.update().where(keyed).values({body: sa.bindparam(body), "digest": sa.bindparam("digest")})
    before, after = backfill_ddl([t], dialect, chain=CHAIN, kind="tenant")
    versions = steps = 0
    last: tuple[str, int] | None = None
    while True:
        for statement in before:
            op.execute(statement)
        rows = _page(t, body, last)
        changed: list[Json] = []
        for key, number, held in rows:
            rewritten, gained, left = rewrite(held)
            for step in left if first else ():
                print(f"0120_skill_step_tools: left for its builder: {t.name} {key} v{number} {step}")
            if gained:
                changed.append({"k_parent": key, "k_version": number, body: rewritten, "digest": _digest(rewritten)})
                steps += len(gained)
                print(f"0120_skill_step_tools: {t.name} {key} v{number}: steps {', '.join(gained)}")
        if changed:
            op.get_bind().execute(update, changed)
            versions += len(changed)
        for statement in after:
            op.execute(statement)
        _commit()
        if len(rows) < BATCH:
            return versions, steps
        last = (rows[-1][0], rows[-1][1])


def upgrade() -> None:
    if op.get_context().as_sql:
        return
    dialect = op.get_bind().dialect.name
    tables = ((SKILL_VERSIONS, "content", _with_tools), (AGENT_VERSIONS, "spec", _pins_with_tools))
    versions = {t.name: 0 for t, _, _ in tables}
    steps = 0
    # A pass that writes nothing is the proof that no stored step is left. A release still running may save a step
    # behind a pass, so a pass that wrote is followed by another, up to PASSES.
    for n in range(PASSES):
        wrote = 0
        for t, body, rewrite in tables:
            v, s = _fill(t, body, rewrite, dialect, first=n == 0)
            versions[t.name] += v
            steps += s
            wrote += v
        if not wrote:
            break
    else:
        raise RuntimeError(
            f"0120: versions were still being saved without their step tools after {PASSES} passes; stop the release "
            "that reads a step's tool from its sentence and run the upgrade again"
        )
    print(
        f"0120_skill_step_tools: stored the tool of {steps} steps in {versions[SKILL_VERSIONS.name]} skill versions "
        f"and {versions[AGENT_VERSIONS.name]} agent versions; a last pass found none left"
    )


def downgrade() -> None:
    # Nothing to undo: the code before this revision reads a step's stored `use` before its sentence. Rendered as SQL
    # it writes nothing, as the upgrade does.
    if not op.get_context().as_sql:
        print("0120_skill_step_tools: each stored step keeps its `use`")
