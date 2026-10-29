-- Ops AI schema for SQL Server, compiled from the store models by deploy/database/mssql.py; do not edit.
-- For review; apply bundle.sql, not these.
-- models-service, stamped at models_0007
CREATE TABLE provider_connections (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	type VARCHAR(32) NOT NULL, 
	base_url VARCHAR(400) NULL, 
	key_ref VARCHAR(120) NULL, 
	created_at VARCHAR(32) NOT NULL, 
	CONSTRAINT provider_connections_pkey PRIMARY KEY (id), 
	CONSTRAINT provider_connections_name_key UNIQUE (name)
);
GO
CREATE TABLE provider_keys (
	tenant_id VARCHAR(64) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	ciphertext VARCHAR(max) NOT NULL, 
	version INTEGER NOT NULL, 
	created_by VARCHAR(320) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL DEFAULT SYSDATETIMEOFFSET(), 
	rotated_at DATETIMEOFFSET NULL, 
	CONSTRAINT provider_keys_pkey PRIMARY KEY (tenant_id, name)
);
GO
CREATE TABLE model_keys (
	id VARCHAR(200) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	budget NUMERIC(18, 6) NOT NULL, 
	spent NUMERIC(18, 6) NOT NULL, 
	rate_limit_per_minute INTEGER NOT NULL, 
	expires_at DATETIMEOFFSET NULL, 
	status VARCHAR(16) NOT NULL, 
	secret_hash VARCHAR(64) NOT NULL, 
	previous_secret_hash VARCHAR(64) NULL, 
	previous_valid_until DATETIMEOFFSET NULL, 
	created_at DATETIMEOFFSET NOT NULL DEFAULT SYSDATETIMEOFFSET(), 
	rotated_at DATETIMEOFFSET NULL, 
	tenant_budget NUMERIC(18, 6) NULL, 
	CONSTRAINT model_keys_pkey PRIMARY KEY (id), 
	CONSTRAINT model_keys_secret_hash_key UNIQUE (secret_hash)
);
GO
CREATE UNIQUE INDEX model_keys_previous_secret_hash_key ON model_keys (previous_secret_hash) WHERE previous_secret_hash IS NOT NULL;
GO
CREATE TABLE model_key_tenants (
	key_id VARCHAR(200) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	budget NUMERIC(18, 6) NOT NULL, 
	spent NUMERIC(18, 6) NOT NULL, 
	CONSTRAINT model_key_tenants_pkey PRIMARY KEY (key_id, tenant_id)
);
GO
CREATE TABLE model_call_log (
	id VARCHAR(64) NOT NULL, 
	key_id VARCHAR(200) NOT NULL, 
	alias VARCHAR(120) NOT NULL, 
	alias_version INTEGER NULL, 
	provider_model VARCHAR(200) NULL, 
	input_tokens INTEGER NOT NULL, 
	output_tokens INTEGER NOT NULL, 
	cost NUMERIC(18, 6) NOT NULL, 
	latency_ms INTEGER NOT NULL, 
	outcome VARCHAR(16) NOT NULL, 
	reason VARCHAR(64) NULL, 
	sensitivity VARCHAR(16) NULL, 
	run_id VARCHAR(64) NULL, 
	step_id VARCHAR(200) NULL, 
	thread_id VARCHAR(64) NULL, 
	request_hash VARCHAR(64) NULL, 
	tenant_id VARCHAR(64) NULL, 
	created_at DATETIMEOFFSET NOT NULL DEFAULT SYSDATETIMEOFFSET(), 
	images INTEGER NOT NULL DEFAULT '0', 
	CONSTRAINT model_call_log_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_model_call_log_created_at ON model_call_log (created_at);
GO
CREATE INDEX ix_model_call_log_key_id ON model_call_log (key_id);
GO
CREATE INDEX ix_model_call_log_thread_id ON model_call_log (thread_id);
GO
CREATE TABLE model_aliases (
	name VARCHAR(120) NOT NULL, 
	version INTEGER NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	provider_id VARCHAR(64) NOT NULL, 
	model_id VARCHAR(200) NOT NULL, 
	cleared_sensitivity VARCHAR(16) NOT NULL, 
	input_per_million NUMERIC(18, 6) NOT NULL, 
	output_per_million NUMERIC(18, 6) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	reasoning_effort VARCHAR(16) NULL, 
	images BIT NOT NULL DEFAULT 0, 
	CONSTRAINT model_aliases_pkey PRIMARY KEY (name, version), 
	CONSTRAINT model_aliases_provider_id_fkey FOREIGN KEY(provider_id) REFERENCES provider_connections (id)
);
GO
CREATE UNIQUE INDEX ux_model_aliases_current ON model_aliases (name) WHERE status = 'current';
GO
CREATE TABLE alembic_version_models (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_models_pkc PRIMARY KEY (version_num)
);
GO
INSERT INTO alembic_version_models (version_num) VALUES ('models_0007');
GO
