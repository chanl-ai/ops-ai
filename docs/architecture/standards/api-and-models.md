# Standards: API contracts and models

Status: target state. Part of the [engineering standards](../engineering-standards.md); ids `AP1` to `AP7` and `MD1` to
`MD5` are frozen. The conventions are in [API](../api.md).

Every route is typed, authenticated, idempotent on write, and described in the committed `openapi.json` that the SDKs
are generated from. Every model that crosses a boundary is a Pydantic model that refuses what it does not know.

## API contracts

### AP1 Every route declares its responses, and the document matches the app

Rule: every route declares its success model (`Envelope[T]`) and the error envelope for each status it returns, and the
committed `openapi.json` matches what the app serves.
Why: the SDKs are generated from the documents, so an undeclared response is an untyped SDK method.

Today: four untyped routes remain across the `openapi-untyped.txt` files; the list may only shrink. Inside the code,
about 4,300 `dict[str, Any]` annotations show how much crosses layers untyped.

Pattern (`services/agents-service/src/ops_agents/api/routers/cases.py:35` and
`packages/ops_service_kit/src/ops_service_kit/http.py:67`):

```python
@router.get("", response_model=Envelope[CaseRunList])
def error_responses(overrides=None) -> dict[int | str, dict[str, Any]]:  # the responses= a route declares
```

Check: `services/<x>/scripts/check_openapi.py` (all eight services) in each service's CI job;
`ops_service_kit.contract.response_checker(app)` attached in tests, so every response is checked against the document.

### AP2 One envelope for success and one for failure

Rule: success is `{success: true, data}` through `ok()` or `paged()`; failure is an `ApiError` subclass rendered as
`{success: false, error: {code, message, status, requestId, details?}}`; codes are named on the class or passed as a
constant.
Why: one shape lets every client handle errors once, and the request id ties the message to its log line.

Today: no breach.

Pattern (`packages/ops_service_kit/src/ops_service_kit/errors.py:8`, `http.py:179`):

```python
class ApiError(Exception):
    status = 500
    code = "internal"
def ok(data: Any, status: int = 200) -> JSONResponse:
```

Check: `ops_service_kit.contract.response_checker` against the documented error envelope; `install_error_handlers(app)`
(`http.py:219`) renders every `ApiError`.

### AP3 Every route is authenticated

Rule: every route depends on a caller from `ops_identity` (`CurrentPrincipal`, `CurrentService` or `CurrentCaller`);
only `/health` and the OpenAPI document are open.
Why: an unauthenticated path into data is the first thing a penetration test finds.

Today: checked for agents-service only; the other seven services have each operation marked public or private in the
OpenAPI gate, which does not prove the dependency is there.

Pattern (`packages/ops_identity/src/ops_identity/fastapi.py:214`):

```python
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
```

Check: `services/agents-service/scripts/check_standards.py` rule 5. Needed: move rule 5 into
`ops_service_kit.openapi` so every service's gate asserts the dependency on every non-public route.

### AP4 A write is safe to repeat

Rule: every write route accepts an idempotency key or a natural key (`runId`, `externalKey`) and returns the first
result when it is repeated.
Why: clients and relays retry; a repeat must not act twice.

Today: no rule enforces it; the audit found no breach among the write routes it read.

Pattern (`services/agents-service/src/ops_agents/api/routers/graphs.py:198`): find-or-create by `external_key` in one
transaction; a repeat returns the existing thread with `created: false`.

```python
existing = await store.thread_by_key(body.external_key)
```

Check: no check yet. Needed: an OpenAPI rule that every `POST` declares an idempotency key or a natural key in its body
model.

### AP5 Contracts change by addition

Rule: a route that must break its contract ships as a new route or a backwards-compatible field; an in-place change
of a shape, a status code or a path is never made.
Why: generated clients in the field still call the old shape.

Today: no diff against the last release runs.

Pattern (`packages/ops_service_kit/src/ops_service_kit/http.py:78`): `operation_id` is `<tag>_<handler>`, so a path
change leaves the SDK method name alone.

Check: no check yet. Needed: an OpenAPI diff of each service against the last release tag, failing on a removed path,
field or status.

### AP6 An error message carries nothing a caller should not see

Rule: an error message never carries a stack trace, SQL, a secret, a token or another team's data; it says what was
refused and what to do, in product copy.
Why: an error body is shown on screens and copied into tickets (OWASP ASVS V7.4).

Today: no known breach; a forced 500 is not tested.

Pattern (`services/agents-service/src/ops_agents/api/routers/graphs.py:220`):

```python
raise Conflict(f"Deployment {body.deployment_id} is paused; it opens no new cases.", code="deployment_paused")
```

Check: `_UnhandledAsEnvelope` (`http.py:189`) turns an unhandled exception into the 500 envelope with no traceback.
Needed: a test that forces a 500 and asserts the body carries no traceback or SQL.

### AP7 Route ids and tags come from the kit

Rule: operation ids, tags and `x-ops-public` markers come from the kit's helpers; a route is marked `sdk`, `console` or
`both` on purpose, and the SDK generator reads the marking.
Why: the marking is what decides what a customer's SDK can call.

Today: no breach.

Pattern (`packages/ops_service_kit/src/ops_service_kit/http.py:73`): `tag_name` and `operation_id` are every service's
`generate_unique_id_function`.

Check: `services/<x>/scripts/check_openapi.py` (every route named, tagged and marked).

## Models

### MD1 Request bodies refuse unknown fields

Rule: every request body model sets `extra="forbid"`, so an unknown field answers `400 validation_failed`.
Why: a misspelled field silently ignored is a lost instruction (Pydantic v2 "Extra attributes"; OWASP ASVS V5.1).

Today (`services/agents-service/src/ops_agents/api/routers/run_resume.py:36` and
`services/models-service/src/ops_models/schemas.py:132`): two request bodies accept anything. Both have a stated
reason (an outside system's arbitrary result; a provider request forwarded whole); both should be listed as exceptions
rather than left as plain `extra="allow"`.

```python
class ResumeBody(BaseModel):
    model_config = ConfigDict(extra="allow")
```

Pattern (`packages/ops_service_kit/src/ops_service_kit/http.py:33`): the shared base forbids extras.

```python
class Out(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
```

A body or reply in another system's wire format (OpenAI's `finish_reason`) takes `ExternalIn` or `ExternalOut`: the
same refusal of unknown fields, with field names as declared instead of camelCase. Both count as `In` and `Out`.

Check: `uv run python scripts/check_typed_boundaries.py --strict`: `extra="allow"` outside the kit's `Passthrough`, and
every route whose JSON body is not an `In` (`ops_service_kit.contract.boundaries`), beyond the service's
`typed-boundaries-baseline.txt`. It catches `dict[str, Any]`, `asyncio.gather`, `create_task`, `getLogger` and
`extra="allow"` in their literal form, by their imported names (`from asyncio import gather`); a type alias, a name
that holds one, or a wrapper that calls them passes.

### MD2 One model per contract, generated everywhere else

Rule: each contract has one model, in the service that owns it; the SDKs and the console get it through `make openapi`
and the generator; no model is copied by hand into another service, an SDK or the console.
Why: copies drift, and the drift shows in production as a field one side never sends.

Today (`apps/console/src/lib/api/platform-http.ts:70`): the console's area clients hand-write the shapes they expect.
The SDK drift check runs only on a full CI plan and nightly, so a route change in a narrow pull request can leave the
SDK stale for a day.

Pattern (`apps/console/src/hooks/systems-queries.ts:18`): types come from the SDK's operations.

```ts
type Tools = OpsAI['raw']['tools'];
```

Check: `uv run python sdk/generate.py --check` (`make sdk-verify`). Needed: run it in `checks` whenever an
`openapi.json` changes.

### MD3 Validation is never skipped on outside input

Rule: `model_construct` and `model_validate(..., strict=False)` are never applied to input from a caller, a tool or a
model.
Why: `model_construct` skips validation (Pydantic v2 docs), so a bad value reaches the store.

Today: none found; nothing stops the next one.

Check: pyright `reportDeprecated = "error"` (`pyproject.toml`) keeps Pydantic v1 APIs at zero. No check yet for
`model_construct`; needed: a ruff banned-API entry outside `domain`.

### MD4 A value that crosses a layer is a model

Rule: what a route returns, what an `app` function returns to a route, and what a store returns to `app` is a typed
model or a typed row, never a bare `dict[str, Any]` where a model exists.
Why: a dict is an untyped contract; a renamed key fails at the customer, a renamed field fails at type-check.

Today (`services/agents-service/src/ops_agents/api/hitl_facade.py:320`): the facade returns a dict the route forwards.

Pattern (`services/agents-service/src/ops_agents/api/routers/cases.py:35`): `Envelope[CaseRunList]` types the route's
answer.

Check: `services/<x>/scripts/check_openapi.py` (untyped routes on the shrink-only list), and
`uv run python scripts/check_typed_boundaries.py --strict`: `dict[str, Any]` per file, store functions returning a dict,
and replies that are not an `Out` all the way down, each on a shrink-only `typed-boundaries-baseline.txt` per member.
A row leaves a store through `ops_store.rows.rows()` or `one()`.

### MD5 A name a person types is a `Name`

Rule: a request model's `name`, `title`, `label` or `display_name` field is `ops_service_kit.names.Name` (or `Name80`,
`Name120`, sized to the column that stores it; `FileName` for a file name), unless it carries a `pattern`. Code that checks a
name by hand calls `names.name_problem`, so every route refuses with the same message. A slug made from a name comes from
`names.slugify`, the one slug maker: Latin letters keep their base letter, and a name with letters that have no ASCII
spelling gets an 8-character hash of the name appended, so names that differ only in Chinese, Arabic or Cyrillic letters
get distinct slugs.
Why: a bare `str` takes a blank name, a line break or a value wider than its column; the last answered 500 on PostgreSQL
(`value too long for type character varying(120)`).

Today: the fields listed in `packages/ops_service_kit/name-fields-baseline.txt`; none of them reaches a column narrower
than the cap its model gives.

Pattern (`services/agents-service/src/ops_agents/api/routers/agents.py`): `name: Name`.

Check: `ops_service_kit.standards.check_names`, run by `services/agents-service/scripts/check_standards.py`; the baseline
only shrinks. A name is NFKC-normalised and trimmed on save, and a tab or a run of spaces becomes one space. A line break
answers 400 ("The name must be on one line; remove the line break."), so an old row holding one must be renamed before it
re-saves; a name made only of invisible characters (a zero-width space, a bidi mark) answers 400 as blank; NUL and other
control characters answer 400. The console checks the same rules in `apps/console/src/lib/validation/names.ts` before it
sends.
