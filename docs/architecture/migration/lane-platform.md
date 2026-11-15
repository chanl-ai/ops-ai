# Phase 2, platform lane

Status: current, 2026-11-15. platform-service's store and request layers replaced wholesale against the components,
in one branch and one pull request, beside the kb, tools and agents lanes. Sign-in, OAuth, SAML, roles and policies
logic stays; what changes is how a route opens its transaction, pages, types its values and reaches other services,
and how the page shell is answered.

## Inputs

| Input | Where |
|---|---|
| The components and the pilot, merged on `develop` | [components.md](components.md), [pilot.md](pilot.md) and its published rates |
| The service today | `services/platform-service/src/ops_platform/`: `store/` 17 files, 5,455 lines; `api/app.py` and `api/schemas.py`, 2,554 lines; 22 top-level modules (`auth.py`, `roles.py`, `sso.py`, `signin_settings.py`, `teams.py`, `workspace_lifecycle.py` and the rest); `oauth/` 4 files |
| Its use cases | 27: `make usecase-coverage SERVICE=platform-service` lists them (`uc-021` to `uc-751`) |
| Its unit tests | `services/platform-service/tests`, 54 files |
| The sites, counted on `develop` | 127 `tenant_tx` calls; 2 caught database errors that carry on; 1 table with no row policy (`signin_email_failures`); 4 clients and 6 literal timeouts, 1 loopback fallback; a relay wiring in `store/event_relay.py`; 24 store functions returning a dict; 1 gather and 3 `create_task` sites; the page shell reads roles twice (`/v1/me` and `/v1/me/permissions`) and five routes write a row per GET; api keys paged in Python; one `sa.text(f"...")` in `store/signin.py`; 25 access lines on the allowlist: 21 policy defaults (kept, every reader through `policy()`), 2 role-name compares in `store/teams.py` and `store/workspace.py` (converted onto role assignments), 2 refusals kept as state |
| The components' baseline rows for this service | The raw-site, savepoint, config-literal, typed-boundary and portable files, and the per-lane role-name file |

## Size

5 to 7 builder days, against 3 to 4 in the site-by-site plan. Basis: store 5,455 lines at 1,800 a day (3); 41 GET
routes and their writes in `api/app.py` at 70 a day (1); the shell as one `/v1/me` answer with teams and permissions,
no write on a GET, members with roles in one query (1); api keys onto `list_page` and the `role_assignments` index
(0.25); the 21 policy readers through `policy()`, the two queries onto role assignments, the two register rows landed
(0.5 to 1); the budgets file for 41 GET routes (0.5). One builder.

## What is replaced and what is kept

| Replaced | Kept |
|---|---|
| Every file under `store/`: `audit.py`, `holders.py`, `identity.py`, `keys.py`, `lifecycle.py`, `members.py`, `policies.py`, `roles.py`, `seeding.py`, `signin_secrets.py`, `signin.py`, `tables.py` (one marking added), `teams.py`, `tenancy.py` (becomes a one-line alias of the base's `tx()`), `workspace.py`; `store/event_relay.py` deleted | The SQL each function runs, moved onto the base with named columns |
| Route plumbing in `api/app.py`: every route takes `Tx`; `/v1/me` answers once; list routes take `ListQuery`; bodies in `api/schemas.py` extend `In`, replies `Out`; the gather and `create_task` sites | The functions the routes call in `auth.py`, `roles.py`, `sso.py`, `passwords.py`, `signin_settings.py`, `signin_watch.py`, `team_admin.py`, `workspace_lifecycle.py`, `break_glass.py`, `oauth/`; their inputs retyped where a dict crossed |
| `__main__.py` endpoint fields and `require()`; the 4 clients onto `ServiceClient.for_settings`; the fallback and 6 timeouts deleted | `bootstrap.py`, `seed.py` |
| `signin.py`'s `sa.text(f"...")`: the name moves into `ops_store.dialect` or carries its `noqa: S608` reason | |
| The 2 role-name compares: the admin count per team and the Security mirror read `role_assignments` | The 21 policy defaults in `ops_access.policies`, each read through `policy(p, key)`; the 2 refusals (`workspace_closed`, `domain_not_allowed`), which are state |

## Target shapes

```python
# services/platform-service/src/ops_platform/store/members.py, after
class MemberOut(Out):
    person_id: str
    team_id: TeamId
    display_name: str
    roles: list[str]           # from role_assignments in the same statement, never a second query per row

class Members(Store):
    role = ROLE

    async def list(self, conn: AsyncConnection, team: str, q: ListParams) -> ListPage[MemberOut]:
        return await list_page(conn, members_with_roles(team), q, default_sort=members.c.display_name,
                               search=[members.c.display_name, members.c.email], facets={"role": role_assignments.c.role})

# services/platform-service/src/ops_platform/api/app.py, after
@router.get("/v1/me", response_model=Envelope[MeOut])
async def me(p: CurrentPrincipal, _: Tx, st: Stores) -> JSONResponse:
    """One answer: the person, their teams and the permission cells, in one transaction; writes nothing."""
    async with st.identity.tx() as conn:
        return ok(await st.identity.me(conn, p))

@router.get("/v1/api-keys", response_model=Envelope[ListResult[ApiKeyOut]])
async def list_api_keys(p: CurrentPrincipal, _: Tx, q: ListQuery, st: Stores) -> JSONResponse:
    async with st.keys.tx() as conn:
        return ok(await st.keys.list(conn, p.team, q))

# a policy value, after
limit = policy(p, "chat.daily_budget")      # never a default read inline
```

## Step order

1. Inventory and characterisation tests, as in the pilot: routes and store functions reached by a use case or test;
   one api-layer test per uncovered route a screen calls, passing on `develop` before the rewrite.
2. Store layer: every class extends `Store`; `tenancy.py`'s `tenant_tx` becomes an alias of the base's `tx()` and the
   127 calls take `conn` or `self.tx()`; every dict-returning function names its columns and returns an `Out`; the two
   caught errors run inside `attempt()`; `signin_email_failures` is marked and its migration emits the policy DDL with
   its backfill and down path; the `role_assignments` index by role is added in the same chain.
3. Request layer: every route takes `Tx`; the shell becomes one `/v1/me` with teams and permissions and the permission
   version header; the five GET routes that wrote a row stop writing; api keys and members take `ListQuery`; bodies
   onto `In`, replies onto `Out`; the gather site onto `TaskGroup`, the three `create_task` sites onto
   `background.start()`.
4. Access: every policy reader goes through `policy(p, key)`; the admin count per team and the Security mirror read
   `role_assignments`; the two register rows the components decided are reflected here where this service holds them.
5. Clients, settings and relay: `settings.require("agents", ...)`; the 4 clients onto `ServiceClient.for_settings`;
   the fallback and timeouts deleted; `event_relay.py` deleted and the subscriber map becomes `routes` for `relay()`.
6. Budgets file for 41 GET routes; a `loop_reports_failure` test per loop on `PROCESSES`.
7. Baselines to zero for this service; use cases and tests green; pull request; after merge, SDKs regenerated on
   `develop` by one hand, staging deployed and checked.

## Commands

| Step | Command |
|---|---|
| Tests, both databases | `make -s test PKG=services/platform-service`; the `store-mssql` job on the pull request |
| Only what the change touches | `make test-impacted BASE=origin/develop` |
| The 27 use cases, in parallel | `make usecase-batch UCS="<the ids from make usecase-coverage SERVICE=platform-service>"` |
| Use cases the change touches, plus the core console ones | `make uc-impacted BASE=origin/develop` |
| The ratchets | `uv run python scripts/check_access_exceptions.py`; `uv run python scripts/check_portable_store.py --strict`; `uv run lint-imports --no-logo`; `uv run pytest -q deploy/database/tests`; `uv run python scripts/check_config_literals.py --strict`; `uv run python scripts/check_typed_boundaries.py --strict` |
| The gate | `make verify` |
| After the merge | `make sdk` and `make sdk-verify` on `develop`; `make stg-deploy REF=<merge commit>`; `make stg-health` |

## Acceptance

| Check | Green when |
|---|---|
| Transactions | Zero `tenant_tx` outside the alias; zero raw engine sites; the two caught errors inside `attempt()`; `GET /v1/overview`-style routes open one transaction |
| Markings and indexes | `signin_email_failures` off the `WAITING` list; `role_assignments` indexed by role; the migration downgrades on both databases |
| The shell | `/v1/me` is one call that returns teams and permissions; `/v1/me/permissions` answers from the same statement or is removed with the console lane; no GET writes a row; the permission version is cached 30 s and dropped on the header |
| Lists | Api keys and members paged in SQL with facets; no list slice in `api/` |
| Access | Zero inline policy defaults outside `ops_access.policies`; zero role-name compares in this service; the use cases that assert 403 codes still pass |
| Clients and settings | Zero fallbacks, timeouts and `httpx.AsyncClient` constructions; `__main__` exits naming an unset required endpoint |
| Typed boundaries | 24 store functions return models; every body an `In`, every reply an `Out`; zero bare tasks; `signin.py`'s string SQL resolved |
| Relay and loops | `event_relay.py` gone; every `PROCESSES` key has a `loop_reports_failure` test |
| Budgets | 41 GET routes green at 5 and 50 rows on both databases |
| Behaviour and staging | Tests, the 27 use cases and `make verify` green on the merge commit; staging deployed with every process up and the console walk green; Access, Teams, Sign-in and Security screens opened by hand |

## Branch and pull request

Branch `refactor/platform-store-and-api-layers` from `origin/develop`, one pull request into `develop`, rebased once
on the pilot's merge. Commit subject at most 72 characters, body at most three lines. A reviewer who did not write it
approves against this page and the standards. Merge order: second, after the pilot.

## What not to touch

- `auth.py`, `sso.py`, `passwords.py`, `signin_settings.py`, `oauth/`: sign-in logic stays; inputs retyped only.
- Any other service's files or baseline rows; `access-exceptions-allowlist.txt` lines that belong to another lane.
- The console; `/v1/me/permissions` is removed only once the console lane reads the one `/v1/me` answer.
- The generated SDK layer inside the pull request.
