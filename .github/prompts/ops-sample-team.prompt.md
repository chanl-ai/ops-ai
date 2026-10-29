---
name: ops-sample-team
description: Install the sample team (people, knowledge, agents, tools, workflows, mailbox) on a running stack and walk the email demo end to end. Use when someone wants demo data, a team to try the console with, or to check the stack works from chat to the second reply.
agent: agent
---

# ops-sample-team: install the sample team and walk the demo

<!-- Generated from `docs/guide/skills/ops-sample-team.md` by `scripts/agent_skills.py`; change the page, not this file. -->

Make targets: make sample-team, make demo-walk, make demo.

## When to use it

The stack is up (ops-run) and a person wants something to look at, or wants proof that a fresh database works end to
end.

## Steps

1. `make sample-team` signs in as the first admin from `.run/dev-admin.env` and installs the team in
   `scripts/sample-team/sample-team.json` through the public API: four people, three handbooks, three agents with their
   skills and guardrails, the bank and code tools, the card dispute and levy workflows and the team mailbox. Each line
   says MADE, FOUND or FAIL; a second run finds everything. `NAME="Other team"` installs a second team.
2. `make demo-walk` prints PASS or FAIL per step: a chat that loads a skill and cites a handbook, a blocked topic, bank
   reads, a hold a person approves, then a levy notice emailed to the team mailbox through to the replies in Mailpit
   (<http://localhost:8025>). It runs on the fake model and can run again.
3. `make demo` runs both. The people's password is `OPS_DEMO_PASSWORD` in `.run/dev-admin.env`; the approver is
   riley.chen@harborpine.example.

To start clean: `make reset-db CONFIRM=yes && make up DEMO_MODEL=fake && make sample-team`.

## Proof

```bash proof
make up DEMO_MODEL=fake || make health
make sample-team
make sample-team EXPECT_FOUND=1
make demo-walk
```
