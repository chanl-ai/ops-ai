"""models-service's tables, in its own migration chain (`alembic_version_models`).

A provider connection names its credential (`key_ref`) and never holds it: the credential is a row of provider_keys,
the account's, sealed under the service's secrets key and set by an account admin. An alias has immutable versions; the
newest version that is not retired serves calls. A model key belongs to one identity (a workflow, an agent, a person
or a platform purpose) and carries its budget, its spend and a hash of its secret, plus the previous hash during a
rotation's overlap. A model call row is metadata only: never a prompt or a completion.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from ops_store.dialect import db_now
from ops_store.listing import LISTED
from ops_store.schema import TENANT_SCOPED, system

metadata = sa.MetaData()

MONEY = sa.Numeric(18, 6)

provider_connections = sa.Table(
    "provider_connections",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("name", sa.String(120), nullable=False, unique=True, info=LISTED),
    # openai-compatible | azure-openai | anthropic | scripted
    sa.Column("type", sa.String(32), nullable=False, info=LISTED),
    sa.Column("base_url", sa.String(400)),
    sa.Column("key_ref", sa.String(120)),  # the provider_keys name of its credential
    # azure-openai only: `v1` or a dated version, the resource's region, and the region it last answered from.
    sa.Column("api_version", sa.String(32)),
    sa.Column("region", sa.String(64)),
    sa.Column("observed_region", sa.String(64)),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Index("ix_provider_connections_type", "type"),
    info=system("an install's model connection: no tenant and no value; the provider key it names is held by tenant"),
)

# An account's model provider keys: account admins set them, only this service reads them, and no
# team sees one, so a new team needs no setup. A value is never returned once saved.
provider_keys = sa.Table(
    "provider_keys",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("name", sa.String(120), primary_key=True),
    # AES-256-GCM over the value, the tenant and name as associated data (ops_policy.cipher).
    sa.Column("ciphertext", sa.Text, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now(), info=LISTED),
    sa.Column("rotated_at", sa.DateTime(timezone=True), info=LISTED),
    sa.Index("ix_provider_keys_created_at", "tenant_id", "created_at"),
    sa.Index("ix_provider_keys_rotated_at", "tenant_id", "rotated_at"),
    # Held to its tenant by the database: read only by a transaction run as ROLE in that tenant.
    info=TENANT_SCOPED,
)

model_aliases = sa.Table(
    "model_aliases",
    metadata,
    sa.Column("name", sa.String(120), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("kind", sa.String(16), nullable=False),  # chat | embedding
    sa.Column("provider_id", sa.String(64), sa.ForeignKey("provider_connections.id"), nullable=False),
    sa.Column("model_id", sa.String(200), nullable=False),
    # The most sensitive data class this version may receive: public < internal < confidential < restricted.
    sa.Column("cleared_sensitivity", sa.String(16), nullable=False),
    sa.Column("input_per_million", MONEY, nullable=False),
    sa.Column("output_per_million", MONEY, nullable=False),
    sa.Column("status", sa.String(16), nullable=False),  # current | retired
    sa.Column("created_at", sa.String(32), nullable=False),
    # The reasoning effort this version's calls run at, sent when a request names none; null leaves the provider's.
    sa.Column("reasoning_effort", sa.String(16)),
    # Whether this version may receive page images: an image carries the whole page, so none is sent unless set.
    sa.Column("images", sa.Boolean, nullable=False, server_default=sa.false()),
    # One version of an alias serves: a second current row would leave which one serves to the query's order.
    sa.Index(
        "ux_model_aliases_current",
        "name",
        unique=True,
        postgresql_where=sa.text("status = 'current'"),
        mssql_where=sa.text("status = 'current'"),
    ),
    info=system("an install's alias versions: every tenant's calls are served by them, and none names a tenant"),
)

model_keys = sa.Table(
    "model_keys",
    metadata,
    sa.Column("id", sa.String(200), primary_key=True),  # the identity: agent:ag_fraud, user:<email>, purpose:eval
    sa.Column("kind", sa.String(16), nullable=False),  # workflow | agent | user | purpose
    sa.Column("budget", MONEY, nullable=False),
    sa.Column("spent", MONEY, nullable=False),
    sa.Column("rate_limit_per_minute", sa.Integer, nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
    sa.Column("status", sa.String(16), nullable=False),  # active | revoked
    sa.Column("secret_hash", sa.String(64), nullable=False, unique=True),
    sa.Column("previous_secret_hash", sa.String(64), unique=True),
    sa.Column("previous_valid_until", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now()),
    sa.Column("rotated_at", sa.DateTime(timezone=True)),
    # Set for a key one service uses for many tenants (files-service's extractions): each tenant then spends
    # from its own row in model_key_tenants, starting at this budget, so one tenant cannot use up the others' share.
    sa.Column("tenant_budget", MONEY),
    # What the key may spend in one UTC day, from the call log (models_0011); null for no daily cap.
    sa.Column("daily_cap", MONEY),
    info=system("one identity's model key, spent for many tenants; each tenant's share is held by tenant"),
)

model_key_tenants = sa.Table(
    "model_key_tenants",
    metadata,
    sa.Column("key_id", sa.String(200), primary_key=True),
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("budget", MONEY, nullable=False),
    sa.Column("spent", MONEY, nullable=False),
    # Held to its tenant by the database: read and spent only as ROLE in that tenant.
    info=TENANT_SCOPED,
)


def _call_columns() -> list[sa.Column[Any]]:
    """One call's metadata, shared by the tenant's log and the calls that named no tenant."""
    return [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("key_id", sa.String(200), nullable=False, index=True),
        sa.Column("alias", sa.String(120), nullable=False),
        sa.Column("alias_version", sa.Integer),
        sa.Column("provider_model", sa.String(200)),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("cost", MONEY, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),  # ok | error | denied
        sa.Column("reason", sa.String(64)),
        sa.Column("sensitivity", sa.String(16)),
        sa.Column("run_id", sa.String(64)),
        sa.Column("step_id", sa.String(200)),
        sa.Column("thread_id", sa.String(64), index=True),
        sa.Column("request_hash", sa.String(64)),
    ]


model_call_log = sa.Table(
    "model_call_log",  # not model_calls: agents-service's replay ledger has that name in the same database
    metadata,
    *_call_columns(),
    sa.Column("tenant_id", sa.String(64)),
    # The call list sorts on it (`CallLog.page`).
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now(), index=True, info=LISTED
    ),
    # How many images the request carried, refused or sent.
    sa.Column("images", sa.Integer, nullable=False, server_default="0"),
    sa.Index("ix_model_call_log_key_run", "key_id", "run_id"),
    # Every read names the tenant (the policy adds it) and the page sorts newest first.
    sa.Index("ix_model_call_log_tenant_created", "tenant_id", "created_at"),
    # The call list is searched and filtered on its alias and outcome (`CallLog.page`).
    sa.Index("ix_model_call_log_alias", "alias"),
    sa.Index("ix_model_call_log_outcome", "outcome"),
    # Held to its tenant by the database: written and read only as ROLE in that tenant (models_0012). A key's caps
    # are read from model_key_spend, never from here.
    info=TENANT_SCOPED,
)

# A call that named no tenant (no X-Tenant-Id): refused before a tenant is known, or served by a key that spends for
# no tenant. It has no tenant to be held to, so it never lands in the tenant's log. Kept for operators, who read it in
# the database: no route lists it, since every service token names a tenant and none may read past it.
model_calls_untenanted = sa.Table(
    "model_calls_untenanted",
    metadata,
    *_call_columns(),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now(), index=True),
    sa.Column("images", sa.Integer, nullable=False, server_default="0"),
    info=system("a model call that named no tenant: no tenant column and no tenant to hold it to"),
)

# How long a key's day or run spend is kept after its last call: the sweep (`store.calls.SPEND_SWEEP`) deletes it
# then, and models_0012 backfills only what is newer.
SPEND_KEPT_IDLE_S = 14 * 86400.0

# What a key's caps read, summed across every tenant it spends for: per `period`, `sec:<epoch second>` (the rate
# limit, kept two minutes), `day:<UTC date>` (the daily cap) and `run:<run id>` (a caller's run cap). Written in one
# transaction with the call's row, whichever table that is in (`CallLog.record`).
model_key_spend = sa.Table(
    "model_key_spend",
    metadata,
    sa.Column("key_id", sa.String(200), primary_key=True),
    sa.Column("period", sa.String(80), primary_key=True),
    sa.Column("amount", MONEY, nullable=False),
    sa.Column("calls", sa.Integer, nullable=False),
    # When the period's first call was counted, on the service's clock: the rate window and the sweep of old seconds
    # read it.
    sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
    # Unix seconds of the period's latest call, on the service's clock: the sweep deletes a row idle for
    # SPEND_KEPT_IDLE_S, so a run that is still spending keeps its total however long ago it started.
    sa.Column("last_call_s", sa.Float(asdecimal=False), nullable=False),
    info=system("a model key's spend and call count per period, summed across the tenants it spends for"),
)
