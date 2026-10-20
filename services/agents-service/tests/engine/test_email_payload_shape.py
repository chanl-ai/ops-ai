"""The Email received trigger's payload against its declared shape (c-353), by failure mode: the trigger writes a key
`ops_engine.shapes.EMAIL` does not list, or drops one it requires, so a builder mapping the email's fields before a run
is offered a field that never arrives."""

from __future__ import annotations

from ops_agents.store.tenancy import tenant_scope
from ops_engine.shapes import EMAIL, mismatches
from tests.engine.test_email_trigger import TENANT, Env, env, mail  # noqa: F401  # pyright: ignore[reportUnusedImport]


async def test_a_run_started_by_mail_has_exactly_the_email_payload_shape(env: Env) -> None:  # noqa: F811
    await env.publish()
    await env.listener().poll_all()
    env.drop(mail(1))
    await env.listener().poll_all()
    with tenant_scope(TENANT):
        [run] = await env.runs()
    assert mismatches(EMAIL, run["input"]) == [], run["input"]
