"""Seeds one fresh team through the Python SDK alone: the team, a second person to review, a knowledge base, an agent,
and a workflow run that waits on a person, is decided and finishes. `make sdk-check` runs it against `make up`.

    python sdk/python/examples/seed_team.py --local --email <workspace admin> --password <password>
    python sdk/python/examples/seed_team.py --base-url https://ops.example.com --email ... --password ...

Every name carries a stamp, so each run makes a team of its own and never touches another team's records.
"""

from __future__ import annotations

import argparse
import os
import time
from typing import Any

from ops_ai import OpsAI

# A local stack without the proxy: each service on its own port (make/env.mk).
LOCAL_PORTS = {"platform": 8710, "agents": 8700, "tools": 8720, "kb": 8740, "files": 8750, "documents": 8760}

HANDBOOK = """# Card disputes

A cardholder may dispute a card transaction within 60 days of the statement date. A provisional credit up to 500 is
approved by the team lead; above 500 it needs a second approver.
"""


def workflow(stamp: str) -> dict[str, Any]:
    """A request that waits for a person to approve or reject it, then ends on their choice."""
    return {
        "schemaVersion": 2,
        "id": f"wf_sdk_{stamp}",
        "name": f"SDK dispute approval {stamp}",
        "description": "A dispute waits for a person's approval.",
        "nodes": [
            {
                "id": "start",
                "type": "ops.trigger.request",
                "typeVersion": 1,
                "name": "Dispute received",
                "parameters": {
                    "inputSchema": {
                        "type": "object",
                        "required": ["cardholder", "amount"],
                        "properties": {
                            "cardholder": {"type": "string", "title": "Cardholder"},
                            "amount": {"type": "string", "title": "Amount"},
                        },
                    }
                },
            },
            {
                "id": "review",
                "type": "ops.flow.humanReview",
                "typeVersion": 1,
                "name": "Approve the provisional credit",
                "parameters": {
                    "title": "Credit {$.input.amount} for {$.input.cardholder}",
                    "summary": {"dispute": "$.input"},
                },
            },
            {
                "id": "approved",
                "type": "ops.flow.end",
                "typeVersion": 1,
                "name": "Credited",
                "parameters": {"outcome": "credited"},
            },
            {
                "id": "rejected",
                "type": "ops.flow.end",
                "typeVersion": 1,
                "name": "Declined",
                "parameters": {"outcome": "declined"},
            },
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "review", "port": "in"}},
            {"from": {"node": "review", "port": "approve"}, "to": {"node": "approved", "port": "in"}},
            {"from": {"node": "review", "port": "reject"}, "to": {"node": "rejected", "port": "in"}},
        ],
    }


def say(what: str, detail: str) -> None:
    print(f"  {what:<22} {detail}", flush=True)


def published(reviewer: OpsAI, review: dict[str, Any], what: str) -> None:
    """A publish waits for a person other than the builder, unless the team's policy asks for no review."""
    if review.get("status") in ("approved", "published") or review.get("decidedAt"):
        say(f"{what} published", "no review needed")
        return
    reviewer.raw.agents.reviews_decide_publish_request(review["id"], {"decision": "approved", "reason": "Checked."})
    say(f"{what} published", f"approved by the reviewer ({review['id']})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("OPS_BASE_URL"))
    ap.add_argument("--local", action="store_true", help="each service on its own local port, no proxy")
    ap.add_argument(
        "--email", default=os.environ.get("OPS_EXAMPLE_EMAIL"), required=not os.environ.get("OPS_EXAMPLE_EMAIL")
    )
    ap.add_argument(
        "--password",
        default=os.environ.get("OPS_EXAMPLE_PASSWORD"),
        required=not os.environ.get("OPS_EXAMPLE_PASSWORD"),
    )
    ap.add_argument("--keep", action="store_true", help="leave the team active; by default it is archived at the end")
    ap.add_argument("--model", default=os.environ.get("OPS_EXAMPLE_MODEL", "default"), help="the agent's model alias")
    a = ap.parse_args()
    conn: dict[str, Any] = {"base_url": a.base_url or "http://127.0.0.1"}
    if a.local:
        conn["services"] = {
            s: f"http://127.0.0.1:{os.environ.get(f'OPS_{s.upper()}_PORT', p)}" for s, p in LOCAL_PORTS.items()
        }
    stamp = time.strftime("%m%d%H%M%S")
    print(f"seed_team: a fresh team, stamp {stamp}")

    admin = OpsAI.sign_in(a.email, a.password, **conn)
    team = admin.raw.platform.teams_create_team({"name": f"SDK example {stamp}", "admin": a.email})
    say("team", f"{team['name']} ({team['id']})")
    # A session carries the teams the person was in when it was made, so the admin signs in again to act in it.
    lead = OpsAI.sign_in(a.email, a.password, team=team["id"], **conn)

    reviewer_email = f"sdk.reviewer.{stamp}@example.test"
    invited = lead.raw.platform.members_invite_members({"emails": [reviewer_email], "role": "approver"})
    token = invited["invites"][0]["token"]
    with OpsAI(**conn) as anonymous:
        anonymous.raw.platform.invites_accept_invite(token, {"name": "SDK Reviewer", "password": a.password})
    reviewer = OpsAI.sign_in(reviewer_email, a.password, team=team["id"], **conn)
    say("second person", f"{reviewer_email}, approver")

    kb = lead.knowledge.create(
        {"name": f"Dispute handbook {stamp}", "description": "Card dispute rules.", "owner": a.email}
    )
    source = lead.raw.kb.sources_create_source(
        {"type": "file", "name": "Handbook", "kbIds": [kb["id"]], "sensitivity": "internal"}
    )
    file = lead.upload("disputes.md", HANDBOOK.encode(), mime="text/markdown", purpose="knowledge_source")
    lead.raw.kb.sources_add_files(source["id"], {"fileIds": [file["id"]]})
    lead.raw.kb.sources_sync_source(source["id"], {})
    say("knowledge base", f"{kb['name']} ({kb['id']}), 1 document")

    agent = lead.agents.create(
        {
            "name": f"Dispute Desk {stamp}",
            "role": "Answers card dispute questions from the handbook.",
            "model": a.model,
            "channels": ["chat"],
            "instructions": "Answer from the dispute handbook and cite it.",
        }
    )
    patched = lead.raw.agents.agents_update_agent(agent["id"], {"collections": [kb["id"]], "note": "Knowledge added."})
    review = lead.raw.agents.agents_request_publish(
        agent["id"], {"version": patched["version"], "note": "First release."}
    )
    published(reviewer, review, "agent")

    definition = workflow(stamp)
    lead.raw.agents.workflows_create_definition({"definition": definition})
    review = lead.raw.agents.workflows_request_definition_publish(definition["id"], {"note": "First release."})
    published(reviewer, review, "workflow")

    started = lead.runs.start(definition["id"], input={"cardholder": "Jordan Example", "amount": "120.00"})
    run = lead.runs.wait(started["runId"], timeout=120)
    if run["status"] != "waiting" or not run.get("taskId"):
        raise SystemExit(f"seed_team: the run should wait on a person, it is {run['status']}: {run.get('error')}")
    say("run waiting", f"{run['id']} on task {run['taskId']}")
    reviewer.tasks.decide(run["taskId"], "approve", reason="Within the lead's limit.")
    run = lead.runs.wait(started["runId"], timeout=120)
    if run["status"] != "succeeded" or run.get("outcome") != "credited":
        raise SystemExit(f"seed_team: the run should end credited, it is {run['status']}/{run.get('outcome')}")
    say("run finished", f"{run['id']} succeeded, outcome {run['outcome']}")
    if not a.keep:
        admin.raw.platform.teams_archive_team(team["id"])
        say("team archived", "pass --keep to leave it active")
    print(f"seed_team: done, team={team['id']} workflow={definition['id']} reviewer={reviewer_email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
