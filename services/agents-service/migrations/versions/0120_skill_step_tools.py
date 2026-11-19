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
than one, a step that already has `use`, and anything that is not a step are left as they are. A rewritten step keeps
its keys in order and gains `use`.

Two tables hold steps: registry_skill_versions (`content.steps`, with `digest`, the sha256 of the canonical JSON of
`content`) and registry_agent_versions (`spec.skillPins[].steps`, each pin a copy of a skill version, with `digest` of
`spec`). Every version of both, draft or published, is read in key order BATCH rows at a time and only the rows that
change are written, with the digest worked out as the stores do (store/agent_registry.py digest_of). `tokens` (the
lengths of each step's `do` and check) and `changes` do not depend on `use` and stay. Every tenant's rows are read, so
both tables' own policies are set aside inside the migration's transaction (on SQL Server each is dropped and made
again before that transaction ends). Before they are put back every row is read again, and the upgrade stops if any
step would still change. A second run changes nothing. Stop agents-service before upgrading (docs/deploy/database.md).

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
from collections.abc import Callable, Iterator
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
REF_TOKEN = re.compile(
    r"(?<![\w@])@(tool|knowledge|skill|agent|workflow):([A-Za-z0-9](?:[A-Za-z0-9_.-]{0,126}[A-Za-z0-9_])?)"
)
# The references a step runs; a skill or a knowledge base named in the sentence is not one.
RUNS = ("tool", "agent", "workflow")

Json = dict[str, Any]
Rewrite = Callable[[Any], tuple[Any, int]]


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


def _use(step: Json) -> Json | None:
    """The `use` to store on `step`, or None when it is left as it is."""
    do = step.get("do")
    if step.get("use") is not None or not isinstance(do, str):
        return None
    named: dict[str, tuple[str, str]] = {}
    for m in REF_TOKEN.finditer(do):
        named.setdefault(m.group(0), (m.group(1), m.group(2)))
    runs = [ref for ref in named.values() if ref[0] in RUNS]
    if len(runs) != 1:
        return None
    kind, ref_id = runs[0]
    return {"kind": kind, "id": ref_id}


def _with_tools(holder: Any) -> tuple[Any, int]:
    """`holder` (a skill version's content, or one pin) with each step's tool stored, and how many steps gained one.
    Anything that is not an object, a `steps` that is not a list and a step that is not an object stay as they are."""
    held = _object(holder)
    steps = _list(held.get("steps")) if held is not None else None
    if held is None or steps is None:
        return holder, 0
    out: list[Any] = []
    gained = 0
    for step in steps:
        each = _object(step)
        use = _use(each) if each is not None else None
        if each is None or use is None:
            out.append(step)
        else:
            out.append({**each, "use": use})
            gained += 1
    return ({**held, "steps": out}, gained) if gained else (holder, 0)


def _pins_with_tools(spec: Any) -> tuple[Any, int]:
    """An agent version's spec with each step of each skill pin's tool stored."""
    held = _object(spec)
    pins = _list(held.get("skillPins")) if held is not None else None
    if held is None or pins is None:
        return spec, 0
    out: list[Any] = []
    gained = 0
    for pin in pins:
        rewritten, n = _with_tools(pin)
        out.append(rewritten)
        gained += n
    return ({**held, "skillPins": out}, gained) if gained else (spec, 0)


def _digest(body: Any) -> str:
    """As the stores digest a spec or content (store/agent_registry.py digest_of)."""
    return hashlib.sha256(canonical_json(body).encode()).hexdigest()


def _pages(t: sa.Table, body: str) -> Iterator[list[tuple[str, int, Any]]]:
    """Every row's (parent id, version, body), BATCH at a time in key order. SQL Server compares no row values, so the
    key after the last one read is spelled out."""
    bind = op.get_bind()
    parent, version = t.c[t.primary_key.columns.keys()[0]], t.c.version
    last: tuple[str, int] | None = None
    while True:
        q = sa.select(parent, version, t.c[body]).order_by(parent, version).limit(BATCH)
        if last is not None:
            q = q.where(sa.or_(parent > last[0], sa.and_(parent == last[0], version > last[1])))
        rows = [(str(r[0]), int(r[1]), r[2]) for r in bind.execute(q).all()]
        if not rows:
            return
        yield rows
        last = (rows[-1][0], rows[-1][1])


def _fill(t: sa.Table, body: str, rewrite: Rewrite) -> tuple[int, int]:
    """Stores the tools of every version of `t` that needs one; (versions written, steps that gained a tool)."""
    parent = t.primary_key.columns.keys()[0]
    keyed = sa.and_(t.c[parent] == sa.bindparam("k_parent"), t.c.version == sa.bindparam("k_version"))
    update = t.update().where(keyed).values({body: sa.bindparam(body), "digest": sa.bindparam("digest")})
    versions = steps = 0
    for rows in _pages(t, body):
        changed: list[Json] = []
        for key, number, held in rows:
            rewritten, gained = rewrite(held)
            if gained:
                changed.append({"k_parent": key, "k_version": number, body: rewritten, "digest": _digest(rewritten)})
                steps += gained
        if changed:
            op.get_bind().execute(update, changed)
            versions += len(changed)
    return versions, steps


def _left(t: sa.Table, body: str, rewrite: Rewrite) -> int:
    """How many stored steps of `t` still name exactly one tool, agent or workflow in their sentence and have no
    `use`."""
    return sum(rewrite(held)[1] for rows in _pages(t, body) for _key, _number, held in rows)


def upgrade() -> None:
    if op.get_context().as_sql:
        return
    dialect = op.get_bind().dialect.name
    tables = ((SKILL_VERSIONS, "content", _with_tools), (AGENT_VERSIONS, "spec", _pins_with_tools))
    # Every tenant's versions are filled, so each table's own policy is set aside, only ever inside a transaction.
    before, after = backfill_ddl([t for t, _, _ in tables], dialect, chain=CHAIN, kind="tenant")
    for statement in before:
        op.execute(statement)
    (skills, skill_steps), (agents, pin_steps) = [_fill(t, body, rewrite) for t, body, rewrite in tables]
    left = sum(_left(t, body, rewrite) for t, body, rewrite in tables)
    if left:
        raise RuntimeError(f"0120: {left} stored skill steps still name their one tool only in their sentence")
    for statement in after:
        op.execute(statement)
    print(
        f"0120_skill_step_tools: stored the tool of {skill_steps + pin_steps} steps in {skills} skill versions and "
        f"{agents} agent versions; 0 steps left naming their one tool only in their sentence"
    )


def downgrade() -> None:
    # Nothing to undo: the code before this revision reads a step's stored `use` before its sentence. Rendered as SQL
    # it writes nothing, as the upgrade does.
    if not op.get_context().as_sql:
        print("0120_skill_step_tools: each stored step keeps its `use`")
