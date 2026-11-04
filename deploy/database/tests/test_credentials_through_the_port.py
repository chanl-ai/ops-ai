"""Every secret value is written and read through the credential store port, so a vault adapter is the
only change needed to keep values outside the database. Two rules over each service's source: nothing seals or opens
a value with the cipher itself, and only the files listed below name a column that holds a credential reference."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[3]

# The columns holding the credential store's reference to a value, by the service that owns them.
COLUMNS = re.compile(r"\b(ciphertext|access_ct|refresh_ct|verifier_ct)\b")
CIPHER = re.compile(r"\.(encrypt|decrypt)\(|\bAesGcmCipher\(")

# Each file that may name a credential column, and why: the store that keeps the row, or the one caller that puts and
# reads that value through the port.
MAY_NAME = {
    "services/tools-service/src/ops_tools/store/secrets.py": "keeps tool_secrets",
    "services/tools-service/src/ops_tools/store/connections.py": "keeps connection_tokens and oauth_states",
    "services/tools-service/src/ops_tools/auth/tokens.py": "puts and reads tokens and person sign-ins",
    "services/tools-service/src/ops_tools/connections/service.py": "puts and reads a sign-in's verifier",
    "services/tools-service/src/ops_tools/connections/records.py": "asks if a refresh token is held, never reads it",
    "services/models-service/src/ops_models/store/tables.py": "defines provider_keys",
    "services/models-service/src/ops_models/store/provider_keys.py": "keeps provider_keys, through the port",
}
SOURCES = ["services/tools-service/src", "services/models-service/src"]


def _files() -> list[Path]:
    return sorted(p for src in SOURCES for p in (ROOT / src).rglob("*.py"))


def test_nothing_seals_or_opens_a_value_but_the_port() -> None:
    found = [
        f"{p.relative_to(ROOT)}:{n}"
        for p in _files()
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if CIPHER.search(line) and not line.lstrip().startswith("#")
    ]
    assert not found, f"seal and open values through ops_policy.CredentialStore, not the cipher: {found}"


def test_only_the_listed_files_name_a_credential_column() -> None:
    found = [
        f"{p.relative_to(ROOT)}:{n}"
        for p in _files()
        if str(p.relative_to(ROOT)) not in MAY_NAME
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if COLUMNS.search(line)
    ]
    assert not found, f"a credential column is named outside its store and the port's callers: {found}"
