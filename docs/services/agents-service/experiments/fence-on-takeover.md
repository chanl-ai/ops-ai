# Raising the tools-service fence on takeover

Status: done (E2c), 2026-10-10. Tests are in `services/agents-service/tests/gateway/test_fence_on_takeover.py` and run
on the scripted model, with no real model calls.

## Gap

E2b fences tool writes in tools-service by the highest lease generation a write has carried (`gateway_fences`).
That fence rises only when a write arrives. After agents-service takes a thread over, and before the new owner's
first tool write, a stalled old owner could still write with its old generation, because the fence had not moved.

## What was built

| Part | Detail |
|---|---|
| Fence route | `POST /v1/fences {thread, generation}` in tools-service (`ops_tools/app.py`), with service-token auth. It raises the fence to `generation` unless the fence is already higher. Calling it again is a no-op, and a lower generation gets 409 `lease_superseded` |
| Takeover detection | `Leases.acquire` reads the lease row under a row lock in the same transaction as the takeover upsert. If the row it replaces was never released (a crash or a stall, not a finished run), the acquire is a takeover. That covers the sweeper's recovery and any new run that reclaims an expired lease |
| Hook | `Leases(on_takeover=...)` is called with the new generation after a takeover, before the caller resumes the thread. agents-service wires it to `ToolsFence` (`ops_agents/api/fencing.py`), which calls `GatewayClient.raise_fence` |
| Tools-service down | The takeover goes on. `ToolsFence` journals `lease.fence_not_raised` on the thread (a `kind=lease` run row) and logs a warning. The new owner's first tool write raises the fence anyway, so the gap stays open only until that write |

## Tests

| Failure mode | Test | Watched to fail |
|---|---|---|
| A stale owner writes between the takeover and the new owner's first tool write | `test_stale_owner_write_after_takeover_is_refused` | Yes: with the hook disabled, the stale write returned 200 |
| The fence call is not idempotent, or lowers the fence | `test_fence_call_is_idempotent_and_refuses_a_lower_generation` | No |
| tools-service being down blocks the takeover, or the gap stays open past the first write | `test_takeover_goes_on_when_tools_service_is_down` | Yes: with the hook disabled, no warning was journaled |
| A finished run's next acquire is mistaken for a takeover, adding a call on every run | `test_a_finished_run_is_not_a_takeover` | No |

## Verdict

Confirmed. The gap between the takeover and the new owner's first tool write is closed whenever tools-service
answers, and when it does not, the gap lasts only until the new owner's first tool write.

## Gotchas

| Topic | Detail |
|---|---|
| Ordering | The hook runs after the takeover commits and before the thread resumes. A stale owner's write that reaches tools-service before the fence call still passes, because it is ordered before the takeover as tools-service sees it. That write was made while the old owner still believed it held the lease, which is the residual the fence cannot close without a shared clock |
| A takeover that is itself stale | If the fence is already above the new generation (a third owner took over meanwhile), the call gets 409 and the hook only logs it. That owner's own writes will be refused by the fence |
| Takeover costs one call | Only takeovers call tools-service. A run that finished and released its lease does not, so the normal path adds no call |
| Auth | The fence route takes the same shared service token as the timer fire route. A deployment replaces both with workload identity |
