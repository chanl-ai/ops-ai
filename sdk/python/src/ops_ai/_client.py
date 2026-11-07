"""`OpsAI` and `AsyncOpsAI`: the core nouns by name, the Apps area in the screen's words (`apps`, `credentials`,
`accounts`, `tools`, `resources`, `usage`), `raw` for every other public operation.

from ops_ai import OpsAI

ops = OpsAI(api_key="ok_...", base_url="https://ops.example.com", team="team_claims")
for agent in ops.agents.list():
    print(agent["name"])
run = ops.runs.start("wf_card_dispute", input={"account": "123"})
done = ops.runs.wait(run["runId"])        # returns when the run ends or stops at a human task
if done.get("taskId"):
    ops.tasks.decide(done["taskId"], "approve")
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

import httpx

from ._agents import Agents, AsyncAgents
from ._chat import AsyncChat, Chat
from ._config import Config, Session
from ._generated.agents.operations import AsyncOperations as AsyncAgentsOps
from ._generated.agents.operations import Operations as AgentsOps
from ._generated.documents.operations import AsyncOperations as AsyncDocumentsOps
from ._generated.documents.operations import Operations as DocumentsOps
from ._generated.files.operations import AsyncOperations as AsyncFilesOps
from ._generated.files.operations import Operations as FilesOps
from ._generated.kb.operations import AsyncOperations as AsyncKbOps
from ._generated.kb.operations import Operations as KbOps
from ._generated.platform.operations import AsyncOperations as AsyncPlatformOps
from ._generated.platform.operations import Operations as PlatformOps
from ._generated.tools.operations import AsyncOperations as AsyncToolsOps
from ._generated.tools.operations import Operations as ToolsOps
from ._models import AsyncModels, Models
from ._transport import AsyncTransport, Transport, _headers, _result, page_items
from ._words import (
    Accounts,
    Apps,
    AsyncAccounts,
    AsyncApps,
    AsyncCredentials,
    AsyncResources,
    AsyncTools,
    AsyncUsage,
    Credentials,
    Resources,
    Tools,
    Usage,
)
from ._workflows import AsyncWorkflows, Workflows

# A run is over in these states; `waiting` means it stopped at a step that waits on a person or another system.
TERMINAL = ("succeeded", "failed", "cancelled")


@dataclass(frozen=True)
class Noun:
    """Which generated operation each verb of a resource calls. One table, read by both clients."""

    service: str
    list: str | None = None
    get: str | None = None
    create: str | None = None


NOUNS: dict[str, Noun] = {
    "teams": Noun("platform", list="teams_list_teams"),
    "agents": Noun("agents", list="agents_list_agents", get="agents_get_agent", create="agents_create_agent"),
    "workflows": Noun("agents", list="workflows_list_workflows", get="workflows_get_workflow"),
    "threads": Noun("agents", list="threads_list_threads", get="threads_thread_state", create="threads_create_thread"),
    "cases": Noun("agents", list="cases_list_cases", get="cases_get_case", create="cases_open_case"),
    "tools": Noun("tools", list="tool_modules_list_modules", get="tool_modules_get_module"),
    "knowledge": Noun(
        "kb",
        list="knowledge_bases_list_knowledge_bases",
        get="knowledge_bases_get_knowledge_base",
        create="knowledge_bases_create_knowledge_base",
    ),
    "files": Noun("files", list="files_list_files", get="files_get_file"),
    "runs": Noun("agents", list="workflows_list_engine_runs", get="workflows_get_engine_run"),
    "tasks": Noun("agents", list="reviews_list_reviews", get="reviews_get_review"),
}


def _with_task(run: dict[str, Any]) -> dict[str, Any]:
    """A waiting run's human task, as `taskId`, so the next call is `tasks.decide`."""
    waiting = run.get("waiting") or {}
    task = (waiting.get("payload") or {}).get("review_id")
    return {**run, "taskId": task} if task else run


def _upload_meta(name: str, content: bytes, mime: str, purpose: str) -> tuple[dict[str, Any], str]:
    digest = hashlib.sha256(content).hexdigest()
    meta = {"name": name, "size": len(content), "mime": mime, "purpose": purpose, "digest": digest}
    # The key names the whole upload, not only its bytes: the same bytes under another name or purpose are another
    # upload, which the files service refuses under a key it has seen.
    key = hashlib.sha256(f"{digest}\n{purpose}\n{mime}\n{name}".encode()).hexdigest()
    return meta, f"sdk-{key[:32]}"


class Raw:
    """Every public operation, by service and operationId: `ops.raw.agents.agents_list_agents(page=2)`."""

    def __init__(self, t: Transport) -> None:
        self.platform, self.agents, self.tools = PlatformOps(t), AgentsOps(t), ToolsOps(t)
        self.kb, self.files, self.documents = KbOps(t), FilesOps(t), DocumentsOps(t)


class AsyncRaw:
    def __init__(self, t: AsyncTransport) -> None:
        self.platform, self.agents, self.tools = AsyncPlatformOps(t), AsyncAgentsOps(t), AsyncToolsOps(t)
        self.kb, self.files, self.documents = AsyncKbOps(t), AsyncFilesOps(t), AsyncDocumentsOps(t)


class Resource:
    def __init__(self, raw: Raw, noun: Noun) -> None:
        self._raw, self._noun = raw, noun

    def _op(self, verb: str) -> Any:
        op_id = getattr(self._noun, verb)
        if not op_id:
            raise AttributeError(f"{verb} is not offered here; use ops.raw.{self._noun.service}")
        return getattr(getattr(self._raw, self._noun.service), op_id)

    def list(self, **query: Any) -> Iterator[Any]:
        """Every item, page after page, whichever paging the route uses."""
        call, nxt = self._op("list"), {}
        while True:
            items, nxt = page_items(call(**{**query, **nxt}))
            yield from items
            if nxt is None:
                return

    def get(self, id: str) -> Any:
        return self._op("get")(id)

    def create(self, body: Any) -> Any:
        return self._op("create")(body)


class AsyncResource:
    def __init__(self, raw: AsyncRaw, noun: Noun) -> None:
        self._raw, self._noun = raw, noun

    def _op(self, verb: str) -> Any:
        op_id = getattr(self._noun, verb)
        if not op_id:
            raise AttributeError(f"{verb} is not offered here; use ops.raw.{self._noun.service}")
        return getattr(getattr(self._raw, self._noun.service), op_id)

    async def list(self, **query: Any) -> AsyncIterator[Any]:
        call, nxt = self._op("list"), {}
        while True:
            items, nxt = page_items(await call(**{**query, **nxt}))
            for item in items:
                yield item
            if nxt is None:
                return

    async def get(self, id: str) -> Any:
        return await self._op("get")(id)

    async def create(self, body: Any) -> Any:
        return await self._op("create")(body)


class Runs(Resource):
    def start(self, workflow_id: str, *, input: dict[str, Any] | None = None, **fields: Any) -> Any:
        """Starts a run of the workflow's current version; `fields` takes `version`, `runKey` and `mode`."""
        return self._raw.agents.workflows_start_engine_run({"workflowId": workflow_id, "input": input or {}, **fields})

    def wait(self, run_id: str, *, timeout: float = 600.0, interval: float = 1.0) -> dict[str, Any]:
        """The run once it has ended or stopped at a human task (then `taskId` names the task)."""
        deadline = time.monotonic() + timeout
        while True:
            run = self._raw.agents.workflows_get_engine_run(run_id)
            if run["status"] in TERMINAL or run["status"] == "waiting":
                return _with_task(run)
            if time.monotonic() > deadline:
                raise TimeoutError(f"run {run_id} is still {run['status']} after {timeout:.0f}s")
            time.sleep(interval)

    def stream(self, run_id: str, *, after: str | None = None) -> Iterator[dict[str, Any]]:
        """The run's events as they happen, until it ends or waits."""
        return self._raw.agents.workflows_engine_run_events(run_id, after=after, follow=True)

    def cancel(self, run_id: str) -> Any:
        return self._raw.agents.workflows_cancel_engine_run(run_id)

    def retry(self, run_id: str) -> Any:
        """Queues a Stuck run again from its last recorded step; nothing it sent is sent again."""
        return self._raw.agents.workflows_retry_engine_run(run_id)

    def run_set_aside_email(self, event_id: str) -> Any:
        """Starts the run of an email the mailbox listener set aside, under the email's own run key."""
        return self._raw.agents.workflows_run_set_aside_email(event_id)


class AsyncRuns(AsyncResource):
    async def start(self, workflow_id: str, *, input: dict[str, Any] | None = None, **fields: Any) -> Any:
        body = {"workflowId": workflow_id, "input": input or {}, **fields}
        return await self._raw.agents.workflows_start_engine_run(body)

    async def wait(self, run_id: str, *, timeout: float = 600.0, interval: float = 1.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            run = await self._raw.agents.workflows_get_engine_run(run_id)
            if run["status"] in TERMINAL or run["status"] == "waiting":
                return _with_task(run)
            if time.monotonic() > deadline:
                raise TimeoutError(f"run {run_id} is still {run['status']} after {timeout:.0f}s")
            await asyncio.sleep(interval)

    async def stream(self, run_id: str, *, after: str | None = None) -> AsyncIterator[dict[str, Any]]:
        return await self._raw.agents.workflows_engine_run_events(run_id, after=after, follow=True)

    async def cancel(self, run_id: str) -> Any:
        return await self._raw.agents.workflows_cancel_engine_run(run_id)

    async def retry(self, run_id: str) -> Any:
        """Queues a Stuck run again from its last recorded step; nothing it sent is sent again."""
        return await self._raw.agents.workflows_retry_engine_run(run_id)

    async def run_set_aside_email(self, event_id: str) -> Any:
        """Starts the run of an email the mailbox listener set aside, under the email's own run key."""
        return await self._raw.agents.workflows_run_set_aside_email(event_id)


class Tasks(Resource):
    """Human tasks. The API calls them reviews (`reviews_*`); the console and this SDK say task."""

    def decide(self, task_id: str, decision: str, *, reason: str | None = None, **fields: Any) -> Any:
        """Sends one of the actions the task offers. The approval token is the server's to issue; nothing here makes
        one."""
        body = {"decision": decision, **({"reason": reason} if reason else {}), **fields}
        return self._raw.agents.reviews_decide(task_id, body)


class AsyncTasks(AsyncResource):
    async def decide(self, task_id: str, decision: str, *, reason: str | None = None, **fields: Any) -> Any:
        body = {"decision": decision, **({"reason": reason} if reason else {}), **fields}
        return await self._raw.agents.reviews_decide(task_id, body)


class Files(Resource):
    def upload(self, name: str, content: bytes, *, mime: str, purpose: str, transport: Transport) -> Any:
        """Uploads bytes the way the console does: a ticket, the bytes, then complete. The same bytes again answer
        the file already stored."""
        meta, key = _upload_meta(name, content, mime, purpose)
        ticket = self._raw.files.files_create_upload(meta, idempotency_key=key)
        if ticket.get("uploadUrl"):
            headers = {**_headers(transport.config, {}), **(ticket.get("headers") or {})}
            put = transport.http.put(ticket["uploadUrl"], headers=headers, content=content)
            if put.status_code != 409:  # 409: an earlier call stored these bytes under the same key
                _result(put)
        done = self._raw.files.files_complete_upload(ticket["fileId"])
        return done.get("file") or done


class AsyncFiles(AsyncResource):
    async def upload(self, name: str, content: bytes, *, mime: str, purpose: str, transport: AsyncTransport) -> Any:
        meta, key = _upload_meta(name, content, mime, purpose)
        ticket = await self._raw.files.files_create_upload(meta, idempotency_key=key)
        if ticket.get("uploadUrl"):
            headers = {**_headers(transport.config, {}), **(ticket.get("headers") or {})}
            put = await transport.http.put(ticket["uploadUrl"], headers=headers, content=content)
            if put.status_code != 409:
                _result(put)
        done = await self._raw.files.files_complete_upload(ticket["fileId"])
        return done.get("file") or done


class Knowledge(Resource):
    def search(self, body: dict[str, Any]) -> Any:
        return self._raw.kb.knowledge_bases_search_knowledge(body)


class AsyncKnowledge(AsyncResource):
    async def search(self, body: dict[str, Any]) -> Any:
        return await self._raw.kb.knowledge_bases_search_knowledge(body)


class OpsAI:
    """The synchronous client. Arguments win over OPS_* environment variables, which win over the ops CLI's profile."""

    def __init__(self, *, http: httpx.Client | None = None, **config: Any) -> None:
        self.config = Config.resolve(**config)
        self._t = Transport(self.config, http)
        self.raw = Raw(self._t)
        self.teams, self.threads, self.cases = (Resource(self.raw, NOUNS[n]) for n in ("teams", "threads", "cases"))
        self.knowledge = Knowledge(self.raw, NOUNS["knowledge"])
        self.files = Files(self.raw, NOUNS["files"])
        self.runs = Runs(self.raw, NOUNS["runs"])
        self.tasks = Tasks(self.raw, NOUNS["tasks"])
        self.agents = Agents(self.raw)
        self.workflows = Workflows(self.raw, self.runs)
        # The Apps area in the screen's words.
        self.apps = Apps(self.raw)
        self.credentials = Credentials(self.raw, self.apps)
        self.accounts = Accounts(self.raw, self.apps)
        self.tools = Tools(self.raw, self.apps, Resource(self.raw, NOUNS["tools"]))
        self.resources = Resources(self.raw)
        self.usage = Usage(self.raw)
        # The chat screen's routes and the model settings', which the generated layer does not hold.
        self.chat = Chat(self.raw)
        self.models = Models(self.raw)

    @classmethod
    def sign_in(cls, email: str, password: str, **config: Any) -> OpsAI:
        """A client acting as a person, from their email and password. A session carries the teams the person was in
        when it was made, so sign in again after joining a team."""
        anonymous = cls(**{**config, "access_token": "", "team": config.get("team") or ""})
        session = anonymous.raw.platform.auth_sign_in({"email": email, "password": password})
        anonymous.close()
        tokens = Session(session["token"], session["refreshToken"])
        return cls(**{**config, "access_token": session["token"], "team": config.get("team") or "", "session": tokens})

    def upload(self, name: str, content: bytes, *, mime: str, purpose: str) -> Any:
        return self.files.upload(name, content, mime=mime, purpose=purpose, transport=self._t)

    def with_team(self, team: str) -> OpsAI:
        """The same credential and address, acting in another team."""
        c = self.config
        # The same session and connections: a renewed token reaches both clients, and closing this one keeps them.
        return OpsAI(
            http=self._t.http,
            api_key=c.api_key,
            access_token=c.access_token,
            base_url=c.base_url,
            team=team,
            services=c.services,
            session=c.session,
        )

    def close(self) -> None:
        self._t.close()

    def __enter__(self) -> OpsAI:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class AsyncOpsAI:
    """The asynchronous client, the same surface as `OpsAI` with every call awaited."""

    def __init__(self, *, http: httpx.AsyncClient | None = None, **config: Any) -> None:
        self.config = Config.resolve(**config)
        self._t = AsyncTransport(self.config, http)
        self.raw = AsyncRaw(self._t)
        self.teams, self.threads, self.cases = (
            AsyncResource(self.raw, NOUNS[n]) for n in ("teams", "threads", "cases")
        )
        self.knowledge = AsyncKnowledge(self.raw, NOUNS["knowledge"])
        self.files = AsyncFiles(self.raw, NOUNS["files"])
        self.runs = AsyncRuns(self.raw, NOUNS["runs"])
        self.tasks = AsyncTasks(self.raw, NOUNS["tasks"])
        self.agents = AsyncAgents(self.raw)
        self.workflows = AsyncWorkflows(self.raw, self.runs)
        self.apps = AsyncApps(self.raw)
        self.credentials = AsyncCredentials(self.raw, self.apps)
        self.accounts = AsyncAccounts(self.raw, self.apps)
        self.tools = AsyncTools(self.raw, self.apps, AsyncResource(self.raw, NOUNS["tools"]))
        self.resources = AsyncResources(self.raw)
        self.usage = AsyncUsage(self.raw)
        self.chat = AsyncChat(self.raw)
        self.models = AsyncModels(self.raw)

    @classmethod
    async def sign_in(cls, email: str, password: str, **config: Any) -> AsyncOpsAI:
        anonymous = cls(**config)
        session = await anonymous.raw.platform.auth_sign_in({"email": email, "password": password})
        await anonymous.close()
        tokens = Session(session["token"], session["refreshToken"])
        return cls(**{**config, "access_token": session["token"], "session": tokens})

    async def upload(self, name: str, content: bytes, *, mime: str, purpose: str) -> Any:
        return await self.files.upload(name, content, mime=mime, purpose=purpose, transport=self._t)

    def with_team(self, team: str) -> AsyncOpsAI:
        c = self.config
        # The same session and connections: a renewed token reaches both clients, and closing this one keeps them.
        return AsyncOpsAI(
            http=self._t.http,
            api_key=c.api_key,
            access_token=c.access_token,
            base_url=c.base_url,
            team=team,
            services=c.services,
            session=c.session,
        )

    async def close(self) -> None:
        await self._t.close()

    async def __aenter__(self) -> AsyncOpsAI:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
