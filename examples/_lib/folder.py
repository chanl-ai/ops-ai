"""Shared public-SDK setup for one Example folder. Each folder's setup.py calls `run(Path(__file__).parent)`."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from ops_ai import OpsAI
from ops_ai._io import load_data
from ops_ai.errors import NotFound, OpsError

BINDINGS = ".bindings.json"
HANDBOOK_NAMES = frozenset({"account-opening", "account opening handbook"})
READ_TOOL = "search_customers"
WRITE_TOOL = "add_customer_note"
HOLD_OPS = frozenset({"list_accounts", "place_hold"})
SAMPLE_EMAIL = "alex.morgan@harborpine.example"
SAMPLE_TEAM = "Customer Operations"
LOCAL_PORTS = {"platform": 8710, "agents": 8700, "tools": 8720, "kb": 8740, "files": 8750, "documents": 8760}
ROOT = Path(__file__).resolve().parents[2]
CITE_HANDBOOK_FOLDER = ROOT / "examples" / "agents" / "02-cite-the-handbook"
NORMALIZE_REQUEST_FOLDER = ROOT / "examples" / "workflows" / "01-normalize-a-request"
NORMALIZE_REQUEST_ID = "normalize_support_request"
ROUTE_SUPPORT_MESSAGE_ID = "route_support_message"
MODEL_NODE_TYPES = frozenset({"ops.ai.classify", "ops.ai.summarise", "ops.ai.extractText", "ops.ai.draft"})
# A model alias no gateway serves: the step's call is refused, so a model failure looks the same on a scripted model and
# on a real one, which a prompt cannot promise.
UNREACHABLE_MODEL = "model-that-does-not-exist"
EXTRACT_DOC_TYPES = ("legal_notice", "levy_notice", "garnishment_notice")
CLAIM_CASE_TYPES = ("complaint",)


def _local_services() -> dict[str, str]:
    return {
        name: f"http://127.0.0.1:{os.environ.get(f'OPS_{name.upper()}_PORT', port)}"
        for name, port in LOCAL_PORTS.items()
    }


def _conn() -> dict[str, Any]:
    base = os.environ.get("OPS_BASE_URL") or "http://127.0.0.1"
    conn: dict[str, Any] = {"base_url": base}
    if "127.0.0.1" in base or base.startswith("http://localhost"):
        conn["services"] = _local_services()
    return conn


def _admin_env() -> dict[str, str]:
    if named := os.environ.get("OPS_ADMIN_ENV"):
        env_path = Path(named)
    else:
        env_path = Path(os.environ.get("OPS_RUN_DIR") or ROOT / ".run") / "dev-admin.env"
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    for line in env_path.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def _demo_password() -> str:
    if password := os.environ.get("OPS_DEMO_PASSWORD"):
        return password
    return _admin_env().get("OPS_DEMO_PASSWORD", "")


def _wanted_team() -> tuple[str, str]:
    return (os.environ.get("OPS_TEAM") or "", os.environ.get("OPS_TEAM_NAME") or SAMPLE_TEAM)


def _with_sample_team(ops: OpsAI) -> OpsAI:
    wanted_id, wanted_name = _wanted_team()
    for team in ops.teams.list():
        if wanted_id and str(team.get("id")) == wanted_id:
            return ops.with_team(str(team["id"]))
        if team.get("name") == wanted_name:
            return ops.with_team(str(team["id"]))
    return ops


def ops_client() -> OpsAI:
    """A signed-in client for this folder. A saved Harbor profile must not win on a local stack."""
    password = _demo_password()
    email = os.environ.get("OPS_EXAMPLE_EMAIL") or SAMPLE_EMAIL
    if password:
        return _with_sample_team(OpsAI.sign_in(email, password, **_conn()))
    try:
        return _with_sample_team(OpsAI())
    except ValueError:
        raise


def ops_as(email: str) -> OpsAI:
    password = _demo_password()
    if not password:
        raise ValueError("no demo password; run make sample-team")
    return _with_sample_team(OpsAI.sign_in(email, password, **_conn()))


def sample_members(ops: OpsAI) -> list[dict[str, Any]]:
    members = _listed(ops.raw.platform.members_list_members())
    return [item for item in members if item.get("status") == "active" and item.get("email")]


def cell_allowed(ops: OpsAI, area: str, action: str) -> bool:
    return bool(ops.raw.platform.me_why_not(area=area, action=action).get("allowed"))


def person_for_cell(ops: OpsAI, area: str, action: str, *, allowed: bool) -> dict[str, Any]:
    for member in sample_members(ops):
        try:
            signed = ops_as(str(member["email"]))
        except (NotFound, OpsError):
            continue
        if cell_allowed(signed, area, action) is allowed:
            return member
    raise ValueError(f"no sample-team person with {area}.{action} allowed={allowed}; run make sample-team")


def _handbook(item: dict[str, Any]) -> bool:
    name = str(item.get("name") or "").strip().lower()
    ident = str(item.get("id") or "").strip().lower()
    slug = str(item.get("slug") or "").strip().lower().replace("-", " ")
    return name in HANDBOOK_NAMES or ident in HANDBOOK_NAMES or slug in HANDBOOK_NAMES


def find_handbook(ops: OpsAI) -> dict[str, Any] | None:
    for item in ops.knowledge.list():
        if _handbook(item):
            return item
    return None


def find_chat_target(ops: OpsAI) -> dict[str, Any]:
    chosen: dict[str, Any] | None = None
    for agent in ops.agents.list():
        chosen = chosen or agent
        if str(agent.get("status") or "").lower() == "published":
            return agent
    if chosen:
        return chosen
    raise ValueError("no published chat target; run make sample-team")


def find_read_module(ops: OpsAI) -> dict[str, Any]:
    for module in ops.tools.list():
        detail = ops.tools.get(module["id"]) if module.get("id") else module
        operations = detail.get("operations") or module.get("operations") or []
        if any(op.get("name") == READ_TOOL for op in operations):
            return detail if detail.get("id") else module
    raise ValueError(f"no {READ_TOOL} tool; run make sample-team")


def _write_grant_waits(ops: OpsAI) -> bool:
    """Whether agents-service currently hands add_customer_note as a gated write (GET /v1/tools)."""
    for row in _listed(ops.raw.agents.agents_list_tools(access=["write"])):
        if str(row.get("name") or row.get("id") or "") == WRITE_TOOL:
            return row.get("requiresApproval") is True
    return False


def _ensure_team_writes_wait(ops: OpsAI) -> None:
    """The team's live toolWritesNeedApproval switch. Grants read it from GET /v1/grantable-operations; no module
    version and no Security review. A per-team policy SET takes true or false for the acting team."""
    held = ops.raw.platform.policies_get_policy("toolWritesNeedApproval")
    value = held.get("value") or {}
    team = getattr(ops.config, "team", None)
    if isinstance(value, dict) and team and value.get(team) is True:
        return
    ops.raw.platform.policies_set_policy("toolWritesNeedApproval", {"value": True})


def _ensure_write_waits(ops: OpsAI) -> None:
    """Turn writes to wait. The operation switch is staged until POST /versions (and Security if a version is already
    in review). The team policy applies on the next grantable-operations read. Approvals are off by default; no new
    route."""
    module = find_read_module(ops)
    mid = str(module["id"])
    op = next((row for row in (module.get("operations") or []) if row.get("name") == WRITE_TOOL), None)
    if op is None:
        raise ValueError(f"no {WRITE_TOOL} tool; run make sample-team")
    in_review = any(v.get("status") == "in_review" for v in module.get("versions") or [])
    if not in_review and op.get("requiresApproval") is not True:
        try:
            module = ops.raw.tools.tool_modules_update_operation(mid, str(op["id"]), {"requiresApproval": True})
        except OpsError:
            module = ops.raw.tools.tool_modules_get_module(mid)
        if module.get("pendingChanges"):
            try:
                ops.raw.tools.tool_modules_publish_version(mid, {"note": "Writes wait for a person"})
            except OpsError:
                pass
    _ensure_team_writes_wait(ops)
    deadline = time.monotonic() + 40.0
    while time.monotonic() < deadline:
        if _write_grant_waits(ops):
            return
        time.sleep(0.5)
    raise ValueError(f"{WRITE_TOOL} still does not wait after the team policy; grants cache")


def customer_notes(ops: OpsAI, customer_id: str) -> list[Any]:
    """Read notes through the public tool run. Used to see what an approved write actually stored."""
    module = find_read_module(ops)
    result = ops.raw.tools.tool_modules_run_tool(
        str(module["id"]),
        "list_customer_notes",
        {"mode": "real", "input": {"customer_id": customer_id}},
    )
    return _listed((result or {}).get("output") if isinstance(result, dict) else result)


def find_hold_module(ops: OpsAI) -> dict[str, Any]:
    needed = set(HOLD_OPS)
    for module in ops.tools.list():
        detail = ops.tools.get(module["id"]) if module.get("id") else module
        names = {str(op.get("name")) for op in detail.get("operations") or module.get("operations") or []}
        if needed <= names and str(detail.get("status") or "").lower() == "published":
            return detail if detail.get("id") else module
    raise ValueError(f"no published {'/'.join(sorted(needed))} tool; run make sample-team")


def send_once(ops: OpsAI, message: str) -> dict[str, Any]:
    target = find_chat_target(ops)
    return ops.agents.chat(str(target["id"]), message)


def search_page(ops: OpsAI, question: str, *, kb_id: str | None = None, limit: int = 3) -> dict[str, Any]:
    kb = {"id": kb_id} if kb_id else find_handbook(ops)
    if not kb:
        raise ValueError("no account-opening handbook; run this folder's setup.py")
    return ops.knowledge.search({"kbIds": [kb["id"]], "question": question, "limit": limit})


def _emails(value: Any) -> list[str]:
    if isinstance(value, dict):
        found = [str(value["email"])] if value.get("email") else []
        for key in ("output", "data", "items", "customers"):
            if key in value:
                found.extend(_emails(value[key]))
        return found
    if isinstance(value, list):
        emails: list[str] = []
        for item in value:
            emails.extend(_emails(item))
        return emails
    return []


def customer_emails(result: Any) -> list[str]:
    return _emails(result)


def find_customer(ops: OpsAI, email: str) -> dict[str, Any]:
    module = find_read_module(ops)
    return ops.raw.tools.tool_modules_run_tool(
        str(module["id"]),
        READ_TOOL,
        {"mode": "real", "input": {"query": email}},
    )


def folder_bindings(folder: Path) -> dict[str, Any]:
    path = folder / BINDINGS
    if not path.is_file():
        raise ValueError(f"no {BINDINGS}; run this folder's setup.py")
    return json.loads(path.read_text())


def find_skill(ops: OpsAI, name: str) -> dict[str, Any] | None:
    try:
        page = ops.raw.agents.agents_list_skills(search=name, page_size=100)
    except (NotFound, OpsError):
        return None
    for item in _listed(page):
        if item.get("name") == name:
            return item
    return None


def find_guardrail(ops: OpsAI, name: str) -> dict[str, Any] | None:
    try:
        page = ops.raw.agents.agents_list_guardrails(search=name, page_size=100)
    except (NotFound, OpsError):
        return None
    for item in _listed(page):
        if item.get("name") == name:
            return item
    return None


def agent_skill_pins(ops: OpsAI, agent_id: str) -> list[dict[str, Any]]:
    try:
        detail = ops.raw.agents.agents_get_agent_skills(str(agent_id))
    except (NotFound, OpsError):
        return []
    pins = detail.get("pins") if isinstance(detail, dict) else None
    return list(pins) if isinstance(pins, list) else []


def chat_agent(ops: OpsAI, agent_id: str, message: str) -> dict[str, Any]:
    return ops.agents.chat(str(agent_id), message)


def _agents_transport(ops: OpsAI) -> Any:
    """The SDK transport already used by generated agents calls. /chat/* is public L3, not yet generated."""
    raw = getattr(ops, "raw", None)
    agents = getattr(raw, "agents", None)
    transport = getattr(agents, "_t", None) or getattr(ops, "_t", None)
    if transport is None:
        raise RuntimeError("public agents transport is missing")
    return transport


def agents_call(ops: OpsAI, method: str, path: str, body: Any | None = None, *, stream: bool = False) -> Any:
    """One public agents-service route through the SDK's authenticated transport."""
    op = {
        "method": method,
        "path": path,
        "pathParams": [],
        "query": [],
        "headers": [],
        "body": "json" if body is not None else None,
        "stream": stream,
    }
    return _agents_transport(ops).call("agents", op, {}, {}, {}, body)


def start_chat_thread(
    ops: OpsAI,
    agent_id: str,
    *,
    kb_ids: list[str] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST /chat/threads. A widen override is 422 naming the field."""
    body: dict[str, Any] = {"agentId": str(agent_id), "kbIds": list(kb_ids or [])}
    if overrides is not None:
        body["overrides"] = overrides
    return agents_call(ops, "POST", "/chat/threads", body)


def thread_settings(ops: OpsAI, thread_id: str) -> dict[str, Any]:
    """GET /chat/threads/{id}/settings: limits, stored overrides, effective settings."""
    return agents_call(ops, "GET", f"/chat/threads/{thread_id}/settings")


def patch_thread_settings(ops: OpsAI, thread_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """PATCH /chat/threads/{id}/settings. A value outside the agent's limits is 422."""
    return agents_call(ops, "PATCH", f"/chat/threads/{thread_id}/settings", body)


def read_chat(ops: OpsAI, thread_id: str) -> dict[str, Any]:
    return agents_call(ops, "GET", f"/chat/threads/{thread_id}")


def send_chat(ops: OpsAI, thread_id: str, message: str, *, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST /chat/threads/{id}/messages, then read the thread so settings and tool calls are on the turn."""
    body: dict[str, Any] = {"content": message}
    if overrides is not None:
        body["overrides"] = overrides
    events = list(agents_call(ops, "POST", f"/chat/threads/{thread_id}/messages", body, stream=True) or [])
    thread = read_chat(ops, thread_id)
    messages = thread.get("messages") or []
    assistant = next((m for m in reversed(messages) if isinstance(m, dict) and m.get("role") == "assistant"), {})
    tool_calls: list[Any] = []
    for msg in messages:
        if isinstance(msg, dict):
            tool_calls.extend(msg.get("toolCalls") or [])
    if not tool_calls:
        _collect_tool_calls(events, tool_calls)
    return {
        "threadId": thread_id,
        "reply": str(assistant.get("content") or ""),
        "events": events,
        "citations": assistant.get("citations") or [],
        "toolCalls": tool_calls,
        "settings": assistant.get("settings") or {},
        "messages": messages,
        "thread": thread,
    }


def chat_reply(result: dict[str, Any]) -> str:
    return str(result.get("reply") or "")


def chat_citations(result: dict[str, Any]) -> list[Any]:
    found = list(result.get("citations") or [])
    if found:
        return found
    for event in result.get("events") or []:
        data = event.get("data") if isinstance(event, dict) else event
        nested = data.get("data") if isinstance(data, dict) else None
        if isinstance(nested, list) and nested:
            return list(nested)
        if isinstance(data, list) and data:
            return list(data)
        if isinstance(data, dict) and data.get("citations"):
            return list(data["citations"])
    return []


def chat_tool_names(result: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for call in result.get("toolCalls") or []:
        if isinstance(call, dict):
            name = str(call.get("name") or call.get("tool") or "")
            if name:
                names.append(name)
    _collect_tool_names(result.get("events") or [], names)
    return names


def _collect_tool_calls(value: Any, calls: list[Any]) -> None:
    if isinstance(value, dict):
        kind = str(value.get("type") or value.get("event") or "")
        payload = value.get("call") if isinstance(value.get("call"), dict) else None
        name = str((payload or {}).get("name") or (payload or {}).get("tool") or "")
        if kind in {"tool_call", "tool_start", "tool_end"} and name:
            if not any(isinstance(c, dict) and str(c.get("name") or c.get("tool") or "") == name for c in calls):
                calls.append(payload)
        for item in value.values():
            _collect_tool_calls(item, calls)
        return
    if isinstance(value, list):
        for item in value:
            _collect_tool_calls(item, calls)


def _collect_tool_names(value: Any, names: list[str]) -> None:
    if isinstance(value, dict):
        name = str(value.get("name") or value.get("tool") or "")
        if name and (name in {READ_TOOL, WRITE_TOOL} or name.startswith("workflow")) and name not in names:
            names.append(name)
        for item in value.values():
            _collect_tool_names(item, names)
        return
    if isinstance(value, list):
        for item in value:
            _collect_tool_names(item, names)


def chat_child_run_id(result: dict[str, Any]) -> str | None:
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("workflow") and value.get("runId"):
                found.append(str(value["runId"]))
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(result)
    return found[0] if found else None


def run_has_human_task(run: dict[str, Any]) -> bool:
    return bool(run.get("taskId")) or str(run.get("status") or "") == "waiting"


def chat_wait(ops: OpsAI, result: dict[str, Any]) -> dict[str, Any]:
    """The public thread state after a chat turn that paused for a write approval."""
    thread_id = str(result.get("threadId") or "")
    state = ops.raw.agents.threads_thread_state(thread_id)
    payload = ((state.get("interrupt") or {}).get("payload") or {}) if isinstance(state, dict) else {}
    call = payload.get("call") if isinstance(payload, dict) else {}
    return {
        "threadId": thread_id,
        "state": state,
        "payload": payload if isinstance(payload, dict) else {},
        "call": call if isinstance(call, dict) else {},
    }


def write_calls(ops: OpsAI, thread_id: str) -> list[dict[str, Any]]:
    """Gateway executions for add_customer_note on this thread (public /v1/executions)."""
    listed = ops.raw.tools.executions_list_executions(tool=WRITE_TOOL, thread=thread_id, page_size=50)
    if isinstance(listed, dict):
        return list(listed.get("data") or [])
    return list(listed or [])


def mint_write_token(ops: OpsAI, thread_id: str) -> dict[str, Any]:
    """POST /v1/threads/{id}/approvals: token bound to the exact waiting input."""
    try:
        return ops.raw.agents.threads_approve(thread_id, {})
    except OpsError as exc:
        if exc.code != "step_up_required":
            raise
        password = _demo_password()
        if not password:
            raise
        minted = ops.raw.platform.auth_step_up({"password": password})
        return ops.raw.agents.threads_approve(thread_id, {"stepUpToken": str(minted.get("token") or "")})


def wait_thread_not_waiting(ops: OpsAI, thread_id: str, *, timeout: float = 30.0) -> dict[str, Any]:
    """The public thread state once it is no longer paused for a write approval."""
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = ops.raw.agents.threads_thread_state(thread_id) or {}
        payload = ((last.get("interrupt") or {}).get("payload") or {}) if isinstance(last, dict) else {}
        if not (isinstance(payload, dict) and payload.get("kind") == "approval"):
            return last
        time.sleep(0.3)
    return last


def approve_write(ops: OpsAI, task_id: str, decision: str = "approve", **fields: Any) -> dict[str, Any]:
    """Decide a review that may gate a write. place_hold asks for a step-up first; mint one and retry."""
    try:
        decided = ops.tasks.decide(task_id, decision, **fields)
    except OpsError as exc:
        if exc.code != "step_up_required":
            raise
        password = _demo_password()
        if not password:
            raise
        minted = ops.raw.platform.auth_step_up({"password": password})
        decided = ops.tasks.decide(task_id, decision, stepUpToken=str(minted.get("token") or ""), **fields)
    try:
        wait_thread_not_waiting(ops, task_id)
    except NotFound:
        pass
    return decided


def run_answer_text(run: dict[str, Any]) -> str:
    output = run.get("output")
    if isinstance(output, dict):
        return str(output.get("text") or json.dumps(output))
    return str(output or "")


def find_citing_agent(ops: OpsAI) -> dict[str, Any] | None:
    path = CITE_HANDBOOK_FOLDER / BINDINGS
    if path.is_file():
        agent_id = json.loads(path.read_text()).get("agentId")
        if agent_id:
            try:
                detail = ops.agents.get(str(agent_id))
                if detail.get("publishedVersion"):
                    return detail
            except (NotFound, OpsError):
                pass
    named_path = CITE_HANDBOOK_FOLDER / "resources" / "agent.yaml"
    named = load_data(named_path).get("name") if named_path.is_file() else None
    if not named:
        return None
    try:
        for agent in ops.agents.list(search=str(named), page_size=50):
            published = agent.get("publishedVersion") or str(agent.get("status") or "").lower() == "published"
            if agent.get("name") == named and published:
                return agent
    except (NotFound, OpsError):
        return None
    return None


def find_published_agent(ops: OpsAI) -> dict[str, Any] | None:
    if cited := find_citing_agent(ops):
        return cited
    try:
        for agent in ops.agents.list(page_size=50):
            published = agent.get("publishedVersion") or str(agent.get("status") or "").lower() == "published"
            if published:
                return agent
    except (NotFound, OpsError):
        return None
    return None


def apply_model_out_of_reach(ops: OpsAI, definition_path: Path) -> str:
    """Stores a copy of the folder's workflow, under its own id, with every model step on an alias no gateway serves, so
    each leaves by its error port. The folder's own workflow is left as it was: a stored version cannot be put back.
    Returns the copy's id."""
    broken = copy.deepcopy(load_data(definition_path))
    broken["id"] = f"{broken['id']}_model_out_of_reach"
    for node in broken.get("nodes") or []:
        if node.get("type") in MODEL_NODE_TYPES:
            node.setdefault("parameters", {})["model"] = UNREACHABLE_MODEL
    return str(ops.workflows.apply(broken)["workflowId"])


def start_test_email(ops: OpsAI, workflow_id: str, event: dict[str, Any]) -> dict[str, Any]:
    started = ops.workflows.send_test_email(workflow_id, event, mode="test")
    return ops.runs.wait(started["runId"])


SYSTEM_PURGE = "file_deleted_purge"


def delete_file(ops: OpsAI, file_id: str) -> None:
    """Deletes a team file through the public Files API; files-service emits file.deleted."""
    ops.raw.files.files_delete_file(file_id)


def wait_purge_run(ops: OpsAI, file_id: str, *, timeout: float = 90.0) -> dict[str, Any]:
    """The system file_deleted_purge run for this file, once it has ended."""
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        for row in ops.runs.list(workflow_id=SYSTEM_PURGE, page_size=20):
            inp = row.get("input") or {}
            if str(inp.get("fileId") or "") != file_id:
                continue
            last = dict(row)
            if str(last.get("status") or "") in {"succeeded", "failed", "cancelled"}:
                return last
        time.sleep(0.4)
    return last


def start_file_deleted(
    ops: OpsAI, name: str = "purge-example.txt", content: bytes | None = None
) -> tuple[str, dict[str, Any]]:
    """Upload a file, delete it so file.deleted starts the system purge workflow, and wait for that run."""
    body = content if content is not None else f"purge-me {time.time_ns()}\n".encode()
    file_id = upload_bytes(ops, name, body)
    if not file_id:
        raise ValueError("upload did not return a file id")
    delete_file(ops, file_id)
    return file_id, wait_purge_run(ops, file_id)


def upload_bytes(
    ops: OpsAI, name: str, content: bytes, *, mime: str = "text/plain", purpose: str = "case_attachment"
) -> str:
    stored = ops.upload(name, content, mime=mime, purpose=purpose)
    return str(stored.get("id") or stored.get("fileId") or "")


def email_with_file(event: dict[str, Any], file_id: str) -> dict[str, Any]:
    return {**event, "attachments": [{"fileId": file_id}]}


def wait_run(ops: OpsAI, run_id: str, *, timeout: float = 180.0) -> dict[str, Any]:
    """Wait past an extract park until the run ends or a person has a task."""
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = ops.runs.wait(run_id, timeout=min(20.0, max(1.0, deadline - time.monotonic())))
        if str(last.get("status") or "") in {"succeeded", "failed", "cancelled"}:
            return last
        if last.get("taskId"):
            return last
        time.sleep(0.4)
    return last


def wait_ended(ops: OpsAI, run_id: str, *, timeout: float = 30.0) -> dict[str, Any]:
    """Wait until the run is terminal. A waiting review is not terminal; use this for a review timeout."""
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = ops.runs.get(run_id)
        if str(last.get("status") or "") in {"succeeded", "failed", "cancelled"}:
            return last
        time.sleep(0.4)
    return last


def inspect_run(ops: OpsAI, run_id: str) -> dict[str, Any]:
    """The same run `opsai workflows inspect` prints: status, waiting payload, steps."""
    return ops.runs.get(run_id)


def resume_wait(ops: OpsAI, run: dict[str, Any], body: dict[str, Any]) -> Any:
    """Resume a Wait for step through the public callback route, using the step's own token."""
    waiting = run.get("waiting") or {}
    token = str(((waiting.get("payload") or {}).get("resume") or {}).get("token") or "")
    node = str(waiting.get("node") or "wait")
    run_id = str(run.get("id") or run.get("runId") or "")
    if not token or not run_id:
        raise ValueError("run is not waiting on an external callback")
    caller = OpsAI(
        access_token=token,
        base_url=ops.config.base_url,
        services=ops.config.services,
    )
    try:
        return caller.raw.agents.workflows_resume_step(run_id, node, body)
    finally:
        caller.close()


def _listed(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        items = value.get("data") or value.get("items") or []
        return items if isinstance(items, list) else []
    return []


def find_document_type(ops: OpsAI, *wanted: str) -> dict[str, Any] | None:
    names = {name.lower() for name in wanted}
    try:
        items = _listed(ops.raw.documents.document_types_list_types())
    except (NotFound, OpsError):
        return None
    for item in items:
        if _named(item, names):
            return item
    return None


def find_case_type(ops: OpsAI, *wanted: str) -> dict[str, Any] | None:
    names = {name.lower() for name in wanted}
    try:
        items = _listed(ops.raw.agents.cases_list_case_types())
    except (NotFound, OpsError):
        return None
    for item in items:
        if _named(item, names):
            return item
    return None


def _named(item: dict[str, Any], names: set[str]) -> bool:
    ident = str(item.get("id") or "").lower()
    name = str(item.get("name") or "").lower()
    if ident in names or name in names:
        return True
    return any(
        ident.endswith(f"_{wanted}")
        or ident.startswith(f"{wanted}_")
        or name.endswith(f"_{wanted}")
        or name.endswith(f" {wanted}")
        or name.startswith(f"{wanted} ")
        for wanted in names
    )


def find_normalize_workflow(ops: OpsAI) -> dict[str, Any] | None:
    try:
        return ops.workflows.get(NORMALIZE_REQUEST_ID)
    except (NotFound, OpsError):
        pass
    path = NORMALIZE_REQUEST_FOLDER / BINDINGS
    if not path.is_file():
        return None
    workflow_id = json.loads(path.read_text()).get("workflowId")
    if not workflow_id:
        return None
    try:
        return ops.workflows.get(str(workflow_id))
    except (NotFound, OpsError):
        return None


def _workflow_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or row.get("workflowId") or NORMALIZE_REQUEST_ID)


def _bind_agent_nodes(definition: dict[str, Any], agent_id: str) -> dict[str, Any]:
    bound = json.loads(json.dumps(definition))
    for node in bound.get("nodes") or []:
        if node.get("type") == "ops.ai.agent":
            node.setdefault("parameters", {})["agent"] = agent_id
    return bound


def wait_for_passage(ops: OpsAI, kb_id: str, question: str, *, limit: int = 3, timeout: float = 25.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = ops.knowledge.search({"kbIds": [kb_id], "question": question, "limit": limit})
        if last.get("passages"):
            return last
        time.sleep(0.4)
    return last


def run(folder: Path, argv: list[str] | None = None) -> int:
    meta = load_data(folder / "example.yaml")
    ap = argparse.ArgumentParser(description=meta.get("title") or folder.name)
    ap.add_argument("action", nargs="?", default="setup", choices=("setup", "status", "remove"))
    ns = ap.parse_args(argv)
    if meta.get("status") == "planned":
        print(f"PLANNED {meta['id']}: {meta.get('gaps') or 'reserved'}")
        return 0
    try:
        ops = ops_client()
    except Exception as exc:
        print(f"NOT READY: {exc}", file=sys.stderr)
        return 2
    if ns.action == "remove":
        return _remove(ops, folder, meta)
    if ns.action == "status":
        return _status(ops, folder, meta)
    return _setup(ops, folder, meta)


def _complete(meta: dict[str, Any], bindings: dict[str, Any], folder: Path | None = None) -> bool:
    track = meta.get("track")
    if track == "chat":
        return bool(bindings.get("agentId"))
    if track == "knowledge":
        return bool(bindings.get("knowledgeId"))
    if track == "tool":
        return bool(bindings.get("moduleId"))
    if track == "agent":
        if not bindings.get("agentId"):
            return False
        if folder is not None:
            if (folder / "resources" / "skill.yaml").is_file() and not bindings.get("skillId"):
                return False
            if (folder / "resources" / "guardrail.yaml").is_file() and not bindings.get("guardrailId"):
                return False
        return True
    if track == "workflow":
        return bool(bindings.get("workflowId"))
    if track == "composition":
        return bool(bindings.get("workflowId") and bindings.get("agentId"))
    return True


def _setup(ops: OpsAI, folder: Path, meta: dict[str, Any]) -> int:
    bindings_path = folder / BINDINGS
    if bindings_path.is_file():
        bindings = json.loads(bindings_path.read_text())
        if _complete(meta, bindings, folder):
            if bindings.get("writeOperation") == WRITE_TOOL:
                try:
                    _ensure_write_waits(ops)
                except (NotFound, OpsError, ValueError) as exc:
                    print(f"NOT READY: {exc}", file=sys.stderr)
                    return 2
            print(f"FOUND {meta['id']}")
            return 0
    bindings: dict[str, Any] = {"id": meta["id"]}
    if meta.get("track") == "composition":
        if err := _setup_composition(ops, folder, meta, bindings):
            return err
        bindings_path.write_text(json.dumps(bindings, indent=2) + "\n")
        _write_profile(ops, folder)
        print("READY")
        _ready(bindings, meta)
        return 0
    workflow = folder / "resources" / "workflow.yaml"
    if not workflow.is_file() and meta.get("track") == "workflow":
        pointed = Path(str(meta.get("entrypoint") or ""))
        candidate = pointed if pointed.is_absolute() else folder / pointed
        if candidate.is_file() and candidate.suffix in {".yaml", ".yml", ".json"}:
            workflow = candidate
    agent = folder / "resources" / "agent.yaml"
    if workflow.is_file():
        definition = load_data(workflow)
        if _needs_ai_steps(definition):
            _ensure_ai_steps(ops)
        if READ_TOOL in _operation_names(definition):
            try:
                find_read_module(ops)
            except ValueError as exc:
                print(f"NOT READY: {exc}", file=sys.stderr)
                return 2
        if HOLD_OPS & set(_operation_names(definition)):
            try:
                find_hold_module(ops)
            except ValueError as exc:
                print(f"NOT READY: {exc}", file=sys.stderr)
                return 2
        if err := _ensure_folder_tools(ops, folder, definition, bindings):
            return err
        source: Any = workflow
        if _needs_extract(definition):
            if err := _ensure_extract_resources(ops, bindings):
                return err
            definition = _bind_extract_nodes(
                definition, str(bindings.get("documentTypeId") or ""), bindings.get("caseTypeId")
            )
            source = definition
        if err := _ensure_child_workflow(ops, folder, meta, bindings):
            return err
        if _needs_knowledge(definition):
            kb = _ensure_handbook(
                ops,
                folder / "resources" / "documents" / "handbook.md"
                if (folder / "resources" / "documents" / "handbook.md").is_file()
                else None,
            )
            definition = _bind_knowledge_nodes(definition, str(kb["id"]))
            bindings["knowledgeId"] = kb["id"]
            source = definition
        if _needs_bound_agent(definition):
            cited = find_published_agent(ops)
            if not cited:
                print(
                    "NOT READY: no published agent; run examples/agents/02-cite-the-handbook/setup.py",
                    file=sys.stderr,
                )
                return 2
            definition = _bind_agent_nodes(definition, str(cited["id"]))
            bindings["agentId"] = cited["id"]
            source = definition
        check = ops.workflows.validate(source)
        if not check.ok:
            check.raise_for_errors()
        made = ops.workflows.apply(source)
        review = _publish_workflow(ops, str(made["workflowId"]), f"Example {meta['id']}")
        bindings["workflowId"] = made["workflowId"]
        bindings["version"] = made.get("version")
        bindings["digest"] = made.get("digest")
        bindings["publish"] = review
        if not _workflow_published(ops, str(made["workflowId"])):
            print(f"NOT READY: workflow {made['workflowId']} is not published", file=sys.stderr)
            return 2
    if agent.is_file() or meta.get("track") == "agent":
        if err := _setup_agent(ops, folder, meta, bindings):
            return err
    page = folder / "resources" / "documents" / "handbook.md"
    if page.is_file() or meta.get("track") == "knowledge":
        kb = _ensure_handbook(ops, page if page.is_file() else None)
        query = load_data(folder / "fixtures" / "query.json") if (folder / "fixtures" / "query.json").is_file() else {}
        found = wait_for_passage(
            ops, kb["id"], str(query.get("question") or "beneficial owners"), limit=int(query.get("limit") or 3)
        )
        if not found.get("passages"):
            print("NOT READY: handbook is not searchable yet", file=sys.stderr)
            return 2
        bindings["knowledgeId"] = kb["id"]
    if meta.get("track") == "chat" and not bindings.get("agentId"):
        bindings["agentId"] = find_chat_target(ops)["id"]
    if meta.get("track") == "tool":
        bindings["moduleId"] = find_read_module(ops)["id"]
        bindings["operation"] = READ_TOOL
    bindings_path.write_text(json.dumps(bindings, indent=2) + "\n")
    _write_profile(ops, folder)
    print("READY")
    _ready(bindings, meta)
    return 0


def _setup_composition(ops: OpsAI, folder: Path, meta: dict[str, Any], bindings: dict[str, Any]) -> int:
    workflow = folder / "resources" / "workflow.yaml"
    agent = folder / "resources" / "agent.yaml"
    if workflow.is_file():
        cited = find_citing_agent(ops)
        if not cited:
            print(
                "NOT READY: no citing agent; run examples/agents/02-cite-the-handbook/setup.py",
                file=sys.stderr,
            )
            return 2
        definition = _bind_agent_nodes(load_data(workflow), str(cited["id"]))
        check = ops.workflows.validate(definition)
        if not check.ok:
            check.raise_for_errors()
        made = ops.workflows.apply(definition)
        review = _publish_workflow(ops, str(made["workflowId"]), f"Example {meta['id']}")
        bindings["workflowId"] = made["workflowId"]
        bindings["version"] = made.get("version")
        bindings["digest"] = made.get("digest")
        bindings["publish"] = review
        bindings["agentId"] = cited["id"]
        if not _workflow_published(ops, str(made["workflowId"])):
            print(f"NOT READY: workflow {made['workflowId']} is not published", file=sys.stderr)
            return 2
    if agent.is_file():
        normalize = find_normalize_workflow(ops)
        if not normalize:
            print(
                "NOT READY: no normalize_support_request; run examples/workflows/01-normalize-a-request/setup.py",
                file=sys.stderr,
            )
            return 2
        data = dict(load_data(agent))
        tools = data.pop("tools", None) or [f"workflow:{_workflow_id(normalize)}"]
        data["toolIds"] = [
            f"workflow:{_workflow_id(normalize)}" if str(item).startswith("workflow:") else item for item in tools
        ]
        made = ops.agents.apply(data)
        agent_id = str(made.get("id") or "")
        if not agent_id:
            print("NOT READY: apply did not return an agent id", file=sys.stderr)
            return 2
        review = _publish_agent(ops, agent_id, f"Example {meta['id']}")
        detail = ops.agents.get(agent_id)
        if not detail.get("publishedVersion"):
            print(f"NOT READY: agent {agent_id} is not published", file=sys.stderr)
            return 2
        bindings["agentId"] = agent_id
        bindings["workflowId"] = _workflow_id(normalize)
        bindings["publish"] = review
    return 0


def _setup_agent(ops: OpsAI, folder: Path, meta: dict[str, Any], bindings: dict[str, Any]) -> int:
    path = folder / "resources" / "agent.yaml"
    if not path.is_file():
        print("NOT READY: missing resources/agent.yaml", file=sys.stderr)
        return 2
    data = dict(load_data(path))
    knowledge = data.pop("knowledge", None)
    tools = data.pop("tools", None)
    specialist_path = folder / "resources" / "specialist.yaml"
    if specialist_path.is_file():
        specialist = dict(load_data(specialist_path))
        if specialist.pop("knowledge", None):
            kb = find_handbook(ops)
            if not kb:
                print(
                    "NOT READY: no account-opening handbook; run examples/knowledge/01-search-a-page/setup.py",
                    file=sys.stderr,
                )
                return 2
            specialist["collections"] = [kb["id"]]
            bindings["knowledgeId"] = kb["id"]
        made_spec = ops.agents.apply(specialist)
        spec_id = str(made_spec.get("id") or "")
        if not spec_id:
            print("NOT READY: specialist apply did not return an agent id", file=sys.stderr)
            return 2
        _publish_agent(ops, spec_id, f"Example {meta['id']} specialist")
        if not ops.agents.get(spec_id).get("publishedVersion"):
            print(f"NOT READY: specialist {spec_id} is not published", file=sys.stderr)
            return 2
        bindings["specialistId"] = spec_id
        tools = [f"agent:{spec_id}" if str(t) in {"agent:specialist", "specialist"} else t for t in (tools or [])]
    if data.get("model") == "fake":
        data["model"] = "default"
    if knowledge:
        kb = find_handbook(ops)
        if not kb:
            print(
                "NOT READY: no account-opening handbook; run examples/knowledge/01-search-a-page/setup.py",
                file=sys.stderr,
            )
            return 2
        found = wait_for_passage(ops, kb["id"], "beneficial owners")
        if not found.get("passages"):
            print("NOT READY: handbook is not searchable yet", file=sys.stderr)
            return 2
        data["collections"] = [kb["id"]]
        bindings["knowledgeId"] = kb["id"]
    if tools:
        names = [str(item) for item in tools]
        if any(not name.startswith(("workflow:", "agent:")) for name in names):
            module = find_read_module(ops)
            offered = {str(op.get("name")) for op in (module.get("operations") or [])}
            missing = [name for name in names if not name.startswith(("workflow:", "agent:")) and name not in offered]
            if missing:
                print(f"NOT READY: no {'/'.join(missing)} tool; run make sample-team", file=sys.stderr)
                return 2
        if WRITE_TOOL in names:
            _ensure_write_waits(ops)
        data["toolIds"] = list(tools)
        bindings["operation"] = names[0]
        if WRITE_TOOL in names:
            bindings["writeOperation"] = WRITE_TOOL
    made = ops.agents.apply(data)
    agent_id = str(made.get("id") or "")
    if not agent_id:
        print("NOT READY: apply did not return an agent id", file=sys.stderr)
        return 2
    if err := _pin_folder_controls(ops, folder, meta, bindings, agent_id):
        return err
    review = _publish_agent(ops, agent_id, f"Example {meta['id']}")
    detail = ops.agents.get(agent_id)
    if not detail.get("publishedVersion"):
        print(f"NOT READY: agent {agent_id} is not published", file=sys.stderr)
        return 2
    bindings["agentId"] = agent_id
    bindings["publish"] = review
    return 0


def _team_name(ops: OpsAI) -> str:
    wanted_id, wanted_name = _wanted_team()
    wanted = str(getattr(ops.config, "team", "") or wanted_id or "")
    named = wanted_name
    for team in ops.teams.list():
        if str(team.get("id")) == wanted and team.get("name"):
            return str(team["name"])
        if str(team.get("name")) == wanted_name:
            named = wanted_name
    return named


def _decide_publish(pending_id: str | None, note: str) -> None:
    if not pending_id:
        return
    body = {"decision": "approved", "reason": note}
    last: OpsError | None = None
    for client in (_workspace_admin(), _security_ops()):
        try:
            client.raw.agents.reviews_decide_publish_request(str(pending_id), body)
            return
        except OpsError as exc:
            last = exc
    if last is not None:
        raise last


def _publish_review_id(review: Any) -> str | None:
    if not isinstance(review, dict):
        return None
    if review.get("status") in {"approved", "published"} or review.get("decidedAt"):
        return None
    nested = review.get("review")
    if isinstance(nested, dict) and nested.get("id"):
        return str(nested["id"])
    for key in ("pendingReviewId", "pendingRequestId"):
        if review.get(key):
            return str(review[key])
    ident = review.get("id")
    if ident and (
        review.get("kind") in {"agent_publish", "workflow_publish", "publish_request"}
        or str(ident).startswith(("WFP-", "rev_", "pr_"))
    ):
        return str(ident)
    return None


def _publish_agent(ops: OpsAI, agent_id: str, note: str) -> Any:
    try:
        review = ops.agents.publish(agent_id, note=note)
    except OpsError as exc:
        if exc.code not in {"cannot_request", "review_open", "already_published", "not_a_draft"}:
            raise
        review = ops.agents.get(agent_id)
    _decide_publish(_publish_review_id(review), note)
    return review


def _publish_workflow(ops: OpsAI, workflow_id: str, note: str) -> Any:
    try:
        review = ops.workflows.publish(workflow_id, note=note)
    except OpsError as exc:
        if exc.code not in {"cannot_request", "review_open", "already_published", "not_a_draft"}:
            raise
        review = {"error": exc.code}
        try:
            review = ops.workflows.get(workflow_id)
        except (NotFound, OpsError):
            pass
    _decide_publish(_publish_review_id(review), note)
    return review


def _workflow_published(ops: OpsAI, workflow_id: str) -> bool:
    try:
        detail = ops.workflows.get(workflow_id)
    except (NotFound, OpsError):
        return False
    return bool(
        detail.get("publishedVersion")
        or detail.get("liveVersion")
        or detail.get("published")
        or detail.get("status") == "published"
    )


def _workspace_admin() -> OpsAI:
    env = _admin_env()
    email = env.get("OPS_DEMO_ADMIN_EMAIL") or env.get("OPS_BOOTSTRAP_ADMIN_EMAIL")
    password = env.get("OPS_DEMO_ADMIN_PASSWORD") or env.get("OPS_BOOTSTRAP_ADMIN_PASSWORD")
    if not email or not password:
        raise ValueError("no workspace admin in OPS_ADMIN_ENV or .run/dev-admin.env; run make up")
    return _with_sample_team(OpsAI.sign_in(email, password, **_conn()))


def _ensure_published_skill(ops: OpsAI, spec: dict[str, Any], note: str) -> dict[str, Any]:
    name = str(spec["name"])
    found = find_skill(ops, name)
    if found is None:
        body: dict[str, Any] = {
            "name": name,
            "instructions": spec["instructions"],
            "ownerTeam": spec.get("ownerTeam") or _team_name(ops),
        }
        for key in ("useWhen", "loading", "refusal"):
            if spec.get(key):
                body[key] = spec[key]
        found = ops.raw.agents.agents_create_skill(body)
    sid = str(found["id"])
    detail = ops.raw.agents.agents_get_skill(sid)
    if detail.get("publishedVersion") is not None:
        return detail
    try:
        detail = ops.raw.agents.agents_request_skill_publish(sid, {"note": note})
    except OpsError as exc:
        if exc.code not in {"cannot_request", "review_open"}:
            raise
        detail = ops.raw.agents.agents_get_skill(sid)
    _decide_publish(detail.get("pendingReviewId"), note)
    return ops.raw.agents.agents_get_skill(sid)


def _ensure_published_guardrail(ops: OpsAI, spec: dict[str, Any], note: str) -> dict[str, Any]:
    name = str(spec["name"])
    found = find_guardrail(ops, name)
    if found is None:
        body = {key: spec[key] for key in ("name", "kind", "topics", "message", "scopes", "owner") if spec.get(key)}
        found = ops.raw.agents.agents_create_guardrail(body)
    gid = str(found["id"])
    detail = ops.raw.agents.agents_get_guardrail(gid)
    if detail.get("publishedVersion") is not None:
        return detail
    try:
        detail = ops.raw.agents.agents_request_guardrail_publish(
            gid, {"version": int(detail.get("version") or 1), "note": note}
        )
    except OpsError as exc:
        if exc.code not in {"cannot_request", "review_open"}:
            raise
        detail = ops.raw.agents.agents_get_guardrail(gid)
    _decide_publish(detail.get("pendingRequestId"), note)
    return ops.raw.agents.agents_get_guardrail(gid)


def _pin_folder_controls(
    ops: OpsAI, folder: Path, meta: dict[str, Any], bindings: dict[str, Any], agent_id: str
) -> int:
    note = f"Example {meta['id']}"
    skill_path = folder / "resources" / "skill.yaml"
    guardrail_path = folder / "resources" / "guardrail.yaml"
    if skill_path.is_file():
        skill = _ensure_published_skill(ops, dict(load_data(skill_path)), note)
        if not skill.get("publishedVersion"):
            print("NOT READY: skill is not published", file=sys.stderr)
            return 2
        bindings["skillId"] = skill["id"]
        bindings["skillVersion"] = skill["publishedVersion"]
    if guardrail_path.is_file():
        guardrail = _ensure_published_guardrail(ops, dict(load_data(guardrail_path)), note)
        if not guardrail.get("publishedVersion"):
            print("NOT READY: guardrail is not published", file=sys.stderr)
            return 2
        bindings["guardrailId"] = guardrail["id"]
        bindings["guardrailVersion"] = guardrail["publishedVersion"]
    if bindings.get("guardrailId"):
        ops.raw.agents.agents_update_agent(
            agent_id,
            {
                "guardrailPins": [
                    {
                        "guardrailId": bindings["guardrailId"],
                        "version": int(bindings["guardrailVersion"]),
                        "enabled": True,
                    }
                ]
            },
        )
    if bindings.get("skillId"):
        ops.raw.agents.agents_attach_skill(
            agent_id, str(bindings["skillId"]), {"version": int(bindings["skillVersion"])}
        )
    return 0


def _ensure_handbook(ops: OpsAI, page: Path | None) -> dict[str, Any]:
    if found := find_handbook(ops):
        return found
    kb = ops.knowledge.create({"name": "Account opening handbook"})
    if page is not None:
        ops.raw.kb.knowledge_bases_add_page(kb["id"], {"title": "Account opening", "text": page.read_text()})
    return kb


def _status(ops: OpsAI, folder: Path, meta: dict[str, Any]) -> int:
    path = folder / BINDINGS
    if not path.is_file():
        print(f"MISSING {meta['id']}")
        return 1
    print(f"FOUND {meta['id']}")
    return 0


def _remove(ops: OpsAI, folder: Path, meta: dict[str, Any]) -> int:
    path = folder / BINDINGS
    if not path.is_file():
        print(f"MISSING {meta['id']}")
        return 0
    bindings = json.loads(path.read_text())
    owns_workflow = meta.get("track") != "composition" or (folder / "resources" / "workflow.yaml").is_file()
    if owns_workflow and (workflow_id := bindings.get("workflowId")):
        try:
            ops.workflows.archive(workflow_id)
        except (OpsError, NotFound):
            pass
    path.unlink()
    print(f"REMOVED {meta['id']}")
    return 0


def _operation_names(definition: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for node in definition.get("nodes") or []:
        if node.get("type") != "ops.action.tool":
            continue
        name = str((node.get("parameters") or {}).get("operation") or "")
        if name:
            names.append(name)
    return names


def _code_source(records: dict[str, Any]) -> str:
    return (
        "RECORDS = " + json.dumps(records, indent=4) + "\n\ndef main(input):\n"
        "    rec = RECORDS.get(input.get('id'))\n"
        "    if rec is None:\n"
        "        raise ValueError('not found')\n"
        "    return rec\n"
    )


def _security_ops() -> OpsAI:
    env = _admin_env()
    email = env.get("OPS_DEMO_ADMIN_EMAIL") or env.get("OPS_BOOTSTRAP_ADMIN_EMAIL")
    password = env.get("OPS_DEMO_ADMIN_PASSWORD") or env.get("OPS_BOOTSTRAP_ADMIN_PASSWORD")
    if not email or not password:
        raise ValueError("no workspace admin in OPS_ADMIN_ENV or .run/dev-admin.env; run make up")
    signed = OpsAI.sign_in(email, password, **_conn())
    for team in signed.teams.list():
        name = str(team.get("name") or "")
        ident = str(team.get("id") or "")
        if name == "Security" or ident == "team_security":
            return signed.with_team(ident)
    raise ValueError("no Security team")


def _publish_tool_module(ops: OpsAI, module_id: str, note: str) -> None:
    detail = ops.raw.tools.tool_modules_get_module(module_id)
    if detail.get("status") == "published":
        return
    if not any(v.get("status") == "in_review" for v in detail.get("versions") or []):
        detail = ops.raw.tools.tool_modules_request_review(module_id, {"note": note})
    waiting = next((v for v in detail.get("versions") or [] if v.get("status") == "in_review"), None)
    if waiting is None:
        raise ValueError(f"tool module {module_id} did not enter review")
    review_id = str(waiting.get("reviewId") or waiting.get("review_id") or "")
    if not review_id:
        raise ValueError(f"tool module {module_id} review has no id")
    _security_ops().raw.agents.reviews_decide_publish_request(review_id, {"decision": "approved", "reason": note})
    published = ops.raw.tools.tool_modules_get_module(module_id)
    if published.get("status") != "published":
        raise ValueError(f"tool module {module_id} is {published.get('status')}, not published")


def _ensure_folder_tools(ops: OpsAI, folder: Path, definition: dict[str, Any], bindings: dict[str, Any]) -> int:
    path = folder / "resources" / "tools.yaml"
    needed = [name for name in _operation_names(definition) if name != READ_TOOL]
    if not path.is_file() or not needed:
        return 0
    spec = load_data(path)
    published = dict.fromkeys(needed, False)
    found_id = ""
    for module in ops.tools.list():
        detail = ops.tools.get(module["id"]) if module.get("id") else module
        names = {str(op.get("name")) for op in detail.get("operations") or []}
        if spec.get("name") and detail.get("name") == spec.get("name"):
            found_id = str(detail.get("id") or found_id)
        for name in needed:
            if name in names and detail.get("status") == "published":
                published[name] = True
                found_id = str(detail.get("id") or found_id)
    if all(published.values()):
        if found_id:
            bindings["codeModuleId"] = found_id
        return 0
    if not found_id:
        operations = list(spec.get("operations") or [])
        if not operations:
            print("NOT READY: resources/tools.yaml has no operations", file=sys.stderr)
            return 2
        first = operations[0]
        made = ops.raw.tools.tool_modules_create_module(
            {
                "name": spec["name"],
                "displayName": spec.get("displayName") or spec["name"],
                "system": spec.get("system") or spec["name"],
                "type": "code",
                "endpoint": "",
                "function": {
                    "name": first["name"],
                    "description": first.get("description") or first["name"],
                    "access": "read",
                    "input": [{"name": "id", "type": "string", "required": True}],
                    "code": {"source": _code_source(first.get("records") or {})},
                },
            }
        )
        found_id = str(made["id"])
        for extra in operations[1:]:
            ops.raw.tools.tool_modules_add_function(
                found_id,
                {
                    "name": extra["name"],
                    "description": extra.get("description") or extra["name"],
                    "access": "read",
                    "input": [{"name": "id", "type": "string", "required": True}],
                    "code": {"source": _code_source(extra.get("records") or {})},
                },
            )
    try:
        _publish_tool_module(ops, found_id, f"Example {bindings.get('id') or folder.name}")
    except Exception as exc:
        print(f"NOT READY: {exc}", file=sys.stderr)
        return 2
    bindings["codeModuleId"] = found_id
    return 0


def _needs_ai_steps(definition: dict[str, Any]) -> bool:
    return any(node.get("type") in MODEL_NODE_TYPES for node in definition.get("nodes") or [])


def _needs_read_tools(definition: dict[str, Any]) -> bool:
    reads = {READ_TOOL, "get_customer"}
    return any(
        node.get("type") == "ops.action.tool" and str((node.get("parameters") or {}).get("operation") or "") in reads
        for node in definition.get("nodes") or []
    )


def _needs_bound_agent(definition: dict[str, Any]) -> bool:
    return any(node.get("type") == "ops.ai.agent" for node in definition.get("nodes") or [])


def _needs_knowledge(definition: dict[str, Any]) -> bool:
    return any(node.get("type") == "ops.ai.knowledge" for node in definition.get("nodes") or [])


def _bind_knowledge_nodes(definition: dict[str, Any], kb_id: str) -> dict[str, Any]:
    bound = json.loads(json.dumps(definition))
    for node in bound.get("nodes") or []:
        if node.get("type") == "ops.ai.knowledge":
            node.setdefault("parameters", {})["kbIds"] = [kb_id]
    return bound


def _needs_extract(definition: dict[str, Any]) -> bool:
    return any(node.get("type") == "ops.ai.extract" for node in definition.get("nodes") or [])


def _bind_extract_nodes(definition: dict[str, Any], type_id: str, case_type: Any) -> dict[str, Any]:
    bound = json.loads(json.dumps(definition))
    for node in bound.get("nodes") or []:
        if node.get("type") == "ops.ai.extract" and type_id:
            node.setdefault("parameters", {})["documentType"] = {"id": type_id}
        if node.get("type") == "ops.action.openCase" and case_type:
            node.setdefault("parameters", {})["caseType"] = str(case_type)
    return bound


def _ensure_child_workflow(ops: OpsAI, folder: Path, meta: dict[str, Any], bindings: dict[str, Any]) -> int:
    path = folder / "resources" / "child.yaml"
    if not path.is_file():
        return 0
    check = ops.workflows.validate(path)
    if not check.ok:
        check.raise_for_errors()
    made = ops.workflows.apply(path)
    review = _publish_workflow(ops, str(made["workflowId"]), f"Example {meta['id']} child")
    bindings["childWorkflowId"] = made["workflowId"]
    bindings["childPublish"] = review
    if not _workflow_published(ops, str(made["workflowId"])):
        print(f"NOT READY: child workflow {made['workflowId']} is not published", file=sys.stderr)
        return 2
    return 0


def _ensure_extract_resources(ops: OpsAI, bindings: dict[str, Any]) -> int:
    doc = find_document_type(ops, *EXTRACT_DOC_TYPES)
    if not doc:
        print("NOT READY: no legal notice document type; run make sample-team", file=sys.stderr)
        return 2
    bindings["documentTypeId"] = doc["id"]
    if case := find_case_type(ops, *CLAIM_CASE_TYPES):
        bindings["caseTypeId"] = case["id"]
    return 0


def _ensure_ai_steps(ops: OpsAI) -> None:
    try:
        current = ops.raw.platform.policies_get_policy("aiSteps")
    except (NotFound, OpsError):
        current = {}
    if current.get("value") is True:
        return
    ops.raw.platform.policies_set_policy("aiSteps", {"value": True})


def _write_profile(ops: OpsAI, folder: Path) -> None:
    path = folder / ".ops-profile.json"
    path.write_text(
        json.dumps(
            {
                "current": "local",
                "profiles": {
                    "local": {
                        "baseUrl": ops.config.base_url,
                        "accessToken": ops.config.access_token,
                        "team": ops.config.team,
                        "services": ops.config.services,
                    }
                },
            },
            indent=2,
        )
        + "\n"
    )


def _ready(bindings: dict[str, Any], meta: dict[str, Any]) -> None:
    if bindings.get("workflowId") and meta.get("track") == "workflow":
        workflow_id = bindings["workflowId"]
        print(f"UI /workflows/definitions/{workflow_id}")
        fixture = (meta.get("fixtures") or ["fixtures/valid.json"])[0]
        caps = {str(item.get("id")) for item in (meta.get("capabilities") or []) if isinstance(item, dict)}
        if "ops.trigger.email" in caps or str(meta.get("id") or "").startswith("email"):
            print(f"CLI OPS_CONFIG=.ops-profile.json opsai workflows send-test-email {workflow_id} --event {fixture}")
            print(f"PY  ops.workflows.send_test_email({workflow_id!r}, event={{...}}, mode='test')")
        elif "ops.trigger.event" in caps:
            print(
                "CLI delete a team file (ops.raw.files.files_delete_file); "
                "file.deleted starts system workflow file_deleted_purge"
            )
            print("PY  ops.raw.files.files_delete_file(file_id)  # system/event-started; not startable by hand")
        else:
            print(f"CLI OPS_CONFIG=.ops-profile.json opsai workflows run {workflow_id} --input {fixture} --test --wait")
            print(f"PY  ops.workflows.run({workflow_id!r}, input={{...}}, mode='test', wait=True)")
    if bindings.get("knowledgeId"):
        print(f"PY  ops.knowledge.search({{'kbIds': [{bindings['knowledgeId']!r}], 'question': 'beneficial owners'}})")
    if bindings.get("moduleId"):
        print(
            f"PY  ops.raw.tools.tool_modules_run_tool({bindings['moduleId']!r}, {READ_TOOL!r}, {{'mode': 'real', 'input': {{'query': 'ada@example.test'}}}})"
        )
    if bindings.get("agentId") and meta.get("track") == "chat":
        print("PY  ops.agents.chat(<published id>, message)")
        print("CLI opsai chat send  # Planned")
    if bindings.get("agentId") and meta.get("track") == "agent":
        agent_id = bindings["agentId"]
        print(f"UI /agents/{agent_id}")
        print(f'CLI opsai agents chat {agent_id} --message "What documents open a business account?"')
        print(f"PY  ops.agents.chat({agent_id!r}, message)")
        print("CLI opsai chat send  # Planned")
    if (
        meta.get("track") == "composition"
        and bindings.get("workflowId")
        and (meta.get("entrypoint") or "").endswith("workflow.yaml")
    ):
        workflow_id = bindings["workflowId"]
        print(f"UI /workflows/definitions/{workflow_id}")
        print(
            f"CLI OPS_CONFIG=.ops-profile.json opsai workflows run {workflow_id} --input fixtures/ask.json --test --wait"
        )
        print(f"PY  ops.workflows.run({workflow_id!r}, input={{...}}, mode='test', wait=True)")
    if (
        meta.get("track") == "composition"
        and bindings.get("agentId")
        and (meta.get("entrypoint") or "").endswith("agent.yaml")
    ):
        agent_id = bindings["agentId"]
        print(f"UI /agents/{agent_id}")
        print(
            f'CLI opsai agents chat {agent_id} --message "Normalize this: ada@example.test / Card / Where is my refund?"'
        )
        print(f"PY  ops.agents.chat({agent_id!r}, message)")
