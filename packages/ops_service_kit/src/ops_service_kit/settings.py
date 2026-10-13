"""The one place the Runtime reads its environment (spec 17 section 2, rule 4).

Runtime values carry an `OPS_` prefix because a shared secret store may already define `DATABASE_URL` and
others for a different service; an unprefixed name would point the Runtime at that database. Model keys keep
their provider names so the same secrets serve every service.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The seed catalogue is the agents service's test fixture data until a registry serves definitions.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SEED_DIR = _REPO_ROOT / "services" / "agents-service" / "tests" / "fixtures" / "seed"
_DEV_SECRETS_KEY = "00" * 32
# The console's tool modules, loaded by a dev tools-service so it serves what the console's mock shows.
# tools-service's dev seed (demo modules, teams, connections), not a test fixture: a running service reads no tests/.
_TOOLS_SEED = _REPO_ROOT / "services" / "tools-service" / "seed" / "tool_modules.json"
# The development tenant, team and people platform-service seeds in dev.
_PLATFORM_SEED = _REPO_ROOT / "services" / "platform-service" / "tests" / "fixtures" / "people.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPS_", extra="ignore")

    environment: Literal["dev", "test", "production"] = "dev"
    # dev: a fixed user, no sign-in. platform: every caller is resolved from a platform-service token or API key.
    auth_mode: Literal["dev", "platform"] = "dev"
    database_url: str = "postgresql+asyncpg://ops:ops@localhost:5477/ops_runtime"
    port: int = 8700
    # OpenAI is the default chat model. A `claude-*` alias selects Anthropic when its key is set.
    model_alias: str = "gpt-5.5"
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY"))
    openai_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY"))
    cors_origins: list[str] = ["http://localhost:3016", "http://localhost:3017"]
    seed_dir: Path = _SEED_DIR
    turn_deadline_seconds: float = 120.0
    # A run holds its thread's lease and renews it every third of the TTL; a lease past expiry belongs to a dead
    # process, and the sweeper (every sweep_interval) continues that thread from its last checkpoint.
    lease_ttl_seconds: float = 15.0
    sweep_interval_seconds: float = 3.0
    # The SLA timer poller's interval (E5). 0 turns it off, as tests do to drive it one poll at a time.
    timer_poll_seconds: float = 1.0
    # The tool gateway (E3). Unset keeps write tools in this process; set, every write tool and send_reply go to the
    # gateway, which runs them only when OPA accepts the call's approval token.
    gateway_url: str | None = None
    # Model prices per million tokens by alias (E12), e.g. OPS_PRICES='{"gpt-5.5": {"input": "1.25", "output": "10"}}'.
    # An alias with no entry costs zero, which is right for a scripted or self-hosted model.
    prices: dict[str, dict[str, str]] = Field(default_factory=dict[str, dict[str, str]])
    gateway_port: int = 8720
    # Dev only: the tool-module registry is seeded from this file when it starts on an empty tenant.
    tools_seed_file: Path = _TOOLS_SEED
    # tools-service encrypts tool secrets with this AES-256 key, 64 hex characters, from your secrets manager. The
    # default is public and works in dev only.
    secrets_key: SecretStr = SecretStr(_DEV_SECRETS_KEY)
    # A CA bundle tools-service trusts for its outbound https, for systems whose certificates an internal CA issued.
    egress_ca_file: Path | None = None
    # tools-service: the team whose approvers and admins decide a module's security review (c-040). Matches the id in
    # platform-service's directory (its dev seed, tests/fixtures/people.json).
    security_team_id: str = "team_security"
    # Dev only: host names tools-service resolves to these addresses instead of asking DNS, so a use case can reach a
    # local fake as if it were a bank system. Refused outside dev.
    egress_resolve: dict[str, str] = Field(default_factory=dict[str, str])
    # models-service: model egress, aliases, keys and budgets. Unset, agents-service admits every key (E12's AdmitAll);
    # set, it asks models-service before opening a thread.
    models_url: str | None = None
    # agents-service's base URL for other services (tools-service reads its workflows); unset, the local agents port.
    agents_url: str | None = None
    models_port: int = 8730
    # agents-service's own key at models-service. With models_url, every turn runs through models-service on its
    # agent's alias, and this process needs no provider key (ADR-0008). Unset, turns use the direct provider.
    models_key: SecretStr | None = None
    # Provider credentials by the name a provider connection's `keyRef` gives, as JSON in OPS_MODEL_PROVIDER_KEYS.
    # A connection stores only the name; the value never reaches the database.
    model_provider_keys: dict[str, SecretStr] = Field(default_factory=dict[str, SecretStr])
    # How long a rotated model key's previous secret keeps working, so callers can pick up the new one.
    model_key_overlap_seconds: int = 900
    # platform-service: the identity issuer. The public port serves sign-in and the key set; the internal port serves
    # API-key introspection and is never exposed by the public host.
    platform_url: str | None = None
    platform_port: int = 8710
    platform_internal_port: int = 8711
    # base64url of the 32-byte Ed25519 private key; required outside dev, where an unset key refuses to start.
    platform_signing_key: SecretStr | None = None
    platform_signing_kid: str = "platform-1"
    # Every service a platform token may be presented to; each verifies its own name is in the token's `aud`.
    platform_audiences: list[str] = ["platform", "agents", "tools", "models", "hitl", "kb", "files"]
    # Dev only: the one password for every seeded person. Ignored outside dev, where password sign-in is closed.
    platform_demo_password: SecretStr = SecretStr("northfield-demo")
    platform_seed_file: Path = _PLATFORM_SEED
    # How long a platform token lives; a session renews it with its refresh token. Use cases shorten it to watch one
    # expire.
    platform_token_ttl_seconds: int = Field(default=900, ge=1, le=3600)
    # Service tokens (I13): each service signs the tokens it sends to another's internal routes with its own Ed25519
    # key (base64url private text, kid e.g. "svc-agents-1"). Unset in dev, a key derived from a public seed is used
    # under kid "svc-dev"; outside dev an unset key refuses to start.
    service_signing_key: SecretStr | None = None
    service_signing_kid: str = "svc-dev"
    # The services allowed to call this one's internal routes: kid -> {"service": name, "x": base64url public key}.
    # A token's `sub` must name the service its kid is bound to.
    service_public_keys: dict[str, dict[str, str]] = Field(default_factory=dict[str, dict[str, str]])
    gateway_sub: str = "runtime:local"
    opa_url: str = "http://127.0.0.1:8181"
    # The review service signs approval tokens with this HMAC key; the gateway hands it to OPA, which verifies them.
    review_key: SecretStr = SecretStr("dev-review-key-not-secret")
    review_token_ttl_seconds: int = 900
    # An expired approval token is renewed from its recorded approvals while they are younger than this; older, the
    # call needs a fresh review (durability-failure-and-audit.md, approval expiry).
    approval_renewal_max_age_seconds: int = 86400
    # Chat approvals by the person who asked the agent. An owner decision is pending; True keeps today's behaviour.
    # Money reviews in Reviews always need distinct approvers, and workflow reviews are never decided by the requester.
    allow_self_approval_in_chat: bool = True
    # Dev only: an agent or workflow publish request is approved as it is made, so one person can take a draft live.
    # Ignored outside dev, where publishing waits for a reviewer.
    registry_auto_approve: bool = True
    dev_user_name: str = "James Richardson"
    dev_user_email: str = "j.richardson@northfieldbank.com"

    @model_validator(mode="after")
    def _refuse_dev_auth_outside_dev(self) -> Settings:
        # The fixed dev user exists for the walking skeleton only (spec 17 section 5, Auth).
        if self.auth_mode == "dev" and self.environment != "dev":
            raise ValueError(f"auth_mode 'dev' is refused when environment is {self.environment}")
        if self.environment != "dev" and self.review_key.get_secret_value() == "dev-review-key-not-secret":
            raise ValueError("review_key must be set outside dev; the default is public")
        key = self.secrets_key.get_secret_value()
        if len(key) != 64 or any(c not in "0123456789abcdefABCDEF" for c in key):
            raise ValueError("secrets_key must be 64 hex characters (an AES-256 key)")
        if self.environment != "dev" and key == _DEV_SECRETS_KEY:
            raise ValueError("secrets_key must be set outside dev; the default is public")
        if self.environment != "dev" and self.egress_resolve:
            raise ValueError("egress_resolve is for dev only; outside dev, names resolve through DNS")
        if not self.seed_dir.is_dir():
            raise ValueError(f"seed_dir {self.seed_dir} does not exist")
        return self
