"""An app card's one state and where it stands, shared by the Apps routes and the connectors a person lists."""

from __future__ import annotations

from typing import Literal

# An app card's one state for the caller (the Apps design, "An app's state"): not_installed (the install does not hold
# the plugin and the team never had it on), removed (the team had it on; the install no longer holds it), off
# (installed, not on for the team), needs_auth_config (off, and nothing to sign in through), auth_config_broken (on,
# but its auth config is gone or holds no client secret, and the team has no other), needs_sign_in, connected, and
# test_failed (signed in; its test then failed).
AppState = Literal[
    "connected",
    "test_failed",
    "needs_sign_in",
    "auth_config_broken",
    "needs_auth_config",
    "off",
    "not_installed",
    "removed",
]
# Who acts next, for every list that groups apps (the catalog's views, Mine, the chat picker, the tool list): on (it
# works), needs_you (the caller's own sign-in), needs_admin (someone who manages the team's apps), gone (not installed).
AppGroup = Literal["on", "needs_you", "needs_admin", "gone"]


def app_group(state: str, *, own_sign_in: bool) -> AppGroup:
    """The group of a state; `own_sign_in`: a sign-in it needs is the caller's own, not the team account's."""
    if state in ("connected", "test_failed"):
        return "on"
    if state == "needs_sign_in":
        return "needs_you" if own_sign_in else "needs_admin"
    if state in ("not_installed", "removed"):
        return "gone"
    return "needs_admin"
