"""The one place the Runtime reads its environment (spec 17 section 2, rule 4).

Runtime values carry an `OPS_` prefix because a shared secret store may already define `DATABASE_URL` and
others for a different service; an unprefixed name would point the Runtime at that database. Model keys keep
their provider names so the same secrets serve every service.
"""

from __future__ import annotations

import json
import os
from functools import cache
from importlib.metadata import entry_points
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from .flags import Flags
from .flags import check as check_flags

_REPO_ROOT = Path(__file__).resolve().parents[4]
# Each service's dev seed lives in its own seed/ folder. A running service reads no tests/ path
# (check_standards rule 3b), so a change to a test fixture cannot change what the product shows.
_SEED_DIR = _REPO_ROOT / "services" / "agents-service" / "seed"
_DEV_SECRETS_KEY = "00" * 32
_DEV_REVIEW_KEY = "dev-review-key-not-secret"
# The console's tool modules, loaded by a dev tools-service so it serves what the console's mock shows.
_TOOLS_SEED = _REPO_ROOT / "services" / "tools-service" / "seed" / "tool_modules.json"
# The development tenant, team and people platform-service seeds in dev.
_PLATFORM_SEED = _REPO_ROOT / "services" / "platform-service" / "seed" / "people.json"


# The entry point group installed plugin packages register under; equals ops_plugin_sdk.loader.GROUP (a tools-service
# test holds the two together, since this package does not import the plugin kit).
PLUGIN_ENTRY_POINTS = "ops_ai.plugins"


@cache
def _installed_plugins() -> bool:
    """Whether any installed package registers a plugin; read once per process, as the installed set only changes
    with a new image."""
    return bool(entry_points(group=PLUGIN_ENTRY_POINTS))


def _secrets_dir() -> Path | None:
    """Secrets as files (Docker and Kubernetes secrets): a file per setting, named after its env name in any case
    (ops_review_key for OPS_REVIEW_KEY), read when no env value is set. /run/secrets unless OPS_SECRETS_DIR names
    another folder; none when the folder does not exist."""
    folder = Path(os.environ.get("OPS_SECRETS_DIR") or "/run/secrets")
    return folder if folder.is_dir() else None


class PluginClient(BaseModel):
    """An OAuth client the install registered with a plugin's vendor: its id and its secret."""

    id: str = Field(min_length=1)
    secret: SecretStr


class Settings(BaseSettings):
    # An empty value is unset, so a compose file can name every setting and leave the ones a site does not use blank.
    model_config = SettingsConfigDict(
        env_prefix="OPS_", extra="ignore", secrets_dir=_secrets_dir(), env_ignore_empty=True
    )

    environment: Literal["dev", "test", "production"] = "dev"
    # dev: a fixed user, no sign-in. platform: every caller is resolved from a platform-service token or API key.
    auth_mode: Literal["dev", "platform"] = "dev"
    database_url: str = "postgresql+asyncpg://ops:ops@localhost:5477/ops_runtime"
    # How long one attempt to open a database connection may take, and how many attempts are made before the connect
    # fails (ops_store.database). On a loaded host the first attempt has stalled for a minute with no reply.
    database_connect_timeout_s: float = 30.0
    database_connect_attempts: int = 3
    # The address every service's HTTP server listens on. A container sets 0.0.0.0 so other containers reach it; on a
    # host the default keeps each port local to the machine. `*` listens on every address, IPv4 and IPv6: a Fly
    # machine needs both (health checks arrive over IPv4, the private network is IPv6), and `::` alone is IPv6 only
    # because asyncio sets IPV6_V6ONLY on the sockets it opens.
    bind_host: str = "127.0.0.1"
    port: int = 8700
    # The runtime's alias, which models-service serves; no vendor model is named here (a direct call sets one).
    model_alias: str = "default"
    # The alias a chat reply reruns on when the person taps Think harder (OPS_THINK_HARDER_ALIAS); empty offers no chip.
    think_harder_alias: str = "thinking"
    # With the flag tool_search on, an agent with more granted tools than this searches for its tools instead
    # of being sent every schema; 0 means always, None the agent kernel's default (TOOL_SEARCH_ABOVE, 20).
    tool_search_above: int | None = Field(default=None, ge=0)
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY"))
    openai_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY"))
    # Read here only so the agents kernel's direct path can refuse an Azure key; models-service reads and checks
    # the install's model connection itself (ops_models.connection_settings), so no other service fails on it.
    openai_api_type: str | None = Field(default=None, validation_alias=AliasChoices("OPENAI_API_TYPE"))
    cors_origins: list[str] = ["http://localhost:3016", "http://localhost:3017"]
    # agents-service's catalogue and start-up seeds. Outside dev it is unset unless named, so production starts empty;
    # tests name tests/fixtures/seed.
    seed_dir: Path | None = _SEED_DIR
    # The chat agents to seed, when not seed_dir's chat_agents.json.
    agents_seed_file: Path | None = None
    # Dev only: channel deployments to seed at start (a graph on a channel), e.g. services/agents-service/seed/
    # deployments.json. Rows that exist are updated to the file.
    deployments_seed_file: Path | None = None
    # Mail in is a team's own mailbox records (Channels > Email), each read by its provider; a dev stack's are on
    # GreenMail. No setting names a mailbox.
    # The IMAP server a mailbox of provider gmail signs in to.
    gmail_imap_host: str = "imap.gmail.com"
    # The SMTP server a Gmail mailbox's replies go through when its sender names none.
    gmail_smtp_host: str = "smtp.gmail.com"
    graph_url: str = "https://graph.microsoft.com"
    graph_login_url: str = "https://login.microsoftonline.com"
    # The install's own Microsoft 365 app, for mail_provider "graph" only: the platform's sender, not a team's mailbox.
    graph_tenant_id: str | None = None
    graph_client_id: str | None = None
    graph_client_secret: SecretStr | None = None
    # Dev only: the team mailboxes to connect at start (Channels > Email records), e.g. services/agents-service/seed/
    # mailboxes.json. Rows that exist are replaced by the file's.
    mailboxes_seed_file: Path | None = None
    # How often the workflow worker reads each bound mailbox.
    email_poll_seconds: float = 30.0
    # Mail out (packages/ops_email): "none" fails every send with that reason; "smtp", "resend" and "graph" send from
    # `mail_from`; "fake" is dev only and writes each message to `mail_fake_out_dir`.
    mail_provider: Literal["none", "fake", "smtp", "resend", "graph"] = "none"
    mail_from: str | None = None
    mail_fake_out_dir: Path = _REPO_ROOT / ".run" / "fake-mail-out"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    # The install's own SMTP account: system-wide. A team sends from its own mailbox records, each with its secret.
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    # How long one IDLE on an IMAP mailbox waits before the listener asks again.
    email_idle_seconds: float = 25.0
    resend_url: str = "https://api.resend.com"
    resend_api_key: SecretStr | None = None
    turn_deadline_seconds: float = 120.0
    # A run holds its thread's lease and renews it every third of the TTL; a lease past expiry belongs to a dead
    # process, and the sweeper (every sweep_interval) continues that thread from its last checkpoint.
    lease_ttl_seconds: float = 15.0
    sweep_interval_seconds: float = 3.0
    # The SLA timer poller's interval (E5). 0 turns it off, as tests do to drive it one poll at a time.
    timer_poll_seconds: float = 1.0
    # The workflow runner's worker (`python -m ops_agents.api.worker`): how often an idle worker polls engine_work, and
    # how many runs one worker process runs at once.
    engine_poll_seconds: float = 0.5
    engine_concurrency: int = 4
    # How often the worker's run reconciler looks for runs nothing is working on and marks them Stuck.
    engine_reconcile_seconds: float = Field(default=60.0, gt=0)
    # One JSON line per request on the ops.request logger and a Server-Timing header; off by default because
    # Server-Timing tells a caller how long internal work took.
    request_timing: bool = False
    # Feature flags turned on for this install, from the install config: OPS_FLAGS=mcp_gateway,tool_search (a
    # JSON list also reads). Every flag is off unless named; a name not in ops_service_kit.flags.FLAGS stops the service
    # at start.
    flags: Annotated[list[str], NoDecode] = Field(default_factory=list[str])
    # The install's one plugins folder: each plugin is a folder in it, put there by `ops plugin
    # install`. The repo's plugins/ locally; a mounted volume in Docker and Kubernetes (OPS_PLUGINS_DIR). tools-service
    # loads every plugin in it at start, and kb-service reads knowledge through them, whenever it holds any.
    plugins_dir: Path = _REPO_ROOT / "plugins"
    # Plugin package folders tools-service loads beside the plugins folder, for a developer trying a plugin on a
    # local stack before it is packaged: OPS_PLUGIN_PATHS='["/path/to/src/ops_plugin_x"]'. Empty everywhere else.
    plugin_paths: list[str] = Field(default_factory=list[str])
    # The install's own OAuth client for each plugin, registered once with the vendor and used by every team that does
    # not bring its own: OPS_PLUGIN_CLIENTS='{"opsai.salesforce": {"id": "...", "secret": "..."}}', set from the
    # deploy's secret store. A client id and secret an account admin saves in the console take its place.
    plugin_clients: dict[str, PluginClient] = Field(default_factory=dict[str, PluginClient])
    # Settings fixed for every team of a plugin, which no team can change: OPS_PLUGIN_LOCKED='{"opsai.salesforce":
    # {"api_version": "61.0"}}'. An installed plugin is offered to every team; each team turns it on for itself.
    plugin_locked: dict[str, dict[str, str | int | float | bool]] = Field(
        default_factory=dict[str, dict[str, str | int | float | bool]]
    )
    # The most text one call to agents-service's AI step route reads (tick 31): the kernel caps a step at two
    # model calls, so this bounds what one outside call can spend.
    ai_step_max_text_chars: int = Field(default=50_000, ge=1)
    # AI step route calls a team may make in a minute: the model key's budget is the service's, not the team's.
    ai_step_calls_per_minute: int = Field(default=60, ge=1)
    # Fault injection for the use case that proves crash recovery (uc-081), never set on a real deployment: the worker
    # kills itself with SIGKILL right after this node's step row is recorded, and with the second the wrapper ignores
    # recorded steps, which is the failure the use case must catch.
    engine_fault_kill_after_node: str | None = None
    engine_fault_ignore_recorded: bool = False
    # Fault injection for uc-567, never set on a real deployment: the mail listener fails to start the run of a message
    # whose subject contains this, as a message that breaks a start would, so the use case sees it set aside.
    email_fault_fail_subject: str | None = None
    # The tool gateway (E3). Unset keeps write tools in this process; set, every write tool and send_reply go to the
    # gateway, which runs them only when OPA accepts the call's approval token.
    gateway_url: str | None = None
    # tools-service, for agents-service to apply a tool module review decided in Reviews. Unset, the gateway's
    # address is used; with neither, a decision waits to be applied.
    tools_url: str | None = None
    # Model prices per million tokens by alias (E12), e.g. OPS_PRICES='{"default": {"input": "1.25", "output": "10"}}'.
    # An alias with no entry costs zero, which is right for a scripted or self-hosted model.
    prices: dict[str, dict[str, str]] = Field(default_factory=dict[str, dict[str, str]])
    gateway_port: int = 8720
    # Dev only: the tool-module registry is seeded from this file when it starts on an empty tenant.
    tools_seed_file: Path = _TOOLS_SEED
    # tools-service encrypts tool secrets with this AES-256 key, 64 hex characters, from your secrets manager. The
    # default is public and works in dev only.
    secrets_key: SecretStr = SecretStr(_DEV_SECRETS_KEY)
    # Where secret values are kept (ops_service_kit.credentials): `sealed` seals each into its row under secrets_key;
    # `memory` keeps them in the process, for running a suite on a vault-shaped adapter, refused outside dev and test.
    credential_store: Literal["sealed", "memory"] = "sealed"
    # A CA bundle tools-service trusts for its outbound https, for systems whose certificates an internal CA issued.
    egress_ca_file: Path | None = None
    # The id a new workspace's Security team is given: the first workspace's (`python -m ops_platform.bootstrap`) and
    # the dev seed's (seed/people.json). A running service reads each workspace's own record, never this.
    security_team_id: str = "team_security"
    # Dev only: host names tools-service resolves to these addresses instead of asking DNS, so a use case can reach a
    # local fake as if it were a bank system. Refused outside dev.
    egress_resolve: dict[str, str] = Field(default_factory=dict[str, str])
    # models-service: model egress, aliases, keys and budgets. Unset, agents-service admits every key (E12's AdmitAll);
    # set, it asks models-service before opening a thread.
    models_url: str | None = None
    # kb-service's base URL. Set, agents search its knowledge bases and check thread grants against them; unset, the
    # fixture catalogue's knowledge stands in (unit tests).
    kb_url: str | None = None
    # agents-service's base URL for other services (tools-service reads its workflows); unset, the local agents port.
    agents_url: str | None = None
    models_port: int = 8730
    kb_port: int = 8740
    # Where kb-service keeps uploaded files and their records (the files-service library on a local object store).
    kb_files_dir: Path = _REPO_ROOT / ".data" / "kb-files"
    # files-service: its port, its base URL for other services (unset, the local port), and where the local backend
    # keeps objects. Scanning "off" marks files clean at completion; files-service refuses it outside dev (files 5.3.1),
    # and the stack sets it for dev. The default passes everywhere, so no other service's Settings depends on it;
    # "eicar" scans inline with the EICAR test engine; "hook" leaves files pending until a scanner posts a result.
    files_port: int = 8750
    files_url: str | None = None
    # documents-service: what is read from a file, beside files-service, which keeps the bytes.
    documents_port: int = 8760
    documents_url: str | None = None
    # The OCR mode files are read with for a knowledge source and for a chat attachment or read_file: "auto" reads
    # scanned pages and the picture parts of mixed pages, "off" reads text layers only, "always" OCRs every page.
    # A server without Tesseract reports OCR as missing in documents-service's /health and fails each scanned page.
    kb_ocr: Literal["off", "auto", "always"] = "auto"
    attachments_ocr: Literal["off", "auto", "always"] = "auto"
    # runner-service: runs code tools' functions in Python on WASM, with no network and no secrets.
    # tools-service calls it at runner_url; unset, a code operation fails runner_unavailable. The CPython WASI build is
    # fetched by `make -C services/runner-service wasm` from runner_wasm_url into runner_cache_dir, and the runner
    # refuses to start unless its SHA-256 is runner_wasm_sha256. Concurrency bounds host memory: the base plus N times
    # a run's memory cap.
    runner_port: int = 8770
    runner_url: str | None = None
    runner_wasm_url: str = (
        "https://github.com/vmware-labs/webassembly-language-runtimes/releases/download/"
        "python%2F3.12.0%2B20231211-040d5a6/python-3.12.0.wasm"
    )
    runner_wasm_sha256: str = "e5dc5a398b07b54ea8fdb503bf68fb583d533f10ec3f930963e02b9505f7a763"
    runner_cache_dir: Path = _REPO_ROOT / ".data" / "runner"
    # wasmtime's compiled-module cache; unset, runner_cache_dir/compiled. Kubernetes points it under /tmp, since its
    # read-only root filesystem leaves the build's folder unwritable.
    runner_compiled_dir: Path | None = None
    runner_concurrency: int = 2
    # The most a code operation may ask for; its own limits default to 256 MB, 10 s and 20 calls.
    runner_max_memory_mb: int = 1024
    runner_max_time_s: float = 60.0
    runner_max_calls: int = 100
    # files-service's public base, path included (e.g. https://ops.example/api/files), when a proxy serves it under a
    # path it strips: every upload and download URL the service hands out is built on it. Unset, the request's base.
    files_public_url: str | None = None
    files_dir: Path = _REPO_ROOT / ".data" / "files"
    files_scanning: Literal["off", "eicar", "hook"] = "hook"
    # This process's own key at models-service: agents-service's turns, files-service's extractions. With
    # models_url, every model call runs through models-service on its alias, and no process needs a provider key
    # (ADR-0008). Unset, agents-service's turns use the direct provider and files-service cannot extract.
    models_key: SecretStr | None = None
    # Dev only: provider credentials by the name a provider connection's `keyRef` gives, as JSON in
    # OPS_MODEL_PROVIDER_KEYS, behind the keys an account admin saves on Settings > Model providers. Outside dev a key
    # here stops models-service's start-up.
    model_provider_keys: dict[str, SecretStr] = Field(default_factory=dict[str, SecretStr])
    # models-service dev seed: with this set (the fake OpenAI's /v1 URL, services/models-service/scripts/fake_openai),
    # it seeds connection openai-local at that URL and binds alias default to it. The row is the switch afterwards:
    # PUT the connection's baseUrl to https://api.openai.com/v1 to make the same alias real.
    models_fake_openai_url: str | None = None
    # How long a rotated model key's previous secret keeps working, so callers can pick up the new one.
    model_key_overlap_seconds: int = 900
    # platform-service: the identity issuer. The public port serves sign-in and the key set; the internal port serves
    # API-key introspection and is never exposed by the public host.
    platform_url: str | None = None
    platform_port: int = 8710
    platform_internal_port: int = 8711
    # How long a closed workspace can be restored by its owner before its records are purged, and how long a team stays
    # archived before it can be deleted. The use-case stack sets both to 0.
    workspace_restore_days: int = 30
    team_delete_after_days: int = 30
    # Where other services reach the internal port to introspect API keys. Unset: this machine's internal port, as when
    # every service runs on one host; each in its own container names platform-service's address on a private network.
    platform_internal_url: str | None = None
    # base64url of the 32-byte Ed25519 private key; required outside dev, where an unset key refuses to start.
    platform_signing_key: SecretStr | None = None
    platform_signing_kid: str = "platform-1"
    # Every service a platform token may be presented to; each verifies its own name is in the token's `aud`.
    platform_audiences: list[str] = ["platform", "agents", "tools", "models", "hitl", "kb", "files", "documents"]
    # Dev only: the one password for every seeded person. Ignored outside dev, where password sign-in is closed.
    platform_demo_password: SecretStr = SecretStr("northfield-demo")
    platform_seed_file: Path = _PLATFORM_SEED
    # Dev only: the sample teams' manifests (`make sample-teams` installs them). Their people who have an account are
    # offered on the dev sign-in page beside the seed's; a missing folder offers none.
    platform_sample_teams_dir: Path = _REPO_ROOT / "scripts" / "sample-team" / "teams"
    # Dev seed only: on, every seeded person also holds Admin in every team, so a person trying the console is never
    # held back by a role. Off by default: the seed's own roles stand, so a viewer is a viewer and a role test
    # means something. Never read by migrations, the bootstrap or any product default.
    seed_everyone_admin: bool = False
    # Sign-in. platform-service's public origin, which identity providers send people back to (the OIDC
    # redirect URI and the SAML consumer URL are built on it), and the console's origin, where a finished SSO sign-in
    # and a reset link land. Unset, SSO and reset refuse with `sso_not_configured`.
    platform_public_url: str | None = None
    console_url: str | None = None
    # The DNS servers that prove a workspace's email domain by its TXT record, as `host:port`; empty asks the
    # system's resolvers. A bank that resolves through its own servers names them here.
    signin_dns_servers: list[str] = Field(default_factory=list[str])
    signin_dns_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    # Wrong passwords (sign-in and step-up together) a person may type in a window before both refuse them for the
    # lockout time, and reset links one person may be sent per window. A used reset link ends a lock.
    # The service provider's own key pair for SAML, PEM: it signs requests to identity providers that ask for
    # it, decrypts assertions encrypted to the certificate, and the certificate is published in the SP metadata. Unset,
    # a provider cannot be set to sign requests or require encryption.
    saml_sp_key: SecretStr | None = None
    saml_sp_certificate: str | None = None
    signin_max_failures: int = Field(default=5, ge=1)
    signin_failure_window_seconds: int = Field(default=900, ge=1)
    signin_lockout_seconds: int = Field(default=900, ge=1)
    password_reset_max_per_window: int = Field(default=3, ge=1)
    password_reset_window_seconds: int = Field(default=3600, ge=1)
    # PBKDF2-SHA256 work factor for stored passwords; a hash made with fewer is replaced at the next sign-in.
    password_hash_iterations: int = Field(default=600_000, ge=1)
    password_min_length: int = Field(default=12, ge=8)
    # How long a round trip to an identity provider may take, and how long a reset link works.
    signin_flow_seconds: int = Field(default=600, ge=30)
    password_reset_seconds: int = Field(default=3600, ge=60)
    # platform-service's first tenant, its Security team (named by security_team_id) and one admin, written once by
    # `python -m ops_platform.bootstrap` where nothing seeds, as on a staging or production install. Unset outside that
    # step; the password is the admin's first one, changed after sign-in.
    bootstrap_tenant_id: str | None = None
    bootstrap_tenant_name: str | None = None
    # One tenant per install (`single`, the default: a bank runs its own deployment, its tenant bootstrap_tenant_id or
    # the dev seed's `local`) or many on one deployment (`multi`, created by the provisioner). Every code path
    # and isolation rule is the same in both; single only refuses creating any other tenant, 409 single_tenant.
    tenancy_mode: Literal["single", "multi"] = "single"
    bootstrap_team_name: str | None = None
    bootstrap_admin_email: str | None = None
    bootstrap_admin_name: str | None = None
    bootstrap_admin_password: SecretStr | None = None
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
    # The `area:action` scopes each calling service may hold in its tokens to this one (ops_access). A token listing a
    # scope its service is not given here is refused, so no service can mint itself more than this.
    # Every service-to-service call is on a public route, so each caller's needs are listed here.
    service_scopes: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "scanner": ["files:decide"],
            # runner-service sends a running code operation's calls back to tools-service.
            "runner": ["tools:run"],
            # documents:view, documents:run: kb-service indexes each file of a source from its reading in
            # documents-service.
            "kb": ["files:view", "files:create", "files:edit", "agents:view", "documents:view", "documents:run"],
            # The workflow worker reads a file an Extract from file step names.
            # It also stores the attachments of mail that starts a workflow.
            # deployments:run: it reads the IMAP mailboxes workflows watch through tools-service.
            # settings:view: its memory sweep reads the tenant's memoryRetentionDays policy on platform-service.
            # documents:view, documents:run: the Extract from file step reads a file through documents-service and a
            # workflow save pins its document type versions there.
            # documents:delete: the system workflow on the file-deleted trigger purges what was derived from the file.
            # files:edit: a Save data on file step records what was read on the file.
            "agents": [
                "files:view",
                "files:create",
                "files:edit",
                "knowledge:view",
                "tools:view",
                # connections:view: the Tools page's app state for the person it lists for, claimed only on that read.
                "connections:view",
                "deployments:run",
                "settings:view",
                "documents:view",
                "documents:run",
                "documents:delete",
                # secrets_egress:manage: an approved held host joins the tenant's allow-list in tools-service;
                # claimed only on that call (GatewayClient.egress_host_decision).
                "secrets_egress:manage",
            ],
            # deployments:view: it reads a mailbox's reply sender when a send_reply names the mailbox.
            # settings:view: a tool module publish reads the team's publishReview live.
            # cases:view, cases:create: the open_case tool opens a case in the caller's team.
            # events:emit: it reports tool access and module review requests as service events.
            # tools:publish: its seed opens the reviews of module versions waiting for one, on the publisher's behalf;
            # agents-service takes that token only for a tool module of the team it is scoped to.
            # files:view, documents:view, documents:run: the read_file and read_document tools read a file of the
            # caller's team through documents-service.
            # agents:view: an app's "who uses it" asks agents-service which of the team's agents and workflows use its
            # tools, before a team admin turns it off. knowledge:view: search_knowledge searches the calling
            # team's knowledge bases through kb-service.
            "tools": [
                "agents:view",
                "knowledge:view",
                "workflows:view",
                "deployments:view",
                "settings:view",
                "cases:view",
                "cases:create",
                "events:emit",
                "tools:publish",
                "files:view",
                "documents:view",
                "documents:run",
            ],
            # events:emit: it reports a deleted file as a service event, which purges what was derived from it.
            "files": ["events:emit"],
            # files:view, files:edit: documents-service reads the bytes it reads from as the caller's team and keeps a
            # sample's file with a reference; settings:view: the extractionFloor policy.
            # events:emit: it reports a person's correction as a service event, which saves it on the file.
            # tools:view: it reads the document type templates of the plugins on for the caller's team.
            # workflows:view: before a document type is deleted it asks agents-service which workflows read it.
            "documents": ["files:view", "files:edit", "settings:view", "events:emit", "tools:view", "workflows:view"],
            # workflows:view: it reads a team's runs in progress and live workflows before the team is deleted or its
            # workspace closed. connections:delete: a member removed from a team has their own accounts on its
            # apps deleted in tools-service. tools:create, agents:create: a new team's defaults are written
            # by each service when platform-service reports the team.
            "platform": ["workflows:view", "connections:delete", "tools:create", "agents:create"],
        }
    )
    # The embed app's own origins (apps/embed), such as https://ops.bank.example. A widget request from one of
    # them speaks for the bank page its session names; nothing in the request (Host, X-Forwarded-Host) can add one.
    embed_origins: list[str] = Field(default_factory=list[str])
    # The proxies a hosted form's submission may pass through on its way here, as CIDRs: the client address is
    # the right-most X-Forwarded-For entry outside them, so everyone behind the embed app is not counted as one address.
    # Set per deploy: the compose network the embed app reaches agents from, or Caddy and the embed app on Fly.
    forms_trusted_proxies: list[str] = Field(default_factory=lambda: ["127.0.0.1/32"])
    gateway_sub: str = "runtime:local"
    opa_url: str = "http://127.0.0.1:8181"
    # make/env.mk's OPS_INFRA: "external" in the devcontainer, where PostgreSQL and OPA are compose side containers and
    # there is no docker to start a private OPA (opa_server.py).
    infra: str = ""
    # The review service signs approval tokens with this HMAC key; the gateway hands it to OPA, which verifies them.
    review_key: SecretStr = SecretStr(_DEV_REVIEW_KEY)
    review_token_ttl_seconds: int = 900
    # An expired approval token is renewed from its recorded approvals while they are younger than this; older, the
    # call needs a fresh review (durability-failure-and-audit.md, approval expiry).
    approval_renewal_max_age_seconds: int = 86400
    # Dev only: an agent or workflow publish request is approved as it is made, so one person can take a draft live.
    # Ignored outside dev, where publishing waits for a reviewer.
    registry_auto_approve: bool = True
    dev_user_name: str = "James Richardson"
    dev_user_email: str = "j.richardson@harborpine.example"
    # Dev only: the access policies the dev caller's identity carries, as a platform token would, e.g.
    # OPS_DEV_POLICIES='{"requesterMayDecide": false}'. Empty: every policy at its open default.
    dev_policies: dict[str, Any] = Field(default_factory=dict[str, Any])

    @field_validator("bind_host")
    @classmethod
    def _every_address(cls, value: str) -> str:
        # uvicorn hands the host to asyncio's create_server, where an empty host opens one socket per address family.
        return "" if value == "*" else value

    @model_validator(mode="after")
    def _refuse_dev_auth_outside_dev(self) -> Settings:
        # The fixed dev user exists for the walking skeleton only (spec 17 section 5, Auth).
        if self.auth_mode == "dev" and self.environment != "dev":
            raise ValueError(f"auth_mode 'dev' is refused when environment is {self.environment}")
        key = self.secrets_key.get_secret_value()
        if len(key) != 64 or any(c not in "0123456789abcdefABCDEF" for c in key):
            raise ValueError("secrets_key must be 64 hex characters (an AES-256 key)")
        if self.environment not in ("dev", "test") and self.credential_store == "memory":
            raise ValueError("credential_store 'memory' is for dev and test only; its values are lost on restart")
        if self.environment != "dev" and self.egress_resolve:
            raise ValueError("egress_resolve is for dev only; outside dev, names resolve through DNS")
        faults = self.engine_fault_kill_after_node is not None or self.engine_fault_ignore_recorded
        if self.environment not in ("dev", "test") and faults:
            raise ValueError("engine_fault_* settings are for dev and test only; they break crash recovery on purpose")
        if self.environment not in ("dev", "test") and self.email_fault_fail_subject:
            raise ValueError("email_fault_fail_subject is for dev and test only; it fails mail on purpose")
        if self.environment != "dev" and "seed_dir" not in self.model_fields_set:
            self.seed_dir = None
        if self.seed_dir is not None and not self.seed_dir.is_dir():
            raise ValueError(f"seed_dir {self.seed_dir} does not exist")
        return self

    @field_validator("flags", mode="before")
    @classmethod
    def _flag_list(cls, value: object) -> object:
        # An operator writes names separated by commas; the JSON list form the other list settings use reads too.
        if isinstance(value, str):
            text = value.strip()
            return json.loads(text) if text.startswith("[") else [n.strip() for n in text.split(",") if n.strip()]
        return value

    @model_validator(mode="after")
    def _known_flags(self) -> Settings:
        check_flags(self.flags)
        return self

    @property
    def feature_flags(self) -> Flags:
        """The install's flags; services read a flag only through this."""
        return Flags(frozenset(self.flags))

    @property
    def plugin_folders(self) -> list[str]:
        """Every plugin folder to load: each folder in plugins_dir (hidden ones and caches skipped), then
        plugin_paths."""
        d = self.plugins_dir
        dropped = (
            sorted(str(f) for f in d.iterdir() if f.is_dir() and not f.name.startswith((".", "_")))
            if d.is_dir()
            else []
        )
        return [*dropped, *self.plugin_paths]

    @property
    def plugins(self) -> bool:
        """Whether this install has any plugin: one in the plugins folder, a developer's plugin path, or an installed
        plugin package. With none, no plugin is read, no plugin route is mounted and kb-service calls no tool."""
        return bool(self.plugin_folders) or _installed_plugins()

    @model_validator(mode="after")
    def _plugin_scopes(self) -> Settings:
        # kb-service reads a plugin's knowledge through tools-service. Its scope cap gains the two tools scopes
        # only when the install has plugins, so a kb token on an install without any can never act on a tool.
        if self.plugins and "service_scopes" not in self.model_fields_set:
            kb = self.service_scopes.get("kb", [])
            extra = [s for s in ("tools:view", "tools:run") if s not in kb]
            self.service_scopes = {**self.service_scopes, "kb": [*kb, *extra]}
        return self


_PUBLIC_DEFAULTS = {"review_key": _DEV_REVIEW_KEY, "secrets_key": _DEV_SECRETS_KEY}


def require_keys(settings: Settings, *names: str) -> None:
    """Refuses to start a service outside dev while a key it uses still holds its public default. Called by each
    service that uses the key, so a service that does not use one is never handed it (`review_key`: agents-service and
    its worker, tools-service; `secrets_key`: tools-service, files-service, models-service, platform-service)."""
    if settings.environment == "dev":
        return
    for name in names:
        value = getattr(settings, name).get_secret_value()
        if value == _PUBLIC_DEFAULTS[name]:
            raise ValueError(f"{name} must be set outside dev; the default is public")


# Addresses of running services that make exports for the stack it starts (make/env.mk). A test whose Settings picked
# one up would call the shared stack, so its result would depend on whether that stack is up: an agents test read the
# publish policy from a stopped platform-service and held a publish it meant to apply.
STACK_SERVICE_ENV = ("OPS_PLATFORM_URL",)


def isolate_from_stack() -> None:
    """Drops the running stack's service addresses from the environment before a test run builds any Settings. Here
    because this module is the one place the environment is read or written (check_standards rule 4)."""
    for name in STACK_SERVICE_ENV:
        os.environ.pop(name, None)
