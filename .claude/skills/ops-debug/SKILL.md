---
name: ops-debug
description: Diagnose a failing Ops AI service: which one is down, its log, its port, a stale process, or a second stack in the way. Use when a page errors, a make target fails, or a service will not start.
allowed-tools: Bash(make *) Bash(uv run *) Bash(python3 *) Read Grep Glob
---

# ops-debug: find why a service fails

<!-- Generated from `docs/guide/skills/ops-debug.md` by `scripts/agent_skills.py`; change the page, not this file. -->

Make targets: make health, make logs, make ports, make restart.

## When to use it

Something in the stack answers an error, hangs or is down.

## Steps

1. `make health` shows every service, its port, its state and who owns the listener; a DOWN row or a listener owned by
   another process names the problem.
2. `make logs SVC=<service> FOLLOW=0` prints a service's log (`.logs/<service>.log`); the worker is `SVC=worker`.
3. `make ports` prints this stack's ports; `ISOLATED=1` adds 1000 to each, so a second stack never fights the first.
4. `make restart SVC=<service>` migrates and restarts one service; `make up` restarts whatever runs code older than the
   checkout.
5. A model call that fails: `make demo-model MODEL=fake` puts the agents back on the fake model.

## Proof

```bash proof
make up DEMO_MODEL=fake || true
make health
make ports
make logs SVC=agents FOLLOW=0 | tail -5
```
