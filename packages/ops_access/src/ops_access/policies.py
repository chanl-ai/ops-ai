"""The rules an admin may set for a workspace, with each default in one place. Most defaults are open, agents' changes
to apps included (appChanges: no team asks); the ones that hold something back are requesterMayDecide (off) and the
AI uses (aiSteps, taskAssist, checkBeforeSend). A team changes any of them. Every value is changed through
`can(settings, manage)` in the security team. platform-service stores the values per tenant and puts them on every
token; services read them there with `policy(p, key)`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from ops_identity import Principal


@dataclass(frozen=True)
class Policy:
    key: str
    # The value a workspace has until an admin sets one.
    default: Any
    # One line, shown beside the switch.
    effect: str
    # "bool"; "floor": a number from 0 to 1, or None for no floor; "days": a whole number of days, or None for no limit;
    # "hours": a whole number of hours; "publish_modes": one team's {area: mode}, see PUBLISH_AREAS and PUBLISH_MODES.
    # "names": a list of names (appWritesNeedApproval: app ids). "choice": one of `choices`.
    # "app_changes": one team's {ask, answer, reviewerRole, testAccountsNeverAsk} (appChanges); "app_changes_by_app":
    # one team's {app id: {answer, reviewerRole}} (appChangesByApp).
    kind: str = "bool"
    # The grid cell a change needs; the security team holds it.
    changed_by: tuple[str, str] = ("settings", "manage")
    # A value per team ({team: value}): a change sets the acting team's part only, checked in that team.
    per_team: bool = False
    # Read live from platform-service on each decision (GET /v1/policies/{key}), never carried in a token, so a change
    # applies at once rather than at the next token refresh.
    live: bool = False
    # A short name for the Policies page, so a new policy is drawn there with no console change.
    title: str = ""
    # A "choice" policy's options, in order: (value, title, what it means).
    choices: tuple[tuple[str, str, str], ...] = ()
    # A fact no value of the policy changes, said under it on the Policies page.
    note: str = ""


KINDS = ("bool", "floor", "days", "hours", "publish_modes", "names", "choice", "app_changes", "app_changes_by_app")


# Which publishes wait for a second person's review (moved here), per team and area:
#   always  every publish opens a review, in dev too
#   major   a major change opens a review; a minor one publishes at once (the default)
#   never   a publish goes live at once, unless it is a security change
PUBLISH_AREAS = ("agents", "workflows", "guardrails", "skills", "widgets", "tools")
PUBLISH_MODES = ("always", "major", "never")
DEFAULT_PUBLISH_MODE = "major"


POLICIES: tuple[Policy, ...] = (
    Policy(
        "requesterMayDecide",
        # Off by default: someone other than the person who asked decides. A workspace that set it on keeps that.
        False,
        "The person who asked for a decision may also make it. Off (the default): someone else has to decide.",
        title="Requester may decide",
    ),
    Policy(
        "extractionFloor",
        # A quality threshold, not an access rule: its default is the engine's floor (ops_extract.checks.DEFAULT_FLOOR),
        # so moving it into settings changes no running workspace.
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
        "companySignInRequired",
        # Off: a password follows the sign-in providers, as before company sign-in could be required.
        False,
        "People on the workspace's verified company domains sign in only through the company's provider; named "
        "break-glass Security admins keep a password. Off: passwords follow the sign-in providers.",
        title="Company sign-in required",
    ),
    Policy(
        "chatThreadsOwnerOnly",
        # People's chats stay private by default; off lets the team's admins read them.
        True,
        "Each chat thread is read only by the person who started it. Off: the team's admins read them too.",
        title="Private chat threads",
    ),
    Policy(
        "memoryRetentionDays",
        None,
        "How long agents keep what they remember about each person. Unset: kept until the person removes it.",
        kind="days",
        # Any team admin sets it, not only the security team.
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
        "appChanges",
        # No team set: nobody is asked before an agent changes an app. A team turns it on and picks who answers.
        {},
        "Ask before an agent changes anything in an app. Off: agents change apps without asking. On: the person in "
        "the chat confirms, or a reviewer of a chosen role approves.",
        kind="app_changes",
        # A team admin's: settings.manage in the team.
        changed_by=("settings", "manage"),
        per_team=True,
        live=True,
        title="Ask before an agent changes anything in an app",
    ),
    Policy(
        "appChangesByApp",
        # No app listed: every app follows the team's switch. An app's entry overrides the team for that app.
        {},
        "Per app: use the team setting, or change without asking, ask the person, or ask a reviewer.",
        kind="app_changes_by_app",
        changed_by=("settings", "manage"),
        per_team=True,
        live=True,
        title="Approval by app",
    ),
    Policy(
        "toolWritesNeedApproval",
        # Derived from appChanges for one release (on when the team asks a reviewer); a write to it lands in appChanges.
        {},
        "Every tool write by the team waits for a person's approval, including the ones a tool lets run at once.",
        changed_by=("reviews", "manage"),
        per_team=True,
        live=True,
        title="Approve every tool write",
    ),
    Policy(
        "appWritesNeedApproval",
        # Derived from appChangesByApp for one release: the apps whose answer is a reviewer, by the id the Apps page
        # shows (plugin:<id>, a connection's id, or module:<id>); a write to it lands in appChangesByApp.
        {},
        "Writes from the listed apps wait for a person's approval. Other writes run unless their tool asks for one.",
        kind="names",
        changed_by=("reviews", "manage"),
        per_team=True,
        live=True,
        title="Approve writes of these apps",
    ),
    Policy(
        "appsChangeWithoutAsking",
        # Derived from appChangesByApp for one release: the apps whose answer is "none"; a write lands there.
        {},
        "Writes from the listed apps run in chat without asking the person first. Every other app asks before changes.",
        kind="names",
        # A team admin's: settings.manage in the team, which builders and members do not hold.
        changed_by=("settings", "manage"),
        per_team=True,
        live=True,
        title="Apps that change without asking",
    ),
    Policy(
        "aiSteps",
        # The one policy whose default holds something back: no team has AI steps until it turns them on.
        # No team set: off everywhere.
        {},
        "The team's workflows may use AI steps: Classify, Summarise, Extract from text, Draft. Off until turned on.",
        changed_by=("workflows", "manage"),
        per_team=True,
        live=True,
        title="AI steps in workflows",
    ),
    Policy(
        "taskAssist",
        # Off until a team turns it on, as aiSteps.
        {},
        "A typed task opens with AI help: its question, a summary, doubtful fields and a suggestion. Off until on.",
        changed_by=("workflows", "manage"),
        per_team=True,
        live=True,
        title="Task assist",
    ),
    Policy(
        "checkBeforeSend",
        # Off until a team turns it on, as aiSteps.
        {},
        "Every write the team sends is checked against its sending policy first; a failure waits for a person.",
        changed_by=("workflows", "manage"),
        per_team=True,
        live=True,
        title="Check before sending",
    ),
    Policy(
        "pageImages",
        # Off until a team turns it on, as aiSteps: the page image leaves for the model
        # provider, so the Security team decides which teams may send it, and a document type turns it on under that.
        {},
        "Document types in the team may show the model the page image of a scan or a doubtful field. Off until on.",
        per_team=True,
        live=True,
        title="Page images to the model",
    ),
    Policy(
        "aiStepsMaskPersonalData",
        # Masks by default, as an agent's redactPii does; a team turns it off with false. It
        # covers what people see of a document type's examples too; the key stays, a generic name comes later.
        {},
        "People see SSNs, card and account numbers, emails and phones masked in AI steps' output and in document type "
        "examples. A team may turn it off.",
        changed_by=("workflows", "manage"),
        per_team=True,
        live=True,
        title="Mask personal data in AI steps",
    ),
    Policy(
        "egressNewHosts",
        # Asking Security is the default: a new address waits for a person who manages the egress list, as before the
        # policy existed. A plugin's own hosts never need listing for its own calls.
        "ask_security",
        "What happens when an app or tool names an address the account has not allowed yet.",
        kind="choice",
        live=True,
        title="New app addresses",
        choices=(
            ("ask_security", "Ask Security", "A new address waits until someone on the Security team allows it."),
            (
                "builders",
                "Builders allow it",
                "Whoever builds the app or tool allows the address, recorded in their name.",
            ),
            ("any_public", "Any public address", "Apps and tools may call any public address without listing it."),
            (
                "block",
                "Only listed addresses",
                "A new address is refused; Security lists addresses on the Egress page.",
            ),
        ),
        note="Private, loopback, link-local and cloud metadata addresses are never reached unless Security lists a "
        "private range, and only https is called.",
    ),
    Policy(
        "securityTeamAddsSecrets",
        False,
        "Only the security team adds secrets. Off: builders add and use their own team's secrets.",
        title="Only Security adds secrets",
    ),
)

BY_KEY: dict[str, Policy] = {p.key: p for p in POLICIES}


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
    if (
        policy.kind == "names"
        and isinstance(value, list)
        and len(cast(list[Any], value)) <= 500
        and all(isinstance(n, str) and 0 < len(n) <= 200 for n in cast(list[Any], value))
    ):
        return list(dict.fromkeys(cast(list[str], value)))
    if policy.kind == "choice" and isinstance(value, str) and value in {c[0] for c in policy.choices}:
        return value
    if policy.kind == "app_changes" and isinstance(value, dict):
        held = cast(dict[str, Any], value)
        answer = held.get("answer", "person")
        role = held.get("reviewerRole")
        if (
            isinstance(held.get("ask", False), bool)
            and answer in ANSWERS
            and (role is None or isinstance(role, str))
            and isinstance(held.get("testAccountsNeverAsk", True), bool)
            and isinstance(held.get("testRunsAsk", True), bool)
        ):
            return {
                "ask": held.get("ask", False),
                "answer": answer,
                "reviewerRole": role,
                "testAccountsNeverAsk": held.get("testAccountsNeverAsk", True),
                "testRunsAsk": held.get("testRunsAsk", True),
            }
    if policy.kind == "app_changes_by_app" and isinstance(value, dict):
        out: dict[str, Any] = {}
        for app, raw in cast(dict[Any, Any], value).items():
            entry: dict[str, Any] = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
            role = entry.get("reviewerRole")
            if not (isinstance(app, str) and entry.get("answer") in ANSWERS):
                break
            out[app] = {"answer": entry["answer"], **({"reviewerRole": role} if isinstance(role, str) else {})}
        else:
            return out
    if policy.kind == "publish_modes" and isinstance(value, dict):
        modes = cast(dict[Any, Any], value)
        if all(a in PUBLISH_AREAS and m in PUBLISH_MODES for a, m in modes.items()):
            return {str(a): str(m) for a, m in modes.items()}
    takes = {
        "bool": "true or false",
        "floor": "a number from 0 to 1, or null",
        "days": "a whole number of days, or null",
        "hours": "a whole number of hours from 1 to 8760",
        "names": "a list of up to 500 names, each 1 to 200 characters",
        "publish_modes": f"an object of area ({', '.join(PUBLISH_AREAS)}) to mode ({', '.join(PUBLISH_MODES)})",
        "choice": f"one of {', '.join(c[0] for c in policy.choices)}",
        "app_changes": "{ask, answer (none, person or reviewer), reviewerRole, testAccountsNeverAsk, testRunsAsk}",
        "app_changes_by_app": "an object of app id to {answer (none, person or reviewer), reviewerRole}",
    }
    raise ValueError(f"{key} takes {takes[policy.kind]}")


def policy(p: Principal, key: str) -> Any:
    """The policy's value for the caller's tenant, from the token; its default when the token carries none."""
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


def team_names(values: Any, team: str | None) -> list[str]:
    """The names `team` listed in a per-team list policy (appWritesNeedApproval), from the value GET /v1/policies/{key}
    returns; none for a team that set nothing."""
    if team is None or not isinstance(values, dict):
        return []
    listed: object = cast(dict[str, Any], values).get(team)
    return [str(n) for n in cast(list[Any], listed)] if isinstance(listed, list) else []


def publish_mode(modes: dict[str, Any], team: str, area: str) -> str:
    """The publish review mode of `area` in `team`, from `publishReview` as GET /v1/policies/publishReview returns it
    (read live on each decision); `major` where the team set none."""
    of_team: dict[str, Any] = dict(modes.get(team) or {})
    return str(of_team.get(area, DEFAULT_PUBLISH_MODE))


ANSWERS = ("none", "person", "reviewer")


def _level(value: Any) -> tuple[str | None, str | None]:
    """The (answer, reviewerRole) one level of the chain holds; answer None when the level says nothing."""
    if not isinstance(value, dict):
        return None, None
    held = cast(dict[str, Any], value)
    answer = held.get("answer")
    if held.get("ask") is False:
        answer = "none"
    return (answer if answer in ANSWERS else None), held.get("reviewerRole")


def effective_answer(*, tool: dict[str, Any], app: Any, team: Any, channel: str, test_account: bool) -> dict[str, Any]:
    """Whether a call waits, and who answers, for one tool: the single rule every service reads.

    The most specific level wins: the tool's `approvalMode`, then the app's entry of `appChangesByApp`, then the team's
    `appChanges`. A read never waits; a write over MCP always does (nobody is in the chat); a tool with two approvers
    always asks a reviewer. A test run (channel "test") of a write on a live account asks the person while `testRunsAsk`
    is on. A team's checkbox `testAccountsNeverAsk` (on unless saved off) lets a test account through.
    "Ask the person" with nobody in the chat (a workflow) goes to the reviewer role. An unreadable team policy (None)
    fails closed: the write waits for a reviewer.

    Returns:
        {waits, answer ("none" | "person" | "reviewer"), reviewerRole, source ("tool" | "app" | "team" | "mcp" |
        "test-account")}.
    """
    if tool.get("access") != "write":
        return {"waits": False, "answer": "none", "reviewerRole": None, "source": "tool"}
    team_role = None
    if team is None:
        return {"waits": True, "answer": "reviewer", "reviewerRole": None, "source": "team"}
    if channel == "mcp":
        return {"waits": True, "answer": "reviewer", "reviewerRole": tool.get("reviewerRole"), "source": "mcp"}
    if tool.get("approvers") == 2:
        role = tool.get("reviewerRole") or _level(team)[1]
        return {"waits": True, "answer": "reviewer", "reviewerRole": role, "source": "tool"}
    team_answer, team_role = _level(team)
    answer, role, source = team_answer or "none", team_role, "team"
    app_answer, app_role = _level(app)
    if app_answer is not None:
        answer, role, source = app_answer, app_role or team_role, "app"
    mode = tool.get("approvalMode")
    if mode in ANSWERS:
        answer, role, source = mode, tool.get("reviewerRole") or role, "tool"
    if answer == "person" and channel == "workflow":
        answer = "reviewer"
    # A test run of a write on a live account pauses for the person's yes unless the team turned `testRunsAsk` off
    # (on unless saved off); chats and workflows keep the answer above.
    if (
        answer == "none"
        and channel == "test"
        and not test_account
        and (cast(dict[str, Any], team).get("testRunsAsk", True) if isinstance(team, dict) else True)
    ):
        answer, role, source = "person", None, "test-run"
    if answer == "none":
        return {"waits": False, "answer": "none", "reviewerRole": None, "source": source}
    if test_account and (
        cast(dict[str, Any], team).get("testAccountsNeverAsk", True) if isinstance(team, dict) else True
    ):
        return {"waits": False, "answer": "none", "reviewerRole": None, "source": "test-account"}
    return {"waits": True, "answer": answer, "reviewerRole": None if answer == "person" else role, "source": source}


def tool_waits(access: str, mode: str | None = None) -> bool:
    """Whether a call of a tool waits on its own setting alone, for a place with no team to ask (a seeded or plugin
    tool's row, the agents' catalogue): `effective_answer` for a team that saved nothing. `mode` is the tool's own
    answer (none, person or reviewer), None when it has none. The team's and app's levels are applied where the team
    is known (the gateway's `WriteApprovals.answer`)."""
    return bool(
        effective_answer(
            tool={"access": access, "approvalMode": mode}, app=None, team={}, channel="chat", test_account=False
        )["waits"]
    )
