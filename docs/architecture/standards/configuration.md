# Standards: configuration

Status: target state. Part of the [engineering standards](../engineering-standards.md); ids `CF1` to `CF6` are frozen.

Every process reads its configuration once, from one typed settings object, and fails at start when a value it needs
is missing. Nothing in code names a host, a port, a URL, a model or a timeout.

## CF1 One settings object per process

Rule: each process builds one `ops_service_kit.settings.Settings` (pydantic-settings, `OPS_` prefix) at start and
passes it down; no other module reads `os.environ`, `getenv` or `process.env`.
Why: configuration read in one place can be listed, validated and documented; a read scattered through code cannot.

Today: no breach in Python; the console has four files outside the entry module that read `process.env` (see `CF6`).

Pattern (`packages/ops_service_kit/src/ops_service_kit/settings.py:64`):

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPS_", extra="ignore", secrets_dir=_secrets_dir(), env_ignore_empty=True)
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

Today (`services/kb-service/src/ops_kb/app.py:152`): a loopback fallback and a literal timeout beside the setting.

```python
http = httpx.AsyncClient(base_url=settings.agents_url or f"http://127.0.0.1:{settings.port}", timeout=5)
```

Also `services/agents-service/src/ops_agents/api/acting_for.py:86` (same fallback),
`services/agents-service/src/ops_agents/api/worker.py:94` (`timeout=10`) and
`packages/ops_service_kit/src/ops_service_kit/opa_server.py:40` (port 8181). The audit counted 20 loopback literals
and about 58 literal timeouts in service code.

Pattern (`packages/ops_service_kit/src/ops_service_kit/settings.py:76`): the value is a named setting with its reason.

```python
database_connect_timeout_s: float = 30.0
database_connect_attempts: int = 3
```

Check: no check yet. Needed: a grep ratchet over `services/*/src` and `packages/*/src` for `127.0.0.1`, `localhost`,
`timeout=<digits>` and `:<port>` literals, with today's count as the ceiling and the loopback count driven to 0.

## CF3 A missing required setting stops the process at start

Rule: a service checks every setting it needs when it starts and exits naming the setting; a missing value is never
found by the first request.
Why: a half-configured service in production serves wrong answers; one that refuses to start is noticed at deploy.

Today: the fallbacks in `CF2` are the breach: with `OPS_AGENTS_URL` unset, kb-service starts and calls itself.

Pattern (`packages/ops_service_kit/src/ops_service_kit/settings.py:611`): a key still holding its public default
stops the service outside dev.

```python
def require_keys(settings: Settings, *names: str) -> None:
    ...
    raise ValueError(f"{name} must be set outside dev; the default is public")
```

Also `services/models-service/src/ops_models/__main__.py:39`: a provider key left in settings outside dev raises
`SystemExit` with the fix in the message.

Check: no check yet. Needed: a boot test per service that starts the app with each required setting removed and asserts
the exit names it.

## CF4 Secrets come only from the secret store

Rule: a secret reaches code only through the settings class (`SecretStr`, `secrets_dir`) or
`ops_service_kit.credentials`; no secret appears in code, fixtures, seeds, `openapi.json`, logs or test output, and
`.env.example` is the only environment file in git.
Why: the repository is public, and a secret in a log or fixture leaks through every copy of it.

Today: no known breach; the leak scan is required on `main` only, so a red scan does not stop a merge to the
development trunk.

Pattern (`packages/ops_service_kit/src/ops_service_kit/settings.py:91`):

```python
anthropic_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY"))
```

Check: `scripts/leak_scan.py` in `.github/workflows/leak-scan.yml` on every pull request. Needed: make the scan a
required check on the development trunk.

## CF5 The default is the safe production value

Rule: a setting's default is the value production should run with; a development shortcut turns on only when
`environment` names development.
Why: a forgotten setting must not open a door in production.

Today (`packages/ops_service_kit/src/ops_service_kit/settings.py:72`): the default runs with no sign-in.

```python
auth_mode: Literal["dev", "platform"] = "dev"
```

Pattern (`packages/ops_service_kit/src/ops_service_kit/settings.py:611`): `require_keys` refuses a public default
outside dev, so the unsafe default cannot reach production.

Check: no check yet. Needed: a test that builds `Settings` with `environment="production"` and no other variable, and
asserts every shortcut is off or the build refuses.

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
