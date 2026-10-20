"""Password hashing: PBKDF2-HMAC-SHA256 from the standard library, a FIPS-approved function, with a random salt per
password and the iteration count stored in the hash, so raising the count later still verifies every stored hash and
`needs_rehash` says which to replace at the next sign-in. The encoded form is `pbkdf2_sha256$<iterations>$<salt>$<key>`
with base64url parts; the password itself is never kept."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

SCHEME = "pbkdf2_sha256"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class PasswordHasher:
    """`iterations` comes from the caller's settings; the library holds no work factor of its own."""

    iterations: int

    def __post_init__(self) -> None:
        if self.iterations < 1:
            raise ValueError("iterations must be positive")

    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, self.iterations)
        return f"{SCHEME}${self.iterations}${_b64(salt)}${_b64(key)}"

    def verify(self, password: str, encoded: str) -> bool:
        """Whether `password` matches `encoded`; a malformed or foreign hash is a mismatch, never an error."""
        parts = encoded.split("$")
        if len(parts) != 4 or parts[0] != SCHEME or not parts[1].isdigit():
            return False
        try:
            salt, want = _unb64(parts[2]), _unb64(parts[3])
        except ValueError:
            return False
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(parts[1]))
        return hmac.compare_digest(got, want)

    def needs_rehash(self, encoded: str) -> bool:
        parts = encoded.split("$")
        return len(parts) != 4 or parts[0] != SCHEME or not parts[1].isdigit() or int(parts[1]) < self.iterations
