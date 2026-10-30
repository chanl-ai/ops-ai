"""The stricter rules an admin may switch on for a workspace (c-186). Each policy's default is open, the AI uses
aside (aiSteps, taskAssist, checkBeforeSend): a new workspace meets no control until an admin sets one, and every value
is changed through `can(settings, manage)` in the security team. platform-service stores the values per tenant and puts
them on every token; services read them there with `policy(p, key)`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from ops_identity import Principal


@dataclass(frozen=True)
class Policy:
    key: str
    # The open value: the decision the policy names holds nothing back.
    default: Any
    # One line, shown beside the switch.
    effect: str
    # "bool"; "floor": a number from 0 to 1, or None for no floor; "days": a whole number of days, or None for no limit;
    # "hours": a whole number of hours; "publish_modes": one team's {area: mode}, see PUBLISH_AREAS and PUBLISH_MODES.
    kind: str = "bool"
    # The grid cell a change needs; the security team holds it.
    changed_by: tuple[str, str] = ("settings", "manage")
    # A value per team ({team: value}): a change sets the acting team's part only, checked in that team.
    per_team: bool = False
    # Read live from platform-service on each decision (GET /v1/policies/{key}), never carried in a token, so a change
    # applies at once rather than at the next token refresh (owner, 2026-10-18).
    live: bool = False
    # A short name for the Policies page, so a new policy is drawn there with no console change.
    title: str = ""


KINDS = ("bool", "floor", "days", "hours", "publish_modes", "plugins")


# Which publishes wait for a second person's review (c-086, moved here by c-214), per team and area:
#   always  every publish opens a review, in dev too
#   major   a major change opens a review; a minor one publishes at once (the default)
#   never   a publish goes live at once, unless it is a security change
PUBLISH_AREAS = ("agents", "workflows", "guardrails", "skills", "widgets", "tools")
PUBLISH_MODES = ("always", "major", "never")
DEFAULT_PUBLISH_MODE = "major"


POLICIES: tuple[Policy, ...] = (
    Policy(
        "requesterMayDecide",
        True,
        "The person who asked for a decision may also make it. Off: someone else has to decide.",
        title="Requester may decide",
    ),
    Policy(
        "extractionFloor",
        # A quality threshold, not an access rule: its default is the engine's floor (ops_extract.checks.DEFAULT_FLOOR),
        # so moving it into settings changes no running workspace (owner via orch, 2026-10-17).
        0.8,
        "The lowest confidence an Extract from file step may accept; no step can ask for less.",
        kind="floor",
        title="Extraction confidence floor",
    ),
    Policy(
        "stepUp",
        False,
        "Every approver confirms their sign-in again before deciding. Off: only operations that ask for it.",
        title="Step-up on every approval",
    ),
    Policy(
        "publishReview",
        # No team set: every area `major`, as before the setting moved here, so the move changes no workspace.
        {},
        "Which of a team's publishes wait for review: always, major changes only (the default), or never.",
        kind="publish_modes",
        changed_by=("reviews", "manage"),
        per_team=True,
        live=True,
        title="Publish reviews",
    ),
    Policy(
        "chatThreadsOwnerOnly",
        # People's chats stay private by default (owner via orch, 2026-10-17); off lets the team's admins read them.
        True,
        "Each chat thread is read only by the person who started it. Off: the team's admins read them too.",
        title="Private chat threads",
    ),
    Policy(
        "memoryRetentionDays",
        None,
        "How long agents keep what they remember about each person. Unset: kept until the person removes it.",
        kind="days",
        # Any team admin sets it (owner, 2026-10-17), not only the security team.
        changed_by=("chat", "manage"),
        title="Memory retention",
    ),
    Policy(
        "reviewSlaHours",
        8,
        "How long a publish review may wait, in wall-clock hours, before it shows as overdue.",
        kind="hours",
        # A team admin sets how fast reviews are expected (reviews.manage), not only the security team.
        changed_by=("reviews", "manage"),
        title="Review deadline",
    ),
    Policy(
        "toolWritesNeedApproval",
        # No team set: each write follows its operation's own flag in the gateway's registry, so every write waits
        # except the few declared to run at once (open_case).
        {},
        "Every tool write by the team waits for a person's approval, including the ones a tool lets run at once.",
        changed_by=("reviews", "manage"),
        per_team=True,
        live=True,
        title="Approve every tool write",
    ),
    Policy(
        "aiSteps",
        # The one policy whose default holds something back: no team has AI steps until it turns them on (owner,
        # 2026-10-18, c-298). No team set: off everywhere.
        {},
        "The team's workflows may use AI steps: Classify, Summarise, Extract from text, Draft. Off until turned on.",
        changed_by=("workflows", "manage"),
        per_team=True,
        live=True,
        title="AI steps in workflows",
    ),
    Policy(
        "taskAssist",
        # Off until a team turns it on, as aiSteps (owner, 2026-10-18, c-302).
        {},
        "A typed task opens with AI help: its question, a summary, doubtful fields and a suggestion. Off until on.",
        changed_by=("workflows", "manage"),
        per_team=True,
        live=True,
        title="Task assist",
    ),
    Policy(
        "checkBeforeSend",
        # Off until a team turns it on, as aiSteps (owner, 2026-10-18, c-300).
        {},
        "Every write the team sends is checked against its sending policy first; a failure waits for a person.",
        changed_by=("workflows", "manage"),
        per_team=True,
        live=True,
        title="Check before sending",
    ),
    Policy(
        "pageImages",
        # Off until a team turns it on, as aiSteps (owner, 2026-10-18, c-295): the page image leaves for the model
        # provider, so the Security team decides which teams may send it, and a document type turns it on under that.
        {},
        "Document types in the team may show the model the page image of a scan or a doubtful field. Off until on.",
        per_team=True,
        live=True,
        title="Page images to the model",
    ),
    Policy(
        "aiStepsMaskPersonalData",
        # Masks by default, as an agent's redactPii does (owner, 2026-10-19, c-321); a team turns it off with false. It
        # covers what people see of a document type's examples too (c-297); the key stays, a generic name comes later.
        {},
        "People see SSNs, card and account numbers, emails and phones masked in AI steps' output and in document type "
        "examples. A team may turn it off.",
        changed_by=("workflows", "manage"),
        per_team=True,
        live=True,
        title="Mask personal data in AI steps",
    ),
    Policy(
        "plugins",
        # No plugin is on until the platform admin turns it on for the install (c-564); teams then turn it on for
        # themselves. A plugin's entry may also lock settings every team uses ({"api_version": "61.0"}).
        {},
        "Which installed plugins teams may turn on, and the settings fixed for every team.",
        kind="plugins",
        live=True,
        title="Plugins",
    ),
    Policy(
        "securityTeamAddsSecrets",
        False,
        "Only the security team adds secrets. Off: builders add and use their own team's secrets.",
        title="Only Security adds secrets",
    ),
)

BY_KEY: dict[str, Policy] = {p.key: p for p in POLICIES}


def _app_client(value: object) -> bool:
    """A plugin's platform OAuth app as the policy holds it: exactly {"id": a client id}."""
    if not isinstance(value, dict):
        return False
    v = cast(dict[Any, Any], value)
    cid = v.get("id")
    return set(v) == {"id"} and isinstance(cid, str) and 0 < len(cid) <= 500


def check_value(key: str, value: Any) -> Any:
    """The value if the policy takes it; ValueError naming the key otherwise."""
    policy = BY_KEY.get(key)
    if policy is None:
        raise ValueError(f"{key} is not a policy")
    if policy.kind == "bool" and isinstance(value, bool):
        return value
    if (
        policy.kind == "floor"
        and (value is None or (isinstance(value, int | float) and not isinstance(value, bool)))
        and (value is None or 0 <= value <= 1)
    ):
        return value
    if policy.kind == "days" and (value is None or (type(value) is int and 1 <= value <= 36500)):
        return value
    if policy.kind == "hours" and type(value) is int and 1 <= value <= 8760:
        return value
    if policy.kind == "publish_modes" and isinstance(value, dict):
        modes = cast(dict[Any, Any], value)
        if all(a in PUBLISH_AREAS and m in PUBLISH_MODES for a, m in modes.items()):
            return {str(a): str(m) for a, m in modes.items()}
    if policy.kind == "plugins" and isinstance(value, dict):
        out: dict[str, Any] = {}
        for pid, entry in cast(dict[Any, Any], value).items():
            if not isinstance(entry, dict) or not isinstance(cast(dict[str, Any], entry).get("enabled"), bool):
                break
            e = cast(dict[str, Any], entry)
            locked: object = e.get("locked") or {}
            if set(e) - {"enabled", "locked", "client"} or not isinstance(locked, dict):
                break
            fixed = cast(dict[Any, Any], locked)
            if not all(isinstance(k, str) and isinstance(v, str | int | float | bool) for k, v in fixed.items()):
                break
            # The platform's own OAuth app for the plugin (c-565): its client id only; the secret is sealed in
            # tools-service at the account and never travels in a policy.
            client: object = e.get("client")
            if client is not None and not _app_client(client):
                break
            out[str(pid)] = {"enabled": e["enabled"], "locked": {str(k): v for k, v in fixed.items()}}
            if client is not None:
                out[str(pid)]["client"] = {"id": str(cast(dict[str, Any], client)["id"])}
        else:
            return out
    takes = {
        "bool": "true or false",
        "floor": "a number from 0 to 1, or null",
        "days": "a whole number of days, or null",
        "hours": "a whole number of hours from 1 to 8760",
        "publish_modes": f"an object of area ({', '.join(PUBLISH_AREAS)}) to mode ({', '.join(PUBLISH_MODES)})",
        "plugins": (
            'an object of plugin id to {"enabled": true or false, "locked": {setting: value}, "client": {"id": text}}'
        ),
    }
    raise ValueError(f"{key} takes {takes[policy.kind]}")


def policy(p: Principal, key: str) -> Any:
    """The policy's value for the caller's tenant, from the token; its open default when the token predates it."""
    return p.policies.get(key, BY_KEY[key].default)


def team_on(values: Any, team: str | None) -> bool:
    """Whether `team` turned a per-team switch on (toolWritesNeedApproval, aiSteps, taskAssist, checkBeforeSend,
    pageImages), from the value GET /v1/policies/{key} returns (read live on each call); off for a team that set
    nothing."""
    return team is not None and isinstance(values, dict) and cast(dict[str, Any], values).get(team) is True


def team_off(values: Any, team: str | None) -> bool:
    """Whether `team` turned a per-team switch that is on by default off (aiStepsMaskPersonalData): only an explicit
    false counts, so a team that set nothing keeps the protection."""
    return team is not None and isinstance(values, dict) and cast(dict[str, Any], values).get(team) is False


def team_writes_need_approval(values: dict[str, Any], team: str | None) -> bool:
    """Whether `team` set toolWritesNeedApproval on."""
    return team_on(values, team)


def publish_mode(modes: dict[str, Any], team: str, area: str) -> str:
    """The publish review mode of `area` in `team`, from `publishReview` as GET /v1/policies/publishReview returns it
    (read live on each decision); `major` where the team set none."""
    of_team: dict[str, Any] = dict(modes.get(team) or {})
    return str(of_team.get(area, DEFAULT_PUBLISH_MODE))
