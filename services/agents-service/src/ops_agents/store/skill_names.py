"""Skill names as their newest version gives them, for many skills in one query rather than one version read per
skill: the assurance page names every suite this way. The tables are store/skills.py's."""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa
from pydantic import BaseModel

from ops_store import Guarantee
from ops_store.dialect import json_text
from ops_store.rows import rows
from ops_store.team_scope import team_visible

from .graphs import mine
from .skills import registry_skill_versions, registry_skills
from .tenancy import RuntimeStore


class _Named(BaseModel):
    id: str
    slug: str
    name: str | None


class SkillNames(RuntimeStore):
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    async def newest(self) -> dict[str, str]:
        """Each skill the acting team sees, to its newest version's name, else its slug. No list of ids is sent, so a
        team with many skills stays under SQL Server's parameter limit. The tenant and team are named in the query as
        well as by the row policies."""
        s, v = registry_skills, registry_skill_versions
        q = (
            sa.select(s.c.id, s.c.slug, json_text(v.c.content, "name").label("name"))
            .select_from(s)
            .outerjoin(
                v,
                sa.and_(
                    v.c.skill_id == s.c.id,
                    v.c.version == s.c.version,
                    v.c.tenant_id == s.c.tenant_id,
                    team_visible(v),
                ),
            )
            .where(mine(s), team_visible(s))
        )
        async with self.tx() as c:
            found = await rows(c, q, _Named)
        return {r.id: r.name or r.slug for r in found}
