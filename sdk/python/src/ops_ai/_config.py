"""Where the client connects and as whom: arguments first, then OPS_* environment variables, then a saved profile. The
profile file is `~/.config/ops-ai/config.json`, or $OPS_CONFIG; nothing writes it for you yet."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def config_path() -> Path:
    if os.environ.get("OPS_CONFIG"):
        return Path(os.environ["OPS_CONFIG"])
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "ops-ai" / "config.json"


def _profile(name: str | None) -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    saved = json.loads(path.read_text())
    profiles: dict[str, Any] = saved.get("profiles") or {}
    return profiles.get(name or saved.get("current") or "default") or {}


@dataclass
class Config:
    base_url: str
    api_key: str | None = None
    # A person's session token (`OpsAI.sign_in`, OPS_TOKEN, or the profile's accessToken), sent as a Bearer token. When
    # one is given it is who the call acts as, ahead of an API key: some changes (editing a workflow) are a person's.
    access_token: str | None = None
    team: str | None = None
    # A service reached at its own address instead of through the origin, e.g. {"agents": "http://localhost:8700"}.
    services: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0
    max_retries: int = 2

    @classmethod
    def resolve(
        cls,
        *,
        api_key: str | None = None,
        access_token: str | None = None,
        base_url: str | None = None,
        team: str | None = None,
        profile: str | None = None,
        services: dict[str, str] | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> Config:
        saved = _profile(profile or os.environ.get("OPS_PROFILE"))
        url = base_url or os.environ.get("OPS_BASE_URL") or saved.get("baseUrl")
        if not url:
            raise ValueError("No Ops AI address: pass base_url, set OPS_BASE_URL, or save one in the profile file")
        token = access_token if access_token is not None else (os.environ.get("OPS_TOKEN") or saved.get("accessToken"))
        chosen_team = team if team is not None else (os.environ.get("OPS_TEAM") or saved.get("team"))
        return cls(
            base_url=url,
            api_key=api_key or os.environ.get("OPS_API_KEY") or saved.get("apiKey"),
            access_token=token or None,
            team=chosen_team or None,
            services={**(saved.get("services") or {}), **(services or {})},
            timeout=timeout if timeout is not None else 30.0,
            max_retries=max_retries if max_retries is not None else 2,
        )
