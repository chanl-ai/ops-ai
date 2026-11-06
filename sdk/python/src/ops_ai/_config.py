"""Where the client connects and as whom: arguments first, then OPS_* environment variables, then a saved profile. The
profile file is `~/.config/ops-ai/config.json`, or $OPS_CONFIG. A profile holding a person's `accessToken` and
`refreshToken` renews them on a 401, and the renewed pair is written back, since a refresh token works once."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast


def config_path() -> Path:
    if os.environ.get("OPS_CONFIG"):
        return Path(os.environ["OPS_CONFIG"])
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "ops-ai" / "config.json"


def _saved() -> dict[str, Any]:
    path = config_path()
    return cast(dict[str, Any], json.loads(path.read_text())) if path.exists() else {}


def _profile_name(name: str | None) -> str:
    return name or str(_saved().get("current") or "default")


def profile_values(name: str | None) -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    profiles: dict[str, Any] = json.loads(path.read_text()).get("profiles") or {}
    return profiles.get(_profile_name(name)) or {}


def save_profile(name: str, fields: dict[str, Any], *, current: bool = False) -> Path:
    """Sets `fields` on a profile, leaving the rest of the file as it is; `current` makes it the one used by default.
    The file holds tokens, so only its owner reads it (mode 600)."""
    path = config_path()
    saved = _saved()
    profiles = cast(dict[str, Any], saved.setdefault("profiles", {}))
    cast(dict[str, Any], profiles.setdefault(name, {})).update(fields)
    if current:
        saved["current"] = name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved, indent=2))
    path.chmod(0o600)
    return path


def _keep_tokens(name: str) -> Callable[[str, str], None]:
    """Writes a renewed pair into the profile it came from."""

    def keep(access_token: str, refresh_token: str) -> None:
        save_profile(name, {"accessToken": access_token, "refreshToken": refresh_token})

    return keep


@dataclass
class Session:
    """A signed-in person's tokens, shared by every client made from one sign-in (`with_team`): a refresh token works
    once, so the first call that renews it changes it for all of them."""

    access_token: str
    refresh_token: str
    # Called with each renewed pair: a saved profile writes it back.
    on_renew: Callable[[str, str], None] | None = field(default=None, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    async_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


@dataclass
class Config:
    base_url: str
    api_key: str | None = None
    # A person's session token (`OpsAI.sign_in`, OPS_TOKEN, or the profile's accessToken), sent as a Bearer token. When
    # one is given it is who the call acts as, ahead of an API key: some changes (editing a workflow) are a person's.
    access_token: str | None = None
    team: str | None = None
    # A session from `sign_in`: its token is sent instead of `access_token`, and a 401 renews it once and retries,
    # as after a role change (`permissions_changed`) or an expired token.
    session: Session | None = None
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
        session: Session | None = None,
    ) -> Config:
        saved = profile_values(profile or os.environ.get("OPS_PROFILE"))
        url = base_url or os.environ.get("OPS_BASE_URL") or saved.get("baseUrl")
        if not url:
            raise ValueError("No Ops AI address: pass base_url, set OPS_BASE_URL, or save one in the profile file")
        token = access_token if access_token is not None else (os.environ.get("OPS_TOKEN") or saved.get("accessToken"))
        chosen_team = team if team is not None else (os.environ.get("OPS_TEAM") or saved.get("team"))
        from_profile = access_token is None and not os.environ.get("OPS_TOKEN") and bool(saved.get("accessToken"))
        if session is None and from_profile and saved.get("refreshToken"):
            name = _profile_name(profile or os.environ.get("OPS_PROFILE"))
            session = Session(str(token), str(saved["refreshToken"]), on_renew=_keep_tokens(name))
        return cls(
            base_url=url,
            api_key=api_key or os.environ.get("OPS_API_KEY") or saved.get("apiKey"),
            access_token=token or None,
            team=chosen_team or None,
            services={**(saved.get("services") or {}), **(services or {})},
            timeout=timeout if timeout is not None else 30.0,
            max_retries=max_retries if max_retries is not None else 2,
            session=session,
        )
