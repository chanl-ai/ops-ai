# Standards: security

Status: target state. Part of the [engineering standards](../engineering-standards.md); ids `SC1` to `SC6` are frozen.
Access and tenancy have their own page ([tenancy and access](tenancy-and-access.md)); secrets in configuration are
`CF4`; input validation is `MD1`.

Model calls and calls to outside systems leave through two gateways and nowhere else; every change to what a person can
see or do leaves an audit entry in the same transaction; a secret is written once and never read back; nothing committed
could identify a customer or open a door.

## SC1 Two gateways, no other egress

Rule: model calls leave only through models-service and tool or outside-system calls only through tools-service; no
other service opens a connection to a host outside the installation.
Why: the gateways hold the keys, check policy, meter and log every call; a call around them is unmetered and unlogged.

Today: the audit found no outside host outside the two gateways; nothing static stops the next one.

Pattern (`services/kb-service/src/ops_kb/app.py:152`): kb-service reaches agents-service through a service client; its
model calls go through models-service.

Check: `services/agents-service/tests/gateway/` (gateway tests); `ops_service_kit.standards.check_model_calls` fails on
any module outside `ops_service_kit.model_calls` and models-service that names a model route
(`packages/ops_service_kit/tests/test_standards.py`). Needed: the `.importlinter` contract in `OB6`, and a socket guard
in tests that fails on any connection to a host the test did not start.

## SC2 A change to access leaves an audit entry in the same transaction

Rule: every write that changes what a person or system can see or do (members, roles, keys, policies, sign-in,
secrets) records an entry through `ops_store.audit.record(conn, ...)` on the connection of the change.
Why: a change with no entry cannot be reviewed (SOC 2 CC7.2, CC8.1), and an entry committed separately can describe a
change that rolled back.

Today: no known breach among the platform-service writes.

Pattern (`services/platform-service/src/ops_platform/store/members.py:461`):

```python
async def _audit(c: AsyncConnection, actor: Actor, action: str, member_id: str, detail: dict[str, Any]) -> None:
    await record(c, tenant_id=actor.tenant_id, team_id=actor.team_id, actor=actor.user_id, action=action, ...)
```

Check: no check yet. Needed: a test over every write route in the access area asserting one audit row per write.

## SC3 A secret is written once and never returned

Rule: a secret value is accepted on write, stored through `ops_service_kit.credentials` over
`ops_policy.CredentialStore`, and never returned by any route; a read answers whether it is set.
Why: a secret that comes back can leak through a screen, a log or a cache.

Today: no known breach.

Pattern (`packages/ops_policy/src/ops_policy/credentials.py:27`): the store is a port; the kit builds it from settings
(`packages/ops_service_kit/src/ops_service_kit/credentials.py:11`).

Check: `deploy/database/tests/test_credential_tables_locked.py` and `test_credentials_through_the_port.py`. Needed: a
test that no response schema in any `openapi.json` carries a field named for a secret.

## SC4 Every dependency is reviewed

Rule: no dependency is added without a licence and network-behaviour entry in [dependencies](../dependencies.md), and a
critical advisory fails the build.
Why: an enterprise reviews every package that ships; an unreviewed one blocks the whole release.

Today: the advisory and code-scanning checks run and are not required on the development trunk, so a red run does not
stop a merge.

Pattern (`scripts/sbom.py`): the dependencies page is generated from `uv.lock` and checked with `--check`.

Check: `.github/workflows/dependency-check.yml` (`scripts/deps_audit.py`), `.github/workflows/codeql.yml`,
`scripts/sbom.py --check` in `make python-verify`. Needed: make both workflows required on the trunk.

## SC5 Nothing committed identifies a customer or opens a door

Rule: no committed file carries a credential, a private path, a tracker id, a session link or real customer data; sample
data is fictional and from several industries.
Why: the repository is public.

Today: no breach.

Check: `scripts/leak_scan.py` (`.github/workflows/leak-scan.yml`); `node scripts/check-public-paths.mjs`;
`config/leak-patterns.txt`.

## SC6 Tests never open a real connection

Rule: tests and use cases run on the scripted model with model keys removed, and a test never reaches a host it did not
start.
Why: a test that depends on an outside service is slow, costs money and leaks the test's data.

Today: `make verify` unsets the model keys; nothing stops a test from opening another socket.

Pattern (`make/python.mk`): the verify target runs each service with the model keys unset.

Check: `make/python.mk`; CI holds no model keys. Needed: the socket guard in `SC1`.
