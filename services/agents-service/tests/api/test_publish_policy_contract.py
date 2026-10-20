"""Every publish follows the one publish-policy module (c-086, api/publish_policy.py), by failure mode: a new publish
route deciding a review its own way, a route that stops asking, a route that asks and then ignores the answer, and a
second copy of the dev auto-approve rule. The static checks read the app's routes and the source; the behaviour check
publishes on every route under "major" with dev auto-approve on (live at once) and under "always" (a review opens)."""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from httpx import AsyncClient, Response

from ops_agents.api import deployment_reviews, engine_lifecycle
from ops_agents.api.app import create_app
from ops_agents.api.routers import agents, channel_list, graphs, guardrails, skills, widgets, workflows
from ops_service_kit.settings import Settings
from tests.api.test_engine_definitions import basic
from tests.api.test_graph_versions import definition as graph_definition
from tests.api.test_publish_policy import _stack, fresh_modes, set_mode  # noqa: F401  # pyright: ignore[reportPrivateUsage, reportUnusedImport]
from tests.api.test_skills import HARDSHIP
from tests.api.test_widget_registry import LIMIT_CARD
from tests.engine.test_lifecycle_rights import BUILDER

SRC = Path(__file__).resolve().parents[2] / "src" / "ops_agents"
POLICY = SRC / "api" / "publish_policy.py"
# Each publish route, and the function on its path that asks the policy (the route itself, or the helper it calls).
PUBLISH_ROUTES: dict[str, Callable[..., Any]] = {
    "/v1/agents/{agent_id}/publish-requests": agents.request_publish,
    "/v1/workflows/{workflow_id}/publish-requests": workflows.request_publish,
    "/v1/workflows/definitions/{workflow_id}/publish-requests": engine_lifecycle.request_publish,
    "/v1/guardrails/{guardrail_id}/publish-requests": guardrails.request_guardrail_publish,
    "/v1/skills/{skill_id}/publish-requests": skills._request_review,  # pyright: ignore[reportPrivateUsage]
    "/v1/widgets/{widget_id}/publish-requests": widgets.request_widget_publish,
    "/v1/graphs/{name}/versions": graphs.publish_version,
}
# Names the policy is imported under, and agents' one wrapper the publish and its preview share.
# engine_lifecycle.open_publish asks decide for a person's publish and a shipped workflow's update alike (tick 30).
ASKS = {"decide", "review_needed", "_publish_decision", "open_publish"}
# Opens a request without asking: a seed's change outside dev, which always waits, and records reviewRequired.
SEED_ONLY = {
    ("workflow_registry.py", "_seed_for_review"),
    # tools-service decides whether a tool module version needs review and opens it here (c-163), for the person
    # publishing or, for its seed's waiting versions, on their behalf (c-222). Neither decides anything in
    # agents-service.
    ("tool_module_reviews.py", "open_review"),
    ("tool_module_reviews.py", "open_for"),
}
# Routes that open a review another service decided on.
OPENS_ONLY = {"/v1/publish-requests"}


def _calls(fn: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            out.add(f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else "")
    return out


def publish_paths() -> set[str]:
    app = create_app(Settings(database_url="sqlite+aiosqlite://"))
    out: set[str] = set()
    for ctx in iter_route_contexts(app.routes):
        r = ctx.original_route
        path = ctx.path or getattr(r, "path", "")
        if (
            isinstance(r, APIRoute)
            and "POST" in (r.methods or set[str]())
            and (path.endswith("/publish-requests") or (path.startswith("/v1/graphs/") and path.endswith("/versions")))
        ):
            out.add(path)
    return out


def test_every_publish_route_is_listed() -> None:
    assert publish_paths() - OPENS_ONLY == set(PUBLISH_ROUTES), (
        "a new publish route must ask the publish policy and be listed here"
    )


def test_each_publish_route_asks_the_policy() -> None:
    for path, fn in PUBLISH_ROUTES.items():
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        assert _calls(tree) & ASKS, f"{path}: {fn.__qualname__} does not ask publish_policy.decide"


def test_a_deployment_change_asks_the_policy() -> None:
    """A chat channel's origins and served version change through PATCH /v1/channels/{id}, not a publish route."""
    assert "change" in _calls(ast.parse(textwrap.dedent(inspect.getsource(channel_list.update_channel))))
    tree = ast.parse(textwrap.dedent(inspect.getsource(deployment_reviews.change)))
    assert _calls(tree) & ASKS, "deployment_reviews.change applies origins without asking publish_policy.decide"


def test_no_other_code_decides_a_review() -> None:
    for path in SRC.rglob("*.py"):
        if path == POLICY:
            continue
        text = path.read_text()
        assert "auto_approves" not in text, f"{path.relative_to(SRC)} keeps its own auto-approve rule"
        assert "registry_auto_approve" not in text, f"{path.relative_to(SRC)} reads the auto-approve setting itself"
        for fn in ast.walk(ast.parse(text)):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and "open_request" in _calls(fn):
                if (path.name, fn.name) in SEED_ONLY:
                    continue
                assert _calls(fn) & ASKS, f"{path.relative_to(SRC)}:{fn.name} opens a publish request without asking"


def _made(r: Response) -> dict[str, Any]:
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]


async def _agent(c: AsyncClient) -> Response:
    a = _made(await c.post("/v1/agents", json={"name": "Payee checker", "role": "Checks payees"}, headers=BUILDER))
    return await c.post(f"/v1/agents/{a['id']}/publish-requests", json={"version": 1}, headers=BUILDER)


async def _workflow(c: AsyncClient) -> Response:
    body = {"name": "Hold check", "trigger": "Manual", "template": "blank"}
    w = _made(await c.post("/v1/workflows", json=body, headers=BUILDER))
    graph = _made(await c.get(f"/v1/workflows/{w['id']}", headers=BUILDER))["draft"]["graph"]
    return await c.post(f"/v1/workflows/{w['id']}/publish-requests", json={"graph": graph}, headers=BUILDER)


async def _definition(c: AsyncClient) -> Response:
    d = _made(await c.post("/v1/workflows/definitions", json={"definition": basic()}, headers=BUILDER))
    return await c.post(f"/v1/workflows/definitions/{d['workflowId']}/publish-requests", json={}, headers=BUILDER)


async def _guardrail(c: AsyncClient) -> Response:
    rule = {
        "name": "No investment advice",
        "topics": ["investment advice"],
        "message": "I can't give investment advice.",
    }
    g = _made(await c.post("/v1/guardrails", json=rule, headers=BUILDER))
    return await c.post(f"/v1/guardrails/{g['id']}/publish-requests", json={"version": 1}, headers=BUILDER)


async def _skill(c: AsyncClient) -> Response:
    s = _made(await c.post("/v1/skills", json=HARDSHIP, headers=BUILDER))
    return await c.post(f"/v1/skills/{s['id']}/publish-requests", json={"note": ""}, headers=BUILDER)


async def _widget(c: AsyncClient) -> Response:
    w = _made(await c.post("/v1/widgets", json=LIMIT_CARD, headers=BUILDER))
    return await c.post(f"/v1/widgets/{w['widgetId']}/publish-requests", json={}, headers=BUILDER)


async def _graph(c: AsyncClient) -> Response:
    body = {"name": "Hold check", "trigger": "Manual", "template": "blank"}
    w = _made(await c.post("/v1/workflows", json=body, headers=BUILDER))
    return await c.post(f"/v1/graphs/{w['id']}/versions", json={"definition": graph_definition(1)}, headers=BUILDER)


def _review_opened(r: Response) -> bool:
    """Each route's own word for "waiting for a second person"; anything else must be live."""
    if r.status_code == 409:
        assert r.json()["error"]["code"] == "review_required", r.text
        return True
    d = _made(r)
    return bool(d.get("pendingRequestId") or d.get("pendingReviewId") or d.get("status") in ("pending", "in_review"))


# Each publish route: how to publish a fresh subject on it, and its area in the policy.
PUBLISHES: dict[str, tuple[str, Callable[[AsyncClient], Awaitable[Response]]]] = {
    "/v1/agents/{agent_id}/publish-requests": ("agents", _agent),
    "/v1/workflows/{workflow_id}/publish-requests": ("workflows", _workflow),
    "/v1/workflows/definitions/{workflow_id}/publish-requests": ("workflows", _definition),
    "/v1/guardrails/{guardrail_id}/publish-requests": ("guardrails", _guardrail),
    "/v1/skills/{skill_id}/publish-requests": ("skills", _skill),
    "/v1/widgets/{widget_id}/publish-requests": ("widgets", _widget),
    "/v1/graphs/{name}/versions": ("workflows", _graph),
}


def test_every_publish_route_has_a_behaviour_check() -> None:
    assert set(PUBLISHES) == set(PUBLISH_ROUTES)


@pytest.mark.parametrize("path", sorted(PUBLISHES))
async def test_each_route_does_what_the_policy_answers(path: str) -> None:
    area, publish = PUBLISHES[path]
    async for c in _stack(True):
        assert not _review_opened(await publish(c)), f"{path}: dev auto-approve under major should publish at once"
    async for c in _stack(True):
        await set_mode(c, area, "always")
        assert _review_opened(await publish(c)), f'{path}: "always" should open a review'
