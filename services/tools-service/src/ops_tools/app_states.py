"""An app card's one state, shared by the Apps routes and the connectors a person lists."""

from __future__ import annotations

from typing import Literal

# An app card's one state for the caller (the Apps design, "An app's state"): not_installed (the install does not hold
# the plugin and the team never had it on), removed (the team had it on; the install no longer holds it), off
# (installed, not on for the team), needs_auth_config (nothing to sign in with: no auth config, or the account's has
# gone or holds no client secret), needs_sign_in, connected, and test_failed (signed in; its test then failed).
AppState = Literal["connected", "test_failed", "needs_sign_in", "needs_auth_config", "off", "not_installed", "removed"]
