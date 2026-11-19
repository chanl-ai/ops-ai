# Standards: errors, logging and observability

Status: target state. Part of the [engineering standards](../engineering-standards.md); ids `OB1` to `OB6` are frozen.
The design is in [logging and data writes](../logging-and-data-writes.md) and [operations](../operations.md).

An operator follows one request across services by its id, every log line is one JSON object with the ids on it, every
outbound call has a timeout, and a load balancer can tell a process that is up from one that is ready.

## OB1 Logs go through the kit

Rule: every log line goes through `ops_service_kit.logging`: no `print`, no `logging.basicConfig`, no
`logging.getLogger`; the event is a string literal and the values are keywords; `redact` runs last.
Why: secrets and personal data are removed in one place (OWASP ASVS V7.1), and a keyword value can be searched where a
formatted sentence cannot.

Today: no breach in agents-service, the one service the rule is checked on.

Pattern (`services/agents-service/src/ops_agents/api/routers/guardrails.py:212` and
`packages/ops_service_kit/src/ops_service_kit/logging.py:117`):

```python
log.info("guardrail_deleted", guardrail=guardrail_id, name=row["name"], by=me.email)
def redact(_: WrappedLogger, __: str, event: EventDict) -> EventDict:
```

Check: ruff `T20`, `G` and `LOG` (`pyproject.toml:92`) on every changed Python file;
`services/agents-service/scripts/check_standards.py` rules 6 and 6b; `packages/ops_service_kit/tests/test_logging.py`.
Needed: run rules 6 and 6b over every service.

## OB2 One request line with the ids and the counts

Rule: each request writes one `http.request` line carrying `request_id`, `tenant_id`, `team_id`, the route template,
the status, the duration and `db.query_count`; every other line in that request carries the same ids.
Why: an operator follows one request across services by id, and the query count is what the statement budget (`DA6`)
reads.

Today: kb-service and files-service write no per-request counter, so their numbers come only from the database log.

Pattern (`packages/ops_service_kit/src/ops_service_kit/request_timing.py:124`):

```python
def _request_line(scope: Scope, timing: RequestTiming, status: int) -> None:
    ... "db.query_count": timing.db_queries,
```

Check: `packages/ops_service_kit/tests/test_logging.py`. Needed: every service mounts `RequestTimingMiddleware`.

## OB3 Errors are typed, coded and actionable

Rule: a refusal is an `ApiError` subclass with a stable `code`, and its message says what was refused and what to do;
an unexpected exception becomes the 500 envelope with a request id and no traceback.
Why: a client branches on the code; a person reads the message; support uses the id.

Today: no known breach.

Pattern (`packages/ops_service_kit/src/ops_service_kit/errors.py:20` and
`services/agents-service/src/ops_agents/api/routers/graphs.py:220`):

```python
class ValidationFailed(ApiError):
    status = 400
    code = "validation_failed"
raise Conflict(f"Deployment {body.deployment_id} is paused; it opens no new cases.", code="deployment_paused")
```

Check: `ops_service_kit.contract.response_checker`; `_UnhandledAsEnvelope` (`http.py:189`). Needed: the forced-500 test
in `AP6`.

## OB4 Up and ready are two answers

Rule: each service answers `GET /health` (the process is up) and `GET /ready` (the database is reachable, its migration
chain is at head, its required settings are present); a deployment routes traffic only on ready.
Why: a load balancer asks two different questions, and a process that is up with a database it cannot reach must not
take traffic.

Today (`services/agents-service/src/ops_agents/api/routers/health.py:28`): `/health` pings the database and checks the
runtime started; no service answers `/ready`, and `deploy/fly/stg_deploy.sh` checks processes with
`deploy/host/ops_host.py --check` instead.

Pattern: none in the repository yet; the shape is the one `health.py:28` uses, split in two.

Check: no check yet. Needed: a use case that calls `/ready` with the database down and with a chain behind head, and
expects 503 both times.

## OB5 Background health is part of health

Rule: every loop appears in `/health/background` in the kit's shape (`packages/ops_service_kit/src/ops_service_kit/background.py`),
and a loop that stops beating shows as such within its interval.
Why: a stuck relay or poller is otherwise found by a customer.

Today: covered for the relays and the agents-service loops; no test per loop (`EV4`).

Check: see `EV4`.

## OB6 Every outbound call has a timeout and a bounded retry from settings

Rule: every HTTP call to another service goes through `ops_identity.ServiceClient` or a client package, with a timeout
and retry count that come from settings; no bare `httpx.AsyncClient()` in a service, and no literal timeout.
Why: a call with no timeout holds a worker forever; a retry loop with no bound turns one outage into a storm.

Today (`services/kb-service/src/ops_kb/app.py:152`, `services/agents-service/src/ops_agents/api/worker.py:94`): bare
clients with literal timeouts (`CF2`). The audit counted 39 `httpx` clients outside the two gateways, all pointed at our
own services.

Pattern (`packages/ops_identity/src/ops_identity/client.py:75`): `ServiceClient.for_settings(...)` takes the timeout
once and retries transport failures on reads only.

Check: no check yet. Needed: an `.importlinter` contract that `httpx` is imported only by `ops_identity.client`, the
two gateways and `ops_service_kit.model_calls`, and the timeout ratchet in `CF2`.
