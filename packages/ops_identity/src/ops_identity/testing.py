"""For tests that mint platform tokens themselves.

A test module often mints its people's tokens once, at import, and the suite then runs for longer than a short
lifetime: every request after the deadline is a 401 that says nothing about the code under test. Person and service
tokens minted for tests live this long instead. A test about expiry passes its own short `ttl_s` and `now`.
"""

from __future__ import annotations

TEST_TOKEN_TTL_S = 3600
