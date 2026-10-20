"""Identifiers and canonical hashing shared by the kernel and the API."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any

from ops_policy import canonicalize
from ops_policy import input_hash as policy_input_hash


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    """RFC 8785 canonical JSON (ops_policy): the same bytes for the same input wherever the hash is computed."""
    return canonicalize(value)


def input_hash(value: Any) -> str:
    return policy_input_hash(value)


def action_id(tool_call_key: str) -> str:
    return hashlib.sha256(tool_call_key.encode()).hexdigest()[:16]
