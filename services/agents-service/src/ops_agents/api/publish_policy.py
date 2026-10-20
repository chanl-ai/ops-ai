"""Whether a publish needs a second person's review (c-086). Every publish route in agents-service asks `decide` and
nothing else; tests/api/test_publish_policy_contract.py fails a route that decides for itself.

An admin sets, per team and area, one of three modes:

  always  every publish opens a review, in dev too
  major   a major change opens a review; a minor one publishes at once (the default)
  never   a publish goes live at once, unless it is a security change

A change is major when it is a first publish or touches anything outside the area's minor fields; guardrails have
none, and approval rules, access and egress are never minor. A security change (a guardrail, an agent's guardrails, an
approval rule, access or egress) opens a review under "never" too. Under the dev auto-approve setting "major" publishes
at once; an explicit "always" still opens a review, so a team can test the review path in dev.

Each publish request records the decision (`reviewRequired`, `policy`, `majorChange`), and its row names who asked
and who decided, so a publish under "never" still says who published."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast, get_args

from ops_access import publish_mode
from ops_service_kit.logging import get_logger

from ..store.tenancy import NoTenantError
from .deps import Runtime
from .platform_policies import PolicyUnread

log = get_logger("ops_agents.publish_policy")

Area = Literal["agents", "workflows", "guardrails", "skills", "widgets", "tools"]
Mode = Literal["always", "major", "never"]
AREAS: tuple[Area, ...] = get_args(Area)
MODES: tuple[Mode, ...] = get_args(Mode)
DEFAULT_MODE: Mode = "major"

# What a change may touch and still publish without a review under "major". Anything else (tools, instructions,
# knowledge, limits, caps, pins, models, a definition's nodes, a skill's body, a widget's actions) is major.
MINOR_FIELDS: dict[Area, frozenset[str]] = {
    # pinnedVersion: a widget deployment moving to a published version, which was reviewed when it was published.
    "agents": frozenset({"name", "role", "channels", "suggestions", "widgetPins", "pinnedVersion"}),
    "workflows": frozenset({"name", "description", "layout", "positions", "position"}),
    "guardrails": frozenset(),
    "skills": frozenset({"name", "description"}),
    "widgets": frozenset({"name", "description"}),
    # tools-service decides a tool module's major and security changes itself and reads only the mode (c-139).
    "tools": frozenset(),
}
# Never minor, whatever an area's list says: approval rules, access and egress.
ALWAYS_MAJOR = frozenset({"approval", "approvals", "access", "egress", "requiresApproval", "approvalPolicy"})
# Reviewed under "never" as well: what a publish lets an agent say or do without a person. Each is a path into the
# version, with the value an unset path stands for.
SECURITY_PATHS: dict[tuple[str, ...], Any] = {
    **{(k,): None for k in ALWAYS_MAJOR},
    ("guardrailPins",): None,
    ("guardrails", "blockedTopics"): None,
    ("guardrails", "redactPii"): True,
}


@dataclass(frozen=True)
class Decision:
    review_required: bool
    mode: Mode
    major: bool
    # Why: policy_always, security_change, policy_never, major_change, dev_auto_approve, minor_change or
    # policy_unread. The publish dialog says it before anyone presses Publish.
    reason: str = "major_change"

    def record(self) -> dict[str, Any]:
        """Kept on the publish request: what the policy said when it was asked."""
        return {
            "reviewRequired": self.review_required,
            "policy": self.mode,
            "majorChange": self.major,
            "reviewReason": self.reason,
        }


def is_major(area: Area, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
    if old is None or area == "guardrails":
        return True
    changed = {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)}
    return bool(changed & ALWAYS_MAJOR) or bool(changed - MINOR_FIELDS[area])


def is_security_change(area: Area, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
    if area == "guardrails":
        return True
    return any(_at(old or {}, path, unset) != _at(new, path, unset) for path, unset in SECURITY_PATHS.items())


def _at(doc: dict[str, Any], path: tuple[str, ...], unset: Any) -> Any:
    value: Any = doc
    for key in path:
        value = cast(dict[str, Any], value).get(key) if isinstance(value, dict) else None
    found = _rule(value)
    return unset if found is None else found


def _rule(value: Any) -> Any:
    """A setting with its empty parts dropped, so no pins and an absent field are the same rule. False and 0 are values:
    switching redaction off is a change, never an unset field that reads as its default."""
    if isinstance(value, dict):
        kept = {k: r for k, v in cast(dict[str, Any], value).items() if (r := _rule(v)) is not None}
        return kept or None
    if isinstance(value, list):
        kept_items = [r for v in cast(list[Any], value) if (r := _rule(v)) is not None]
        return kept_items or None
    return None if value is None or value == "" else value


def dev_auto_approves(rt: Runtime) -> bool:
    return rt.settings.registry_auto_approve and rt.settings.environment == "dev"


async def team_document(rt: Runtime) -> dict[str, Any] | None:
    """The workspace's publishReview policy, `{team: {area: mode}}`, read live from platform-service on every decision
    so a change applies to the next publish. Empty without a platform URL or before a tenant is set
    (the start-up seed); None when platform-service cannot be read."""
    if rt.policies is None:
        return {}
    try:
        found = await rt.policies.value("publishReview")
    except NoTenantError:
        return {}
    except PolicyUnread as e:
        log.warning("publishReview unread; the publish waits for review", extra={"error": str(e)})
        return None
    return cast(dict[str, Any], found) if isinstance(found, dict) else {}


async def decide(rt: Runtime, *, area: Area, team_id: str, old: dict[str, Any] | None, new: dict[str, Any]) -> Decision:
    """`old` is what is published now (None before a first publish), `new` what is being published. When the policy
    cannot be read the publish opens a review, so nothing skips one because platform-service was down."""
    document = await team_document(rt)
    major = is_major(area, old, new)
    if document is None:
        return Decision(True, "always", major, "policy_unread")
    found = publish_mode(document, team_id, area)
    mode: Mode = found if found in MODES else DEFAULT_MODE
    if mode == "always":
        return Decision(True, mode, major, "policy_always")
    if mode == "never":
        security = is_security_change(area, old, new)
        return Decision(security, mode, major, "security_change" if security else "policy_never")
    if not major:
        return Decision(False, mode, major, "minor_change")
    if dev_auto_approves(rt):
        return Decision(False, mode, major, "dev_auto_approve")
    return Decision(True, mode, major, "major_change")
