"""Tool secrets: values stored encrypted (`cipher`), never returned after creation, resolved only inside the
executor at call time, every create, rotate, delete and use audited (`store.secrets`)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from ..store.secrets import SecretStore
from .cipher import Cipher, CipherError, context_of

REFERENCE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
REDACTED = "[secret]"


class SecretMissing(LookupError):
    """A referenced secret the tenant does not have, or one that no longer decrypts. Names only, never values."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(", ".join(names))
        self.names = names


class SecretResolver:
    """Turns `{{NAME}}` references in header values into values, for one call. Values are read and decrypted on
    every call, so a rotation applies to the next one, and each use is audited with the tool that sent it."""

    def __init__(self, store: SecretStore, cipher: Cipher) -> None:
        self.store = store
        self.cipher = cipher

    async def headers(
        self, tenant_id: str, headers: dict[str, str], *, tool: str, actor: str
    ) -> tuple[dict[str, str], list[str]]:
        """The headers with references replaced, and the values used, which the caller scrubs from what it returns."""
        names = sorted({n for v in headers.values() for n in REFERENCE.findall(v)})
        if not names:
            return headers, []
        found = await self.store.use(tenant_id, names, actor=actor, tool=tool, at=datetime.now(UTC))
        missing = [n for n in names if n not in found]
        if missing:
            raise SecretMissing(missing)
        values: dict[str, str] = {}
        for name, (blob, _) in found.items():
            try:
                values[name] = self.cipher.decrypt(blob, context=context_of(tenant_id, name))
            except CipherError as e:
                raise SecretMissing([name]) from e
        resolved = {k: REFERENCE.sub(lambda m: values[m.group(1)], v) for k, v in headers.items()}
        return resolved, list(values.values())


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
