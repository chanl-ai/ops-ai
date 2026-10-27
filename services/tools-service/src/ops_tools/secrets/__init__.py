"""Tool secrets: values stored encrypted (`cipher`), never returned after creation, resolved only inside the
executor at call time, every create, rotate, delete and use audited (`store.secrets`)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from ops_policy import Cipher, CipherError, context_of

from ..store.secrets import SecretStore

NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
REDACTED = "[secret]"


class SecretMissing(LookupError):
    """A referenced secret the team does not have, or one that no longer decrypts. Names only, never values: whether
    another team holds the name is not said."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(", ".join(names))
        self.names = names


class SecretResolver:
    """Turns `{{NAME}}` references into values, for one call. Values are read and decrypted on every call, so a
    rotation applies to the next one, and each use is audited with the tool that sent it."""

    def __init__(self, store: SecretStore, cipher: Cipher) -> None:
        self.store = store
        self.cipher = cipher

    async def lookup(
        self, tenant_id: str, team_id: str | None, names: list[str], *, tool: str, actor: str
    ) -> dict[str, str]:
        """Each named secret's value from `team_id`'s own secrets (the calling module's, mailbox's or connection's
        team), its use audited; SecretMissing names any the team lacks or cannot decrypt. A caller with no team has
        no secrets: every secret belongs to a team (c-509)."""
        if team_id is None:
            raise SecretMissing(names)
        found = await self.store.use(tenant_id, team_id, names, actor=actor, tool=tool, at=datetime.now(UTC))
        missing = [n for n in names if n not in found]
        if missing:
            raise SecretMissing(missing)
        values: dict[str, str] = {}
        for name, (blob, _) in found.items():
            try:
                values[name] = self.cipher.decrypt(blob, context=context_of(tenant_id, name))
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
