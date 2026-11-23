"""Public noun return annotations stay typed (not Any) across the builder-facing surface.

Behaviour of `runs.wait(check=)` is covered in test_client.py. Live local/staging proof is
`make sdk-typed-proof AS=builder [ENV=staging]`; a failed-run walk is
`make usecase-test UC=uc-workflows-2 LAYER=sdk`.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

import ops_ai
from ops_ai import (
    Agent,
    AgentBackgroundRun,
    AgentChatReply,
    CasePage,
    CaseRow,
    CaseView,
    ChatEvent,
    ChatThread,
    DefinitionPublished,
    DefinitionRow,
    DefinitionView,
    FileDetail,
    FileRow,
    FormView,
    Guardrail,
    InboxItem,
    KnowledgeBaseDetail,
    KnowledgeBaseRow,
    OpsAI,
    RunDetail,
    RunFailed,
    RunRow,
    RunStarted,
    SearchOut,
    Skill,
    SkillCreateInput,
    SkillDetail,
    TeamOut,
    ThreadCreated,
    ThreadReview,
    ThreadState,
    ThreadView,
    WaitedRun,
    WidgetTemplateOut,
)
from ops_ai._agents import Agents, AsyncAgents
from ops_ai._chat import AsyncChat, Chat
from ops_ai._client import (
    AsyncFiles,
    AsyncKnowledge,
    AsyncRuns,
    AsyncSkills,
    AsyncTasks,
    AsyncThreads,
    Cases,
    Files,
    Knowledge,
    Runs,
    Skills,
    Tasks,
    Threads,
)
from ops_ai._types import PublishReview, TaskItem
from ops_ai._workflows import AsyncWorkflows, Workflows


def _return(method: Any) -> Any:
    return get_type_hints(method)["return"]


def _is_any(hint: Any) -> bool:
    return hint is Any


def _iterator_item(hint: Any) -> Any:
    origin = get_origin(hint)
    if origin in (Iterator, AsyncIterator):
        args = get_args(hint)
        return args[0] if args else Any
    return hint


def _union_members(hint: Any) -> set[Any]:
    args = get_args(hint)
    return set(args) if args else {hint}


def _is_task_item(hint: Any) -> bool:
    return hint is TaskItem or _union_members(hint) == {ThreadReview, PublishReview}


def test_package_exports_builder_types() -> None:
    for name, typ in (
        ("Agent", Agent),
        ("Skill", Skill),
        ("SkillDetail", SkillDetail),
        ("SkillCreateInput", SkillCreateInput),
        ("AgentChatReply", AgentChatReply),
        ("AgentBackgroundRun", AgentBackgroundRun),
        ("ChatThread", ChatThread),
        ("ChatEvent", ChatEvent),
        ("RunStarted", RunStarted),
        ("WaitedRun", WaitedRun),
        ("RunFailed", RunFailed),
        ("CaseRow", CaseRow),
        ("TeamOut", TeamOut),
        ("Guardrail", Guardrail),
        ("WidgetTemplateOut", WidgetTemplateOut),
        ("FileRow", FileRow),
        ("KnowledgeBaseRow", KnowledgeBaseRow),
        ("DefinitionRow", DefinitionRow),
        ("FormView", FormView),
        ("InboxItem", InboxItem),
    ):
        assert typ.__name__ == name
    assert ops_ai.RunFailed is RunFailed


def test_agents_public_returns_are_typed() -> None:
    assert _iterator_item(_return(Agents.list)) is Agent
    assert _return(Agents.get) is Agent
    assert _return(Agents.create) is Agent
    assert _return(Agents.update) is Agent
    assert _return(Agents.apply) is Agent
    assert _return(Agents.chat) is AgentChatReply
    assert not _is_any(_return(Agents.publish))
    assert not _is_any(_return(Agents.add_reference))
    members = _union_members(_return(Agents.run))
    assert AgentChatReply in members
    assert AgentBackgroundRun in members


def test_async_agents_public_returns_are_typed() -> None:
    assert _iterator_item(_return(AsyncAgents.list)) is Agent
    assert _return(AsyncAgents.get) is Agent
    assert _return(AsyncAgents.create) is Agent
    assert _return(AsyncAgents.chat) is AgentChatReply


def test_skills_public_returns_are_typed() -> None:
    assert _iterator_item(_return(Skills.list)) is Skill
    assert _return(Skills.get) is SkillDetail
    assert _return(Skills.create) is SkillDetail
    assert _return(Skills.save_draft) is SkillDetail
    assert _return(Skills.publish) is SkillDetail


def test_async_skills_public_returns_are_typed() -> None:
    assert _iterator_item(_return(AsyncSkills.list)) is Skill
    assert _return(AsyncSkills.get) is SkillDetail
    assert _return(AsyncSkills.create) is SkillDetail
    assert _return(AsyncSkills.save_draft) is SkillDetail
    assert _return(AsyncSkills.publish) is SkillDetail


def test_chat_public_returns_are_typed() -> None:
    assert _return(Chat.start) is ChatThread
    assert _return(Chat.get) is ChatThread
    assert _iterator_item(_return(Chat.say)) is ChatEvent


def test_async_chat_public_returns_are_typed() -> None:
    assert _return(AsyncChat.start) is ChatThread
    assert _return(AsyncChat.get) is ChatThread
    assert _iterator_item(_return(AsyncChat.say)) is ChatEvent


def test_resource_generics_are_concrete_on_subclasses() -> None:
    assert _iterator_item(_return(Threads.list)) is ThreadView
    assert _return(Threads.get) is ThreadState
    assert _return(Threads.create) is ThreadCreated
    inbox = _return(Threads.inbox)
    assert get_origin(inbox) is list and get_args(inbox)[0] is InboxItem

    assert _iterator_item(_return(Cases.list)) is CaseRow
    assert _return(Cases.get) is CasePage
    assert _return(Cases.create) is CaseView

    assert _iterator_item(_return(Runs.list)) is RunRow
    assert _return(Runs.get) is RunDetail
    assert _return(Runs.start) is RunStarted
    assert _return(Runs.wait) is WaitedRun
    assert _return(Runs.cancel) is RunRow
    assert _return(Runs.retry) is RunRow
    assert _return(Runs.redrive) is RunRow
    assert "check" in inspect.signature(Runs.wait).parameters
    assert inspect.signature(Runs.wait).parameters["check"].default is False

    assert _is_task_item(_iterator_item(_return(Tasks.list)))
    assert _is_task_item(_return(Tasks.decide))

    assert _iterator_item(_return(Files.list)) is FileRow
    assert _return(Files.get) is FileDetail
    assert _return(Files.upload) is FileDetail

    assert _iterator_item(_return(Knowledge.list)) is KnowledgeBaseRow
    assert _return(Knowledge.get) is KnowledgeBaseDetail
    assert _return(Knowledge.search) is SearchOut


def test_async_resource_subclasses_are_typed() -> None:
    assert _iterator_item(_return(AsyncThreads.list)) is ThreadView
    assert _return(AsyncThreads.get) is ThreadState
    assert _return(AsyncRuns.start) is RunStarted
    assert _return(AsyncRuns.wait) is WaitedRun
    assert "check" in inspect.signature(AsyncRuns.wait).parameters
    assert _return(AsyncRuns.redrive) is RunRow
    assert _is_task_item(_return(AsyncTasks.decide))
    assert _return(AsyncFiles.upload) is FileDetail
    assert _return(AsyncKnowledge.search) is SearchOut


def test_workflows_public_returns_are_typed() -> None:
    assert _iterator_item(_return(Workflows.list)) is DefinitionRow
    assert _iterator_item(_return(Workflows.forms)) is FormView
    assert _return(Workflows.get) is DefinitionView
    assert _return(Workflows.get_definition) is DefinitionView
    assert _return(Workflows.apply) is DefinitionPublished
    assert not _is_any(_return(Workflows.publish))
    members = _union_members(_return(Workflows.run))
    assert RunStarted in members and WaitedRun in members


def test_async_workflows_public_returns_are_typed() -> None:
    assert _iterator_item(_return(AsyncWorkflows.list)) is DefinitionRow
    assert _return(AsyncWorkflows.get) is DefinitionView
    assert _return(AsyncWorkflows.apply) is DefinitionPublished
    members = _union_members(_return(AsyncWorkflows.run))
    assert RunStarted in members and WaitedRun in members


def test_opsai_resource_attributes_are_parameterized() -> None:
    """OpsAI pins each Resource noun to concrete row/detail types (not bare Resource)."""
    hints = get_type_hints(OpsAI)
    assert get_args(hints["teams"]) == (TeamOut, TeamOut)
    assert get_args(hints["guardrails"]) == (Guardrail, Guardrail)
    assert get_args(hints["widgets"]) == (WidgetTemplateOut, WidgetTemplateOut)
    assert hints["cases"] is Cases
    assert hints["runs"] is Runs
    assert hints["tasks"] is Tasks
    assert hints["files"] is Files
    assert hints["knowledge"] is Knowledge


def test_resource_bases_do_not_use_pep695_type_params() -> None:
    """class Resource[T] is 3.12-only; the SDK promises 3.11 via Generic[TRow, TDetail]."""
    client_src = Path(ops_ai.__file__).resolve().parent / "_client.py"
    tree = ast.parse(client_src.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in ("Resource", "AsyncResource"):
            assert not getattr(node, "type_params", None), f"{node.name} uses PEP 695 type parameters"


def test_import_ops_ai_on_python_311_when_available() -> None:
    """When uv can resolve Python 3.11, import ops_ai must succeed on that interpreter."""
    sdk_root = Path(__file__).resolve().parents[1]
    cmd = [
        "uv",
        "run",
        "--python",
        "3.11",
        "--no-project",
        "--with-editable",
        str(sdk_root),
        "python",
        "-c",
        "import ops_ai; from ops_ai import OpsAI, RunFailed, WaitedRun",
    ]
    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return
    err = (completed.stderr or "") + (completed.stdout or "")
    if completed.returncode != 0 and (
        "No interpreter" in err
        or "could not find" in err.lower()
        or "download-python" in err.lower()
        or "requires-python" in err.lower()
    ):
        return
    assert completed.returncode == 0, err
