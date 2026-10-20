"""Password sign-in, reset and step-up checks: the decisions, with hashes and reset tokens behind `SignInStore`.

A password works only where the person's workspace allows one: a workspace with no sign-in providers does, and one
with providers does only through an enabled password provider. A stored password is a PBKDF2 hash; the demo password
is a fallback for a person with no stored password, and is None outside dev. Hashing runs off the event loop, and a
refusal does the same hashing work as a success, so timing does not tell an unknown email from a wrong password. A
reset link is mailed only to a person who could sign in by password, and the reply to the request is the same whether
or not one went out. Using the link sets the password and ends every session the person had.

Wrong passwords at sign-in and step-up count together per person (c-196): reaching the limit in the window locks the
person for the lockout time, during which even the right password is refused with 429 `signin_locked`. A right
password clears the count, and a used reset link ends a lock. One person is sent at most the limit of reset links per
window; past it the request is answered the same and nothing is sent.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ops_email import MailSender, OutboundMessage
from ops_service_kit.errors import ServiceUnavailable, TooManyRequests, ValidationFailed
from ops_signin import PasswordHasher

from .signin_options import Limits
from .store.identity import IdentityStore, User
from .store.signin import SignInStore

RESET_PREFIX = "prt_"


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def email_key_from(signing_key_text: str) -> bytes:
    """The key wrong-password counts per address are hashed with: derived from the token signing key, so only this
    service can turn an address into its row, and the table cannot be used to confirm which addresses were tried."""
    return hashlib.sha256(b"ops-platform sign-in email failures\x00" + signing_key_text.encode()).digest()


@dataclass
class Passwords:
    identity: IdentityStore
    store: SignInStore
    hasher: PasswordHasher
    # Dev only: the one password for every seeded person with no stored password. None outside dev.
    demo_password: str | None
    min_length: int
    # Unset: no mail provider is configured, so a reset cannot be sent and the request says so.
    mail: MailSender | None
    console_url: str | None
    reset_ttl_s: int
    limits: Limits = field(default_factory=Limits)
    # The key an address is hashed with for its wrong-password count (`email_key_from`); see `screen_email`.
    email_key: bytes = b""
    _dummy: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self._dummy = self.hasher.hash(secrets.token_urlsafe(16))

    async def _verify(self, password: str, encoded: str) -> bool:
        return await asyncio.to_thread(self.hasher.verify, password, encoded)

    async def hash(self, password: str) -> str:
        if len(password) < self.min_length:
            raise ValidationFailed(
                f"Use at least {self.min_length} characters for the password.", code="password_too_short"
            )
        return await asyncio.to_thread(self.hasher.hash, password)

    async def check(self, user: User, password: str, *, request_id: str) -> str | None:
        """The method a correct password signs `user` in with (`password`, or `dev` for the demo password), or None.
        Raises 429 `signin_locked` while the person is locked, whatever the password."""
        if not await self.store.password_allowed(user.tenant_id):
            await self._verify(password, self._dummy)
            return None
        now = _now()
        until = await self.store.locked_until(user.tenant_id, user.id, now=_iso(now))
        if until is not None:
            await self._verify(password, self._dummy)
            raise _locked(until, now)
        method = await self._compare(user, password)
        if method is not None:
            await self.store.clear_failures(user.tenant_id, user.id)
            return method
        locked = await self.store.count_failure(
            user.tenant_id,
            user.id,
            at=_iso(now),
            window_start=_iso(now - timedelta(seconds=self.limits.failure_window_s)),
            max_failures=self.limits.max_failures,
            lock_until=_iso(now + timedelta(seconds=self.limits.lockout_s)),
            request_id=request_id,
        )
        if locked:
            raise _locked(_iso(now + timedelta(seconds=self.limits.lockout_s)), now)
        return None

    async def _compare(self, user: User, password: str) -> str | None:
        stored = await self.store.password_hash(user.tenant_id, user.id)
        if stored is not None:
            if not await self._verify(password, stored):
                return None
            if self.hasher.needs_rehash(stored):
                await self.store.set_password(user.tenant_id, user.id, await self.hash(password), at=_iso(_now()))
            return "password"
        await self._verify(password, self._dummy)
        if self.demo_password is not None and hmac.compare_digest(password.encode(), self.demo_password.encode()):
            return "dev"
        return None

    def _email_hash(self, email: str) -> str:
        return hmac.new(self.email_key, email.strip().lower().encode(), hashlib.sha256).hexdigest()

    async def screen_email(self, email: str, password: str) -> None:
        """Refuses a sign-in for an address locked by wrong passwords, known or not, after the same hashing work a
        check costs (c-196): sign-in counts per address so an unknown one locks exactly as a known one does."""
        now = _now()
        until = await self.store.email_locked_until(self._email_hash(email), now=_iso(now))
        if until is not None:
            await self._verify(password, self._dummy)
            raise _locked(until, now)

    async def count_email_failure(self, email: str) -> None:
        """Counts a wrong password for the address; raises 429 `signin_locked` when it reaches the limit."""
        now = _now()
        lock_until = _iso(now + timedelta(seconds=self.limits.lockout_s))
        locked = await self.store.count_email_failure(
            self._email_hash(email),
            at=_iso(now),
            window_start=_iso(now - timedelta(seconds=self.limits.failure_window_s)),
            max_failures=self.limits.max_failures,
            lock_until=lock_until,
        )
        if locked:
            raise _locked(lock_until, now)

    async def clear_email_failures(self, email: str) -> None:
        await self.store.clear_email_failures(self._email_hash(email))

    async def refuse_unknown(self, password: str) -> None:
        """The hashing work a known email would cost, for a sign-in whose email matched nobody."""
        await self._verify(password, self._dummy)

    async def forgot(self, email: str, *, request_id: str) -> None:
        """Mails a reset link to the one person with this email who could sign in by password; nothing otherwise."""
        if self.mail is None or self.console_url is None:
            raise ServiceUnavailable("Password reset is not set up on this installation.", code="mail_not_configured")
        found = await self.identity.users_by_email(email)
        if len(found) != 1 or not await self.store.password_allowed(found[0].tenant_id):
            return
        user = found[0]
        now = _now()
        since = _iso(now - timedelta(seconds=self.limits.reset_window_s))
        if await self.store.resets_since(user.tenant_id, user.id, since) >= self.limits.resets_per_window:
            return
        token = f"{RESET_PREFIX}{secrets.token_urlsafe(32)}"
        await self.store.open_reset(
            user.tenant_id,
            user.id,
            token_hash=token_hash(token),
            at=_iso(now),
            expires_at=_iso(now + timedelta(seconds=self.reset_ttl_s)),
        )
        minutes = self.reset_ttl_s // 60
        body = (
            f"Someone asked to reset the password for {user.email}.\n\n"
            f"Set a new password: {self.console_url.rstrip('/')}/reset-password/{token}\n\n"
            f"The link works once, for {minutes} minutes. If you did not ask, ignore this email."
        )
        await self.mail.send(
            OutboundMessage(
                key=f"password-reset:{token_hash(token)}", to=(user.email,), subject="Reset your password", body=body
            )
        )

    async def reset(self, token: str, password: str, *, request_id: str) -> None:
        encoded = await self.hash(password)
        done = await self.store.use_reset(token_hash(token), encoded, at=_iso(_now()), request_id=request_id)
        if done is None:
            raise ValidationFailed("This reset link has expired or was already used.", code="reset_invalid")
        # The new password ends the address's lock too, as it ends the person's.
        person = await self.identity.user(*done)
        if person is not None:
            await self.clear_email_failures(person.email)


def _now() -> datetime:
    return datetime.now(UTC)


def _locked(until: str, now: datetime) -> TooManyRequests:
    wait = max(1, math.ceil((datetime.fromisoformat(until.replace("Z", "+00:00")) - now).total_seconds()))
    minutes = math.ceil(wait / 60)
    return TooManyRequests(
        f"Too many wrong passwords. Try again in {minutes} minute{'s' if minutes != 1 else ''}, "
        "or reset your password.",
        code="signin_locked",
        details={"retryAfterSeconds": wait},
        retry_after_s=wait,
    )
