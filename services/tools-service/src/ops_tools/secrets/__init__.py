"""Tool secrets: values kept in the credential store (`ops_policy.credentials`), never returned after creation,
resolved only inside the executor at call time, every create, rotate, delete and use audited (`store.secrets`). Every
value is written and read here, through the port; the store keeps only each value's reference."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from ops_policy import CipherError, CredentialStore, context_of

from ..store.secrets import SecretStore

NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
REDACTED = "[secret]"


class SecretMissing(LookupError):
    """A referenced secret the team does not have, or one that no longer decrypts. Names only, never values: whether
    another team holds the name is not said."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(", ".join(names))
        self.names = names


# A value this short or shorter keeps no ending: four of its characters would give too much of it away.
SHORTEST_WITH_ENDING = 8


def ending(value: str) -> str | None:
    """The last four characters of a secret value, shown so a person can tell which value is held."""
    return value[-4:] if len(value) >= SHORTEST_WITH_ENDING else None


class SecretResolver:
    """Turns `{{NAME}}` references into values, for one call, and sets, rotates and deletes them. Values are read on
    every call, so a rotation applies to the next one, and each use is audited with the tool that sent it."""

    def __init__(self, store: SecretStore, credentials: CredentialStore) -> None:
        self.store = store
        self.credentials = credentials

    async def create(
        self,
        tenant_id: str,
        team_id: str,
        name: str,
        value: str,
        *,
        actor: str,
        at: datetime,
        template: dict[str, str] | None = None,
        connection_id: str | None = None,
        credential_id: str | None = None,
    ) -> bool:
        """False when the team already has the name: nothing is written, and the value put for it is dropped."""
        context = context_of(tenant_id, name)
        ref = await self.credentials.put(value, context=context)
        made = await self.store.create(
            tenant_id,
            team_id,
            name,
            ref,
            actor=actor,
            at=at,
            ends=ending(value),
            template=template,
            connection_id=connection_id,
            credential_id=credential_id,
        )
        if not made:
            await self.credentials.delete(ref, context=context)
        return made

    async def ends_of(self, tenant_id: str, team_id: str, name: str) -> str | None:
        """A secret's last four characters. One kept before they were stored is read once and they are kept, so a
        person can still tell which value it holds."""
        ref = await self.store.missing_ends(tenant_id, team_id, name)
        if ref is None:
            return None
        ends = ending(await self.credentials.get(ref, context=context_of(tenant_id, name)))
        if ends is not None:
            await self.store.keep_ends(tenant_id, team_id, name, ref, ends)
        return ends

    async def rotate(
        self, tenant_id: str, team_id: str, name: str, value: str, *, actor: str, at: datetime
    ) -> int | None:
        """The new version, or None when the team has no such secret; the value it replaced is dropped."""
        context = context_of(tenant_id, name)
        ref = await self.credentials.put(value, context=context)
        rotated = await self.store.rotate(tenant_id, team_id, name, ref, actor=actor, at=at, ends=ending(value))
        if rotated is None:
            await self.credentials.delete(ref, context=context)
            return None
        version, old = rotated
        await self.credentials.delete(old, context=context)
        return version

    async def rename(
        self, tenant_id: str, team_id: str, name: str, to: str, *, actor: str, at: datetime
    ) -> bool | None:
        """Renames the team's secret, its value kept: a value is sealed under its name (`context_of`), so it is opened
        under the old name and sealed again under the new before the row moves. None when the team has no such secret
        (or it was replaced meanwhile), False when the new name is taken; either way nothing changes."""
        was = await self.store.ref(tenant_id, team_id, name)
        if was is None:
            return None
        value = await self.credentials.get(was, context=context_of(tenant_id, name))
        ref = await self.credentials.put(value, context=context_of(tenant_id, to))
        moved = await self.store.rename(tenant_id, team_id, name, to, ref, was=was, actor=actor, at=at)
        if not moved:
            await self.credentials.delete(ref, context=context_of(tenant_id, to))
            return moved
        await self.credentials.delete(was, context=context_of(tenant_id, name))
        return True

    async def delete(self, tenant_id: str, team_id: str, name: str, *, actor: str, at: datetime) -> bool:
        old = await self.store.delete(tenant_id, team_id, name, actor=actor, at=at)
        if old is None:
            return False
        await self.credentials.delete(old, context=context_of(tenant_id, name))
        return True

    async def present(
        self, tenant_id: str, team_id: str, names: list[str], *, tool: str, actor: str, at: datetime
    ) -> dict[str, str]:
        """The values of the named secrets the team holds, each use audited; one it lacks or that no longer opens is
        left out, for a caller that treats a missing part as not set (a connection's client secret)."""
        found = await self.store.use(tenant_id, team_id, names, actor=actor, tool=tool, at=at)
        values: dict[str, str] = {}
        for name, (ref, _) in found.items():
            try:
                values[name] = await self.credentials.get(ref, context=context_of(tenant_id, name))
            except CipherError:
                continue
        return values

    async def lookup(
        self, tenant_id: str, team_id: str | None, names: list[str], *, tool: str, actor: str
    ) -> dict[str, str]:
        """Each named secret's value from `team_id`'s own secrets (the calling module's, mailbox's or connection's
        team), its use audited; SecretMissing names any the team lacks or cannot decrypt. A caller with no team has
        no secrets: every secret belongs to a team."""
        if team_id is None:
            raise SecretMissing(names)
        found = await self.store.use(tenant_id, team_id, names, actor=actor, tool=tool, at=datetime.now(UTC))
        missing = [n for n in names if n not in found]
        if missing:
            raise SecretMissing(missing)
        values: dict[str, str] = {}
        for name, (ref, _) in found.items():
            try:
                values[name] = await self.credentials.get(ref, context=context_of(tenant_id, name))
            except CipherError as e:
                raise SecretMissing([name]) from e
        return values


def scrub(output: Any, values: list[str]) -> Any:
    """`output` with every occurrence of a secret value replaced: an upstream that echoes a request's headers back
    must not carry the value into the response or the call log."""
    if not values:
        return output
    text = json.dumps(output)
    for v in sorted(values, key=len, reverse=True):
        if v:
            text = text.replace(json.dumps(v)[1:-1], REDACTED)
    return json.loads(text)
