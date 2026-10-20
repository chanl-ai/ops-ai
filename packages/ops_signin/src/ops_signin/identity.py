"""What every sign-in protocol hands back, and its one refusal."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerifiedIdentity:
    """A person the identity provider vouched for. `subject` is the provider's stable id for them (OIDC `sub`, SAML
    NameID); `email` is lower-cased; `auth_time` is when they last entered credentials at the provider (Unix
    seconds), None when the provider did not say."""

    subject: str
    email: str
    name: str
    auth_time: int | None = None
    # The groups the provider says the person is in, from the claim or attribute the caller names; empty when none.
    groups: tuple[str, ...] = ()


class SignInRefused(Exception):
    """The provider's answer did not prove who the person is. `reason` is for logs and tests only; callers show one
    message whatever it says, so a caller learns nothing about which check failed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
