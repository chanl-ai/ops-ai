"""models-service's tables, in its own migration chain (`alembic_version_models`).

A provider connection names its credential (`key_ref`) and never holds it. An alias has immutable versions; the
newest version that is not retired serves calls. A model key belongs to one identity (a workflow, an agent, a person
or a platform purpose) and carries its budget, its spend and a hash of its secret, plus the previous hash during a
rotation's overlap. A model call row is metadata only: never a prompt or a completion.
"""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

MONEY = sa.Numeric(18, 6)

provider_connections = sa.Table(
    "provider_connections",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("name", sa.String(120), nullable=False, unique=True),
    sa.Column("type", sa.String(32), nullable=False),  # openai-compatible | anthropic | scripted
    sa.Column("base_url", sa.String(400)),
    sa.Column("key_ref", sa.String(120)),  # the name Settings.model_provider_keys knows the credential by
    sa.Column("created_at", sa.String(32), nullable=False),
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
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("rotated_at", sa.DateTime(timezone=True)),
)

model_call_log = sa.Table(
    "model_call_log",  # not model_calls: agents-service's replay ledger has that name in the same database
    metadata,
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
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True),
)

SENSITIVITY = ("public", "internal", "confidential", "restricted")


def cleared(alias_ceiling: str, data: str) -> bool:
    """Whether an alias cleared up to `alias_ceiling` may receive data of class `data`; an unknown class never is."""
    if alias_ceiling not in SENSITIVITY or data not in SENSITIVITY:
        return False
    return SENSITIVITY.index(data) <= SENSITIVITY.index(alias_ceiling)
