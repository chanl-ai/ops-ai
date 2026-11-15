# Standards: configuration

Status: target state. Part of the [engineering standards](../engineering-standards.md); ids `CF1` to `CF6` are frozen.

Every process reads its configuration once, from one typed settings object, and fails at start when a value it needs
is missing. Nothing in code names a host, a port, a URL, a model or a timeout.

## CF1 One settings object per process

Rule: each process builds one `ops_service_kit.settings.Settings` (pydantic-settings, `OPS_` prefix) at start and
passes it down; no other module reads `os.environ`, `getenv` or `process.env`.
Why: configuration read in one place can be listed, validated and documented; a read scattered through code cannot.

Today: no breach in Python; the console has four files outside the entry module that read `process.env` (see `CF6`).

Pattern (`Settings` in `packages/ops_service_kit/src/ops_service_kit/settings.py`):

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPS_", env_nested_delimiter="__", extra="ignore", ...)
    environment: Literal["dev", "test", "production"] = "dev"
```

Check: `services/agents-service/scripts/check_standards.py` rule 4 (environment read only in `settings.py`; no
`dotenv`; no `.env` file), run in the agents-service CI job and in pre-commit; `apps/console/scripts/check-standards.mjs`
rule 4. Needed: run rule 4 over every service in the `checks` job.

## CF2 No literal host, port, URL, model or timeout in code

Rule: a host, port, URL, model alias, timeout, retry count, page size or limit lives in the settings class or in a
named constant; code outside those never writes one, and a setting never falls back to `127.0.0.1` or `localhost`.
Why: a value in code changes only with a release and differs silently between copies, and a loopback fallback hides a
missing setting until the first call fails.

Today (`services/kb-service/src/ops_kb/app.py`, `_agents_service`): the address is the setting, with no fallback; the
client and its timeout are still built where they are used.

```python
http = httpx.AsyncClient(base_url=settings.endpoint("agents").base, timeout=5)
```

After: the client comes from the endpoint, which carries the address, the timeout and the retries.

```python
agents = ServiceClient.for_settings(settings, service="kb", audience="agents", scopes=["agents:view"])
```

Also `services/agents-service/src/ops_agents/api/worker.py` (`timeout=10`) and
`packages/ops_service_kit/src/ops_service_kit/opa_server.py` (port 8181). One loopback fallback is left, in
`packages/ops_identity/src/ops_identity/fastapi.py`, and the check counts 59 literal timeouts and 50 clients built
outside `ops_identity.client`.

Pattern (`Settings.database_connect_timeout_s` in `packages/ops_service_kit/src/ops_service_kit/settings.py`): the value
is a named setting with its reason.

```python
database_connect_timeout_s: float = 30.0
database_connect_attempts: int = 3
```

Check: `uv run python scripts/check_config_literals.py --strict` (in `make python-verify`, the commit gate and CI): a
loopback fallback fails anywhere but the two named in the script; a literal `timeout=` or an `httpx.AsyncClient(`
fails beyond the member's `config-literals-baseline.txt`, whose rows only fall. `.importlinter` allows `httpx` only in
tools-service, models-service, `ops_identity.client` and the client packages, beyond a list that only shrinks. Needed:
`:<port>` literals.

## CF3 A missing required setting stops the process at start

Rule: a service checks every setting it needs when it starts and exits naming the setting; a missing value is never
found by the first request.
Why: a half-configured service in production serves wrong answers; one that refuses to start is noticed at deploy.

Today: every service process names the endpoints it cannot run without, first in its `__main__`; an address a process
reads only when a feature is on (`settings.files_url` in agents-service) is not yet checked at start.

Pattern (`services/kb-service/src/ops_kb/__main__.py`, `main`; `Settings.require` and `require_keys` in
`packages/ops_service_kit/src/ops_service_kit/settings.py`): an unset endpoint, or a key still holding its public
default outside dev, stops the service.

```python
settings.require("agents", *settings.identity_endpoints)
```

Also `services/models-service/src/ops_models/__main__.py:39`: a provider key left in settings outside dev raises
`SystemExit` with the fix in the message.

Check: `uv run pytest -q scripts/tests/test_boot_requires_endpoints.py` starts each service process with its required
addresses unset and asserts the exit names them; it fails when a service gains a `__main__` with no row.

## CF4 Secrets come only from the secret store

Rule: a secret reaches code only through the settings class (`SecretStr`, `secrets_dir`) or
`ops_service_kit.credentials`; no secret appears in code, fixtures, seeds, `openapi.json`, logs or test output, and
`.env.example` is the only environment file in git.
Why: the repository is public, and a secret in a log or fixture leaks through every copy of it.

Today: no known breach; the leak scan is required on `main` only, so a red scan does not stop a merge to the
development trunk.

Pattern (`Settings.anthropic_api_key` in `packages/ops_service_kit/src/ops_service_kit/settings.py`):

```python
anthropic_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY"))
```

Check: `scripts/leak_scan.py` in `.github/workflows/leak-scan.yml` on every pull request. Needed: make the scan a
required check on the development trunk.

## CF5 The default is the safe production value

Rule: a setting's default is the value production should run with; a development shortcut turns on only when
`environment` names development.
Why: a forgotten setting must not open a door in production.

Today: no known breach in sign-in; `registry_auto_approve` still defaults on and is ignored outside dev.

Pattern (`Settings.auth_mode` in `packages/ops_service_kit/src/ops_service_kit/settings.py`): the default signs every
caller in, and a development stack or a test names the dev user.

```python
auth_mode: Literal["dev", "platform"] = "platform"
```

Check: `packages/ops_service_kit/tests/test_endpoint_settings.py` builds `Settings` with nothing set and with
`environment="production"` alone, and asserts callers are signed in and the dev user is refused. Needed: the same
assertion for every other shortcut.

## CF6 The console reads the environment in one file

Rule: only `apps/console/src/lib/api/index.ts` reads `process.env`; everything else learns the mode and the service
URLs from it.
Why: one switch between the mock and the services, in one file, is what lets a screen run on either.

Today (`apps/console/src/components/shared/ui-feedback.tsx:18`, `apps/console/src/lib/utils/logger.ts:17`): two files
read `process.env.NODE_ENV` themselves. `apps/console/src/proxy.ts:18` is the one allowed server-side read.

Pattern (`apps/console/src/lib/api/index.ts:25`):

```ts
const baseUrl = process.env.NEXT_PUBLIC_OPS_API_URL;
```

Check: `apps/console/scripts/check-standards.mjs` rule 4 (`apps/console/scripts/check-standards.mjs:73`).
