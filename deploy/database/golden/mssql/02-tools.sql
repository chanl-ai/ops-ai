-- Ops AI schema for SQL Server, compiled from the store models by deploy/database/mssql.py; do not edit.
-- For review; apply bundle.sql, not these.
-- tools-service, stamped at tools_0074_stored_waits_answers
CREATE TABLE gateway_calls (
	id VARCHAR(64) NOT NULL, 
	tool VARCHAR(64) NOT NULL, 
	access VARCHAR(32) NOT NULL, 
	input_hash VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(200) NOT NULL, 
	thread_id VARCHAR(64) NULL, 
	step VARCHAR(200) NULL, 
	sub VARCHAR(200) NOT NULL, 
	act VARCHAR(200) NULL, 
	decision VARCHAR(8) NOT NULL, 
	reasons NVARCHAR(max) NOT NULL, 
	approvers NVARCHAR(max) NOT NULL, 
	outcome VARCHAR(16) NOT NULL, 
	effect BIT NOT NULL, 
	effect_scope VARCHAR(80) NOT NULL, 
	output NVARCHAR(max) NULL, 
	[view] NVARCHAR(max) NULL, 
	created_at VARCHAR(32) NOT NULL, 
	module_id VARCHAR(64) NULL, 
	latency_ms INTEGER NULL, 
	error NVARCHAR(max) NULL, 
	approval_token_id VARCHAR(64) NULL, 
	replay_of VARCHAR(64) NULL, 
	tenant_id VARCHAR(64) NULL, 
	team_id VARCHAR(64) NULL, 
	environment VARCHAR(16) NULL, 
	connection_id VARCHAR(64) NULL, 
	acting_for VARCHAR(320) NULL, 
	credential VARCHAR(16) NULL, 
	channel VARCHAR(16) NULL, 
	client_name VARCHAR(120) NULL, 
	CONSTRAINT gateway_calls_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_gateway_calls_module_created ON gateway_calls (module_id, created_at);
GO
CREATE INDEX ix_gateway_calls_tenant_id ON gateway_calls (tenant_id);
GO
CREATE INDEX ix_gateway_calls_thread_id ON gateway_calls (thread_id);
GO
CREATE UNIQUE INDEX ux_gateway_calls_effect_scope ON gateway_calls (tenant_id, effect_scope, step, tool, input_hash) WHERE tenant_id IS NOT NULL AND step IS NOT NULL;
GO
CREATE TABLE gateway_fences (
	thread_id VARCHAR(64) NOT NULL, 
	generation BIGINT NOT NULL, 
	CONSTRAINT gateway_fences_pkey PRIMARY KEY (thread_id)
);
GO
CREATE TABLE tool_modules (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NULL, 
	name VARCHAR(120) NOT NULL, 
	display_name VARCHAR(200) NOT NULL, 
	system VARCHAR(200) NOT NULL, 
	description VARCHAR(max) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	owner_team VARCHAR(120) NOT NULL, 
	owner_contacts NVARCHAR(max) NOT NULL, 
	auth NVARCHAR(max) NOT NULL, 
	timeout_ms INTEGER NOT NULL, 
	data_classification VARCHAR(16) NOT NULL, 
	catalog_id VARCHAR(64) NULL, 
	connection_id VARCHAR(64) NULL, 
	sign_in VARCHAR(16) NOT NULL DEFAULT 'person_or_team', 
	template_id VARCHAR(120) NULL, 
	protection VARCHAR(16) NULL, 
	reachable BIT NOT NULL, 
	drift BIT NOT NULL, 
	version VARCHAR(32) NOT NULL, 
	pending NVARCHAR(max) NOT NULL, 
	baseline NVARCHAR(max) NULL, 
	revision INTEGER NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	updated_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT tool_modules_pkey PRIMARY KEY (tenant_id, id)
);
GO
CREATE INDEX ix_tool_modules_template_id ON tool_modules (template_id);
GO
CREATE UNIQUE INDEX ux_tool_modules_name ON tool_modules (tenant_id, team_id, name) WHERE team_id IS NOT NULL AND team_id IS NOT NULL;
GO
CREATE UNIQUE INDEX ux_tool_modules_shared_name ON tool_modules (tenant_id, name) WHERE team_id IS NULL;
GO
CREATE TABLE operation_mocks (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	module_id VARCHAR(64) NOT NULL, 
	operation VARCHAR(120) NOT NULL, 
	environment VARCHAR(16) NOT NULL, 
	position INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	match NVARCHAR(max) NOT NULL, 
	status INTEGER NOT NULL, 
	body NVARCHAR(max) NULL, 
	headers NVARCHAR(max) NOT NULL, 
	delay_ms INTEGER NOT NULL, 
	timeout BIT NOT NULL, 
	is_default BIT NOT NULL, 
	from_call_id VARCHAR(64) NULL, 
	created_by VARCHAR(200) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	updated_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT operation_mocks_pkey PRIMARY KEY (tenant_id, id)
);
GO
CREATE INDEX ix_operation_mocks_operation ON operation_mocks (tenant_id, operation, environment, position);
GO
CREATE TABLE service_outbox (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	event_key VARCHAR(200) NOT NULL, 
	actor VARCHAR(320) NULL, 
	payload NVARCHAR(max) NOT NULL, 
	created_at FLOAT NOT NULL, 
	next_at FLOAT NULL, 
	sent_at FLOAT NULL, 
	attempts INTEGER NOT NULL, 
	last_error VARCHAR(max) NULL, 
	CONSTRAINT service_outbox_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_service_outbox_due ON service_outbox (sent_at, next_at);
GO
CREATE TABLE connections (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	auth_kind VARCHAR(40) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	status_detail VARCHAR(max) NULL, 
	expires_at DATETIMEOFFSET NULL, 
	catalog_id VARCHAR(64) NULL, 
	sign_in VARCHAR(16) NOT NULL DEFAULT 'team', 
	team_backup BIT NOT NULL DEFAULT 0, 
	health NVARCHAR(max) NULL, 
	category VARCHAR(80) NULL, 
	description VARCHAR(300) NULL, 
	docs_url VARCHAR(500) NULL, 
	app_id VARCHAR(120) NOT NULL, 
	sandbox BIT NOT NULL DEFAULT 0, 
	account_name VARCHAR(200) NULL, 
	account_key VARCHAR(200) NULL, 
	settings NVARCHAR(max) NOT NULL, 
	secrets NVARCHAR(max) NOT NULL, 
	platform_app VARCHAR(120) NULL, 
	credential_id VARCHAR(64) NULL, 
	plugin_settings NVARCHAR(max) NULL, 
	origin VARCHAR(16) NULL, 
	revision INTEGER NOT NULL, 
	created_by VARCHAR(200) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	updated_by VARCHAR(200) NOT NULL, 
	updated_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT connections_pkey PRIMARY KEY (tenant_id, id)
);
GO
CREATE INDEX ix_connections_app ON connections (tenant_id, team_id, app_id);
GO
CREATE INDEX ix_connections_team ON connections (tenant_id, team_id);
GO
CREATE UNIQUE INDEX uq_connections_account_key ON connections (tenant_id, team_id, app_id, account_key) WHERE account_key IS NOT NULL AND account_key IS NOT NULL;
GO
CREATE TABLE app_credentials (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	app_id VARCHAR(120) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	client_id VARCHAR(500) NOT NULL, 
	scopes VARCHAR(2000) NULL, 
	secret_name VARCHAR(200) NULL, 
	settings NVARCHAR(max) NULL, 
	setting_modes NVARCHAR(max) NULL, 
	created_by VARCHAR(200) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	updated_by VARCHAR(200) NOT NULL, 
	updated_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT app_credentials_pkey PRIMARY KEY (tenant_id, id)
);
GO
CREATE TABLE oauth_states (
	tenant_id VARCHAR(64) NOT NULL, 
	state_hash VARCHAR(64) NOT NULL, 
	connection_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	person_id VARCHAR(200) NOT NULL, 
	verifier_ct VARCHAR(max) NOT NULL, 
	redirect_uri VARCHAR(max) NOT NULL, 
	expires_at DATETIMEOFFSET NOT NULL, 
	used_at DATETIMEOFFSET NULL, 
	token_for VARCHAR(200) NOT NULL DEFAULT '', 
	scopes VARCHAR(max) NOT NULL DEFAULT '', 
	CONSTRAINT oauth_states_pkey PRIMARY KEY (tenant_id, state_hash)
);
GO
CREATE TABLE connection_audit (
	id INTEGER NOT NULL IDENTITY, 
	tenant_id VARCHAR(64) NOT NULL, 
	connection_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	action VARCHAR(32) NOT NULL, 
	environment VARCHAR(16) NULL, 
	actor VARCHAR(200) NOT NULL, 
	at DATETIMEOFFSET NOT NULL, 
	detail NVARCHAR(max) NOT NULL, 
	CONSTRAINT connection_audit_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_connection_audit_connection ON connection_audit (tenant_id, connection_id);
GO
CREATE TABLE egress_hosts (
	tenant_id VARCHAR(64) NOT NULL, 
	host VARCHAR(253) NOT NULL, 
	note VARCHAR(max) NOT NULL, 
	added_by VARCHAR(200) NOT NULL, 
	added_at DATETIMEOFFSET NOT NULL, 
	template_id VARCHAR(120) NULL, 
	protection VARCHAR(16) NULL, 
	CONSTRAINT egress_hosts_pkey PRIMARY KEY (tenant_id, host)
);
GO
CREATE INDEX ix_egress_hosts_template_id ON egress_hosts (template_id);
GO
CREATE TABLE egress_ranges (
	tenant_id VARCHAR(64) NOT NULL, 
	cidr VARCHAR(64) NOT NULL, 
	note VARCHAR(max) NOT NULL, 
	added_by VARCHAR(200) NOT NULL, 
	added_at DATETIMEOFFSET NOT NULL, 
	template_id VARCHAR(120) NULL, 
	protection VARCHAR(16) NULL, 
	CONSTRAINT egress_ranges_pkey PRIMARY KEY (tenant_id, cidr)
);
GO
CREATE INDEX ix_egress_ranges_template_id ON egress_ranges (template_id);
GO
CREATE TABLE egress_audit (
	id INTEGER NOT NULL IDENTITY, 
	tenant_id VARCHAR(64) NOT NULL, 
	kind VARCHAR(8) NOT NULL, 
	value VARCHAR(253) NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	actor VARCHAR(200) NOT NULL, 
	at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT egress_audit_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_egress_audit_tenant_id ON egress_audit (tenant_id);
GO
CREATE TABLE operation_rate_windows (
	tenant_id VARCHAR(64) NOT NULL, 
	operation VARCHAR(200) NOT NULL, 
	window_start DATETIMEOFFSET NOT NULL, 
	calls INTEGER NOT NULL, 
	CONSTRAINT operation_rate_windows_pkey PRIMARY KEY (tenant_id, operation, window_start)
);
GO
CREATE TABLE tool_secrets (
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	ciphertext VARCHAR(max) NOT NULL, 
	version INTEGER NOT NULL, 
	ends VARCHAR(4) NULL, 
	created_by VARCHAR(200) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	rotated_at DATETIMEOFFSET NULL, 
	last_used_at DATETIMEOFFSET NULL, 
	template_id VARCHAR(120) NULL, 
	protection VARCHAR(16) NULL, 
	connection_id VARCHAR(64) NULL, 
	credential_id VARCHAR(64) NULL, 
	CONSTRAINT tool_secrets_pkey PRIMARY KEY (tenant_id, team_id, name)
);
GO
CREATE INDEX ix_tool_secrets_template_id ON tool_secrets (template_id);
GO
CREATE TABLE secret_audit (
	id INTEGER NOT NULL IDENTITY, 
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	version INTEGER NOT NULL, 
	actor VARCHAR(200) NOT NULL, 
	tool VARCHAR(120) NULL, 
	at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT secret_audit_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_secret_audit_tenant_id ON secret_audit (tenant_id);
GO
CREATE TABLE plugin_bindings (
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	plugin_id VARCHAR(120) NOT NULL, 
	enabled BIT NOT NULL, 
	connection_id VARCHAR(64) NULL, 
	settings NVARCHAR(max) NOT NULL, 
	updated_by VARCHAR(320) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	version VARCHAR(40) NULL, 
	digest VARCHAR(64) NULL, 
	declarations NVARCHAR(max) NULL, 
	tools_on NVARCHAR(max) NULL, 
	config_settings NVARCHAR(max) NULL, 
	setting_modes NVARCHAR(max) NULL, 
	CONSTRAINT plugin_bindings_pkey PRIMARY KEY (tenant_id, team_id, plugin_id)
);
GO
CREATE TABLE send_policies (
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	text VARCHAR(max) NOT NULL, 
	saved_by VARCHAR(320) NOT NULL, 
	saved_at VARCHAR(32) NOT NULL, 
	CONSTRAINT send_policies_pkey PRIMARY KEY (tenant_id, team_id, version)
);
GO
CREATE TABLE send_checks (
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	input_hash VARCHAR(80) NOT NULL, 
	policy_version INTEGER NOT NULL, 
	ok BIT NOT NULL, 
	reason VARCHAR(max) NOT NULL, 
	checked_at VARCHAR(32) NOT NULL, 
	CONSTRAINT send_checks_pkey PRIMARY KEY (tenant_id, team_id, input_hash, policy_version)
);
GO
CREATE TABLE team_defaults (
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	applied_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT team_defaults_pkey PRIMARY KEY (tenant_id, team_id)
);
GO
CREATE TABLE module_operations (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	module_id VARCHAR(64) NOT NULL, 
	position INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	tool_id VARCHAR(64) NOT NULL, 
	description VARCHAR(max) NOT NULL, 
	access VARCHAR(16) NOT NULL, 
	enabled BIT NOT NULL, 
	executor VARCHAR(8) NOT NULL DEFAULT 'http', 
	method VARCHAR(8) NULL, 
	path VARCHAR(max) NULL, 
	headers NVARCHAR(max) NOT NULL DEFAULT '[]', 
	body VARCHAR(max) NULL, 
	body_encoding VARCHAR(8) NULL, 
	response_transform VARCHAR(max) NULL, 
	timeout_ms INTEGER NULL, 
	input NVARCHAR(max) NOT NULL, 
	masked_output NVARCHAR(max) NOT NULL, 
	binding NVARCHAR(max) NULL, 
	rate_limit_per_min INTEGER NOT NULL, 
	requires_approval BIT NULL, 
	approval_mode VARCHAR(8) NULL, 
	reviewer_role VARCHAR(64) NULL, 
	amount_max NUMERIC(14, 2) NULL, 
	approvers INTEGER NOT NULL DEFAULT '1', 
	approver_team VARCHAR(64) NULL, 
	step_up BIT NOT NULL DEFAULT 0, 
	needs_person BIT NOT NULL DEFAULT 0, 
	scopes NVARCHAR(max) NOT NULL DEFAULT '[]', 
	output_shape VARCHAR(16) NULL, 
	response_schema NVARCHAR(max) NULL, 
	code NVARCHAR(max) NULL, 
	CONSTRAINT module_operations_pkey PRIMARY KEY (tenant_id, id), 
	CONSTRAINT ck_module_operations_access CHECK (access IN ('read', 'write')), 
	CONSTRAINT ux_module_operations_name UNIQUE (tenant_id, module_id, name), 
	CONSTRAINT module_operations_tenant_id_module_id_fkey FOREIGN KEY(tenant_id, module_id) REFERENCES tool_modules (tenant_id, id) ON DELETE CASCADE
);
GO
CREATE INDEX ix_module_operations_module ON module_operations (tenant_id, module_id);
GO
CREATE TABLE module_versions (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	module_id VARCHAR(64) NOT NULL, 
	position INTEGER NOT NULL, 
	version VARCHAR(32) NOT NULL, 
	major INTEGER NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	published_at DATETIMEOFFSET NULL, 
	published_by VARCHAR(200) NOT NULL, 
	note VARCHAR(max) NOT NULL, 
	changes NVARCHAR(max) NOT NULL, 
	pinned_by NVARCHAR(max) NOT NULL, 
	reachability NVARCHAR(max) NOT NULL, 
	review_id VARCHAR(64) NULL, 
	requested_at DATETIMEOFFSET NULL, 
	reviewer VARCHAR(200) NULL, 
	finding VARCHAR(max) NULL, 
	review_required BIT NULL, 
	policy VARCHAR(16) NULL, 
	CONSTRAINT module_versions_pkey PRIMARY KEY (tenant_id, id), 
	CONSTRAINT ux_module_versions_version UNIQUE (tenant_id, module_id, version), 
	CONSTRAINT module_versions_tenant_id_module_id_fkey FOREIGN KEY(tenant_id, module_id) REFERENCES tool_modules (tenant_id, id) ON DELETE CASCADE
);
GO
CREATE INDEX ix_module_versions_module ON module_versions (tenant_id, module_id);
GO
CREATE TABLE module_approvals (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	module_id VARCHAR(64) NOT NULL, 
	position INTEGER NOT NULL, 
	workflow_id VARCHAR(64) NOT NULL, 
	workflow_name VARCHAR(200) NOT NULL, 
	workflow_team_id VARCHAR(64) NULL, 
	environment VARCHAR(16) NOT NULL, 
	major INTEGER NOT NULL, 
	operations NVARCHAR(max) NOT NULL, 
	constraints VARCHAR(max) NULL, 
	requested_by VARCHAR(200) NOT NULL, 
	requested_by_email VARCHAR(320) NULL, 
	justification VARCHAR(max) NOT NULL, 
	requested_at DATETIMEOFFSET NOT NULL, 
	decided_by VARCHAR(200) NULL, 
	decided_at DATETIMEOFFSET NULL, 
	status VARCHAR(16) NOT NULL, 
	expires_at DATETIMEOFFSET NULL, 
	reason VARCHAR(max) NULL, 
	decider_team VARCHAR(64) NULL, 
	review_id VARCHAR(64) NULL, 
	CONSTRAINT module_approvals_pkey PRIMARY KEY (tenant_id, id), 
	CONSTRAINT module_approvals_tenant_id_module_id_fkey FOREIGN KEY(tenant_id, module_id) REFERENCES tool_modules (tenant_id, id) ON DELETE CASCADE
);
GO
CREATE INDEX ix_module_approvals_module ON module_approvals (tenant_id, module_id);
GO
CREATE TABLE module_egress_hosts (
	tenant_id VARCHAR(64) NOT NULL, 
	module_id VARCHAR(64) NOT NULL, 
	host VARCHAR(253) NOT NULL, 
	position INTEGER NOT NULL, 
	CONSTRAINT module_egress_hosts_pkey PRIMARY KEY (tenant_id, module_id, host), 
	CONSTRAINT module_egress_hosts_tenant_id_module_id_fkey FOREIGN KEY(tenant_id, module_id) REFERENCES tool_modules (tenant_id, id) ON DELETE CASCADE, 
	CONSTRAINT module_egress_hosts_tenant_id_host_fkey FOREIGN KEY(tenant_id, host) REFERENCES egress_hosts (tenant_id, host) ON DELETE NO ACTION
);
GO
CREATE TABLE connection_tokens (
	tenant_id VARCHAR(64) NOT NULL, 
	connection_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	person_id VARCHAR(200) NOT NULL, 
	access_ct VARCHAR(max) NOT NULL, 
	refresh_ct VARCHAR(max) NULL, 
	expires_at DATETIMEOFFSET NULL, 
	scopes NVARCHAR(max) NOT NULL, 
	account VARCHAR(320) NULL, 
	rotations INTEGER NOT NULL, 
	refreshed_at DATETIMEOFFSET NOT NULL, 
	refused_at DATETIMEOFFSET NULL, 
	refused_reason VARCHAR(300) NULL, 
	pinned BIT NOT NULL DEFAULT 0, 
	test NVARCHAR(max) NULL, 
	person_name VARCHAR(200) NULL, 
	CONSTRAINT connection_tokens_pkey PRIMARY KEY (tenant_id, connection_id, person_id), 
	CONSTRAINT connection_tokens_tenant_id_connection_id_fkey FOREIGN KEY(tenant_id, connection_id) REFERENCES connections (tenant_id, id) ON DELETE CASCADE
);
GO
CREATE TABLE connect_links (
	tenant_id VARCHAR(64) NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	connection_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	person_id VARCHAR(200) NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	scopes VARCHAR(max) NOT NULL, 
	reason VARCHAR(32) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	expires_at DATETIMEOFFSET NOT NULL, 
	used_at DATETIMEOFFSET NULL, 
	CONSTRAINT connect_links_pkey PRIMARY KEY (tenant_id, token_hash), 
	CONSTRAINT connect_links_tenant_id_connection_id_fkey FOREIGN KEY(tenant_id, connection_id) REFERENCES connections (tenant_id, id) ON DELETE CASCADE
);
GO
IF SCHEMA_ID(N'ops_security') IS NULL EXEC (N'CREATE SCHEMA ops_security AUTHORIZATION dbo');
GO
CREATE FUNCTION ops_security.tools_team_read (@tenant_id VARCHAR(64), @team_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS visible WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64)) AND (CAST(SESSION_CONTEXT(N'scope') AS NVARCHAR(16)) = N'tenant' OR @team_id = CAST(SESSION_CONTEXT(N'team_id') AS VARCHAR(64)));
GO
CREATE FUNCTION ops_security.tools_team_write (@tenant_id VARCHAR(64), @team_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS allowed WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64)) AND (CAST(SESSION_CONTEXT(N'scope') AS NVARCHAR(16)) = N'tenant' OR @team_id = CAST(SESSION_CONTEXT(N'team_id') AS VARCHAR(64)));
GO
CREATE SECURITY POLICY ops_security.connections_isolation
    ADD FILTER PREDICATE ops_security.tools_team_read(tenant_id, team_id) ON dbo.connections,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.connections AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.connections AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.app_credentials_isolation
    ADD FILTER PREDICATE ops_security.tools_team_read(tenant_id, team_id) ON dbo.app_credentials,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.app_credentials AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.app_credentials AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.oauth_states_isolation
    ADD FILTER PREDICATE ops_security.tools_team_read(tenant_id, team_id) ON dbo.oauth_states,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.oauth_states AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.oauth_states AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.connection_audit_isolation
    ADD FILTER PREDICATE ops_security.tools_team_read(tenant_id, team_id) ON dbo.connection_audit,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.connection_audit AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.connection_audit AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.tool_secrets_isolation
    ADD FILTER PREDICATE ops_security.tools_team_read(tenant_id, team_id) ON dbo.tool_secrets,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.tool_secrets AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.tool_secrets AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.secret_audit_isolation
    ADD FILTER PREDICATE ops_security.tools_team_read(tenant_id, team_id) ON dbo.secret_audit,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.secret_audit AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.secret_audit AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.connection_tokens_isolation
    ADD FILTER PREDICATE ops_security.tools_team_read(tenant_id, team_id) ON dbo.connection_tokens,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.connection_tokens AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.connection_tokens AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.connect_links_isolation
    ADD FILTER PREDICATE ops_security.tools_team_read(tenant_id, team_id) ON dbo.connect_links,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.connect_links AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.tools_team_write(tenant_id, team_id) ON dbo.connect_links AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE TABLE alembic_version_tools (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_tools_pkc PRIMARY KEY (version_num)
);
GO
INSERT INTO alembic_version_tools (version_num) VALUES ('tools_0074_stored_waits_answers');
GO
