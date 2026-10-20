"""send_reply sends through the mail provider settings pick (c-187), by failure mode: a call that reports sent while
no provider is configured, and a reply that never reaches the provider."""

from __future__ import annotations

from ops_agents.activities.catalog import load_catalog
from ops_email import MemorySender, UnconfiguredSender
from ops_tools.tools import LocalToolRunner, ToolCaller

from .conftest import AGENTS_FIXTURES

CALLER = ToolCaller(tenant_id="t_a", team_id="team_ops", sub="service:agents", kind="service")
REPLY = {"to": "ana@example.com", "subject": "Re: card dispute", "body": "We have opened a dispute."}


async def test_with_no_provider_send_reply_fails_with_the_reason_instead_of_reporting_sent() -> None:
    out = await LocalToolRunner(load_catalog(AGENTS_FIXTURES), UnconfiguredSender()).run(
        "send_reply", REPLY, key="k1", caller=CALLER
    )
    assert not out.ok
    assert out.output["status"] == "failed" and "No mail provider is configured" in out.output["error"]


async def test_send_reply_hands_the_message_to_the_provider_under_the_call_key() -> None:
    mail = MemorySender()
    out = await LocalToolRunner(load_catalog(AGENTS_FIXTURES), mail).run(
        "send_reply", REPLY, key="run1:reply:0", caller=CALLER
    )
    assert out.ok and out.output["status"] == "sent"
    sent = mail.sent["run1:reply:0"]
    assert (sent.to, sent.subject, sent.body) == (("ana@example.com",), REPLY["subject"], REPLY["body"])
