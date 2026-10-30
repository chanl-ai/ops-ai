"""Reads the staging Fly app names from $OPS_STAGING_CONFIG/staging.env (default ~/.config/ops-ai/staging.env), the
same file deploy/fly/stg_env.sh reads, so the repo carries none of them. Template: deploy/fly/staging.env.example."""

from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_PREFIX = "<your-app>"


def load() -> dict[str, str]:
    path = Path(os.environ.get("OPS_STAGING_CONFIG") or Path.home() / ".config" / "ops-ai") / "staging.env"
    if not path.is_file():
        sys.exit(f"staging: {path} not found. Copy deploy/fly/staging.env.example there and fill in the app names.")
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.startswith("STG_"):
            values[key.strip()] = value.strip()
    values = {key: os.environ.get(key) or value for key, value in values.items()}
    values.setdefault("STG_APP_PREFIX", DEFAULT_PREFIX)
    return values


def bank_origin() -> str:
    return f"https://{load()['STG_APP_PREFIX']}-bank.fly.dev"
