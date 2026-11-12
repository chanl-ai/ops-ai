"""platform-service as the OAuth 2.1 authorization server for a team's MCP address.

An assistant (Claude, Cursor, VS Code, ChatGPT) finds this server from the 401 at `/mcp/<team>`, registers itself,
sends the person's browser to the console's consent page, and exchanges the code it gets back for a 15-minute token
whose audience is that one address. The grant behind it is a `sessions` row of kind `mcp` (store/identity.py); nothing
else issues, stores or checks these tokens: tools-service verifies through ops_identity only.
"""

from __future__ import annotations

from datetime import UTC, datetime


def iso(t: datetime | None = None) -> str:
    """The format every stored time here has, so strings compare in time order."""
    return (t or datetime.now(UTC)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class OAuthError(Exception):
    """An answer in the shape OAuth clients read: `error` is the standard word, `error_description` is for a person.
    Descriptions never contain the word "code" for a refusal that must not look like it carried one."""

    def __init__(
        self, error: str, description: str, *, status: int = 400, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(description)
        self.error, self.description, self.status = error, description, status
        self.headers = headers or {}
