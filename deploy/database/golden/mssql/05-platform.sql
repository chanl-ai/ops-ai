-- Ops AI schema for SQL Server, compiled from the store models by deploy/database/mssql.py; do not edit.
-- For review; apply bundle.sql, not these.
-- platform-service, stamped at 0025_connections_cells
CREATE TABLE tenants (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	allowed_domains NVARCHAR(max) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	permission_version INTEGER NOT NULL DEFAULT '1', 
	security_team_id VARCHAR(64) NULL, 
	default_team_id VARCHAR(64) NULL, 
	CONSTRAINT tenants_pkey PRIMARY KEY (id)
);
GO
CREATE TABLE signin_email_failures (
	email_hash VARCHAR(64) NOT NULL, 
	failures INTEGER NOT NULL, 
	first_failed_at VARCHAR(40) NOT NULL, 
	locked_until VARCHAR(40) NULL, 
	CONSTRAINT signin_email_failures_pkey PRIMARY KEY (email_hash)
);
GO
CREATE TABLE teams (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	owner_groups NVARCHAR(max) NOT NULL, 
	scope VARCHAR(16) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	status VARCHAR(16) NOT NULL DEFAULT 'active', 
	archived_at VARCHAR(40) NULL, 
	name_key VARCHAR(200) NOT NULL, 
	template_id VARCHAR(64) NULL, 
	protection VARCHAR(16) NOT NULL DEFAULT 'none', 
	CONSTRAINT teams_pkey PRIMARY KEY (id), 
	CONSTRAINT uq_teams_tenant_id UNIQUE (tenant_id, id), 
	CONSTRAINT uq_teams_tenant_name UNIQUE (tenant_id, name_key), 
	CONSTRAINT teams_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
GO
CREATE INDEX ix_teams_tenant_id ON teams (tenant_id);
GO
CREATE TABLE users (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	CONSTRAINT users_pkey PRIMARY KEY (id), 
	CONSTRAINT uq_users_tenant_email UNIQUE (tenant_id, email), 
	CONSTRAINT uq_users_tenant_id UNIQUE (tenant_id, id), 
	CONSTRAINT users_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
GO
CREATE INDEX ix_users_tenant_id ON users (tenant_id);
GO
CREATE TABLE roles (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	builtin BIT NOT NULL, 
	description VARCHAR(500) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	CONSTRAINT roles_pkey PRIMARY KEY (tenant_id, id), 
	CONSTRAINT roles_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
GO
CREATE TABLE policies (
	tenant_id VARCHAR(64) NOT NULL, 
	[key] VARCHAR(64) NOT NULL, 
	value NVARCHAR(max) NOT NULL, 
	updated_by VARCHAR(320) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	CONSTRAINT policies_pkey PRIMARY KEY (tenant_id, [key]), 
	CONSTRAINT policies_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
GO
CREATE TABLE members (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NULL, 
	email VARCHAR(320) NOT NULL, 
	role VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	invite_token_hash VARCHAR(64) NULL, 
	invite_expires_at VARCHAR(40) NULL, 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	CONSTRAINT members_pkey PRIMARY KEY (id), 
	CONSTRAINT uq_members_team_email UNIQUE (team_id, email), 
	CONSTRAINT fk_members_team FOREIGN KEY(tenant_id, team_id) REFERENCES teams (tenant_id, id), 
	CONSTRAINT fk_members_user FOREIGN KEY(tenant_id, user_id) REFERENCES users (tenant_id, id), 
	CONSTRAINT members_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
GO
CREATE INDEX ix_members_team_id ON members (team_id);
GO
CREATE INDEX ix_members_tenant_id ON members (tenant_id);
GO
CREATE UNIQUE INDEX members_invite_token_hash_key ON members (invite_token_hash) WHERE invite_token_hash IS NOT NULL;
GO
CREATE TABLE api_keys (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	prefix VARCHAR(64) NOT NULL, 
	secret_hash VARCHAR(64) NOT NULL, 
	scopes NVARCHAR(max) NOT NULL, 
	created_by VARCHAR(64) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	last_used_at VARCHAR(40) NULL, 
	revoked_at VARCHAR(40) NULL, 
	disabled_at VARCHAR(40) NULL, 
	expires_at VARCHAR(40) NULL, 
	target_kind VARCHAR(16) NULL, 
	target_id VARCHAR(64) NULL, 
	target_version INTEGER NULL, 
	CONSTRAINT api_keys_pkey PRIMARY KEY (id), 
	CONSTRAINT fk_api_keys_team FOREIGN KEY(tenant_id, team_id) REFERENCES teams (tenant_id, id), 
	CONSTRAINT fk_api_keys_creator FOREIGN KEY(tenant_id, created_by) REFERENCES users (tenant_id, id), 
	CONSTRAINT api_keys_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT api_keys_prefix_key UNIQUE (prefix)
);
GO
CREATE INDEX ix_api_keys_team_id ON api_keys (team_id);
GO
CREATE INDEX ix_api_keys_tenant_id ON api_keys (tenant_id);
GO
CREATE TABLE sessions (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	auth_method VARCHAR(16) NOT NULL, 
	provider_id VARCHAR(64) NULL, 
	refresh_hash VARCHAR(64) NOT NULL, 
	expires_at VARCHAR(40) NOT NULL, 
	revoked_at VARCHAR(40) NULL, 
	last_seen_at VARCHAR(40) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	CONSTRAINT sessions_pkey PRIMARY KEY (id), 
	CONSTRAINT fk_sessions_user FOREIGN KEY(tenant_id, user_id) REFERENCES users (tenant_id, id), 
	CONSTRAINT sessions_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT sessions_refresh_hash_key UNIQUE (refresh_hash)
);
GO
CREATE INDEX ix_sessions_tenant_id ON sessions (tenant_id);
GO
CREATE INDEX ix_sessions_user_id ON sessions (user_id);
GO
CREATE TABLE audit_entries (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NULL, 
	actor VARCHAR(320) NOT NULL, 
	action VARCHAR(80) NOT NULL, 
	target_kind VARCHAR(40) NOT NULL, 
	target_id VARCHAR(64) NOT NULL, 
	request_id VARCHAR(64) NOT NULL, 
	at VARCHAR(40) NOT NULL, 
	detail NVARCHAR(max) NOT NULL, 
	CONSTRAINT audit_entries_pkey PRIMARY KEY (id), 
	CONSTRAINT fk_audit_entries_team FOREIGN KEY(tenant_id, team_id) REFERENCES teams (tenant_id, id), 
	CONSTRAINT audit_entries_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
GO
CREATE INDEX ix_audit_entries_team_id ON audit_entries (team_id);
GO
CREATE INDEX ix_audit_entries_tenant_id ON audit_entries (tenant_id);
GO
CREATE TABLE role_permissions (
	tenant_id VARCHAR(64) NOT NULL, 
	role_id VARCHAR(64) NOT NULL, 
	area VARCHAR(32) NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	scope VARCHAR(8) NOT NULL, 
	CONSTRAINT role_permissions_pkey PRIMARY KEY (tenant_id, role_id, area, action), 
	CONSTRAINT fk_role_permissions_role FOREIGN KEY(tenant_id, role_id) REFERENCES roles (tenant_id, id)
);
GO
CREATE TABLE role_assignments (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	subject_kind VARCHAR(8) NOT NULL, 
	subject_id VARCHAR(64) NOT NULL, 
	role_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	expires_at VARCHAR(40) NULL, 
	granted_by VARCHAR(320) NOT NULL, 
	reason VARCHAR(500) NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	CONSTRAINT role_assignments_pkey PRIMARY KEY (id), 
	CONSTRAINT uq_role_assignments UNIQUE (tenant_id, subject_kind, subject_id, role_id, team_id), 
	CONSTRAINT fk_role_assignments_role FOREIGN KEY(tenant_id, role_id) REFERENCES roles (tenant_id, id), 
	CONSTRAINT role_assignments_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
GO
CREATE INDEX ix_role_assignments_subject ON role_assignments (tenant_id, subject_id);
GO
CREATE TABLE signin_providers (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	label VARCHAR(200) NOT NULL, 
	enabled BIT NOT NULL, 
	config NVARCHAR(max) NOT NULL, 
	jit_team_id VARCHAR(64) NULL, 
	jit_role VARCHAR(16) NULL, 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	CONSTRAINT signin_providers_pkey PRIMARY KEY (id, tenant_id), 
	CONSTRAINT fk_signin_jit_team FOREIGN KEY(tenant_id, jit_team_id) REFERENCES teams (tenant_id, id), 
	CONSTRAINT signin_providers_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
GO
CREATE TABLE password_credentials (
	user_id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	hash VARCHAR(255) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	CONSTRAINT password_credentials_pkey PRIMARY KEY (user_id), 
	CONSTRAINT fk_password_user FOREIGN KEY(tenant_id, user_id) REFERENCES users (tenant_id, id), 
	CONSTRAINT password_credentials_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
GO
CREATE INDEX ix_password_credentials_tenant_id ON password_credentials (tenant_id);
GO
CREATE TABLE password_resets (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	expires_at VARCHAR(40) NOT NULL, 
	used_at VARCHAR(40) NULL, 
	CONSTRAINT password_resets_pkey PRIMARY KEY (id), 
	CONSTRAINT fk_password_resets_user FOREIGN KEY(tenant_id, user_id) REFERENCES users (tenant_id, id), 
	CONSTRAINT password_resets_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT password_resets_token_hash_key UNIQUE (token_hash)
);
GO
CREATE INDEX ix_password_resets_tenant_id ON password_resets (tenant_id);
GO
CREATE TABLE signin_lockouts (
	tenant_id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	failures INTEGER NOT NULL, 
	first_failed_at VARCHAR(40) NOT NULL, 
	locked_until VARCHAR(40) NULL, 
	CONSTRAINT signin_lockouts_pkey PRIMARY KEY (tenant_id, user_id), 
	CONSTRAINT fk_signin_lockouts_user FOREIGN KEY(tenant_id, user_id) REFERENCES users (tenant_id, id), 
	CONSTRAINT signin_lockouts_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
GO
CREATE TABLE signin_domains (
	domain VARCHAR(253) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	provider_id VARCHAR(64) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	token VARCHAR(64) NOT NULL, 
	verified_at VARCHAR(40) NULL, 
	CONSTRAINT signin_domains_pkey PRIMARY KEY (domain, tenant_id), 
	CONSTRAINT fk_signin_domains_provider FOREIGN KEY(tenant_id, provider_id) REFERENCES signin_providers (tenant_id, id) ON DELETE CASCADE, 
	CONSTRAINT signin_domains_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
GO
CREATE INDEX ix_signin_domains_tenant_id ON signin_domains (tenant_id);
GO
CREATE UNIQUE INDEX ux_signin_domains_verified ON signin_domains (domain) WHERE verified_at IS NOT NULL;
GO
CREATE TABLE signin_identities (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	provider_id VARCHAR(64) NOT NULL, 
	subject VARCHAR(255) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	last_used_at VARCHAR(40) NOT NULL, 
	CONSTRAINT signin_identities_pkey PRIMARY KEY (id), 
	CONSTRAINT uq_signin_identities_subject UNIQUE (tenant_id, provider_id, subject), 
	CONSTRAINT fk_signin_identities_provider FOREIGN KEY(tenant_id, provider_id) REFERENCES signin_providers (tenant_id, id) ON DELETE CASCADE, 
	CONSTRAINT fk_signin_identities_user FOREIGN KEY(tenant_id, user_id) REFERENCES users (tenant_id, id), 
	CONSTRAINT signin_identities_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
GO
CREATE INDEX ix_signin_identities_tenant_id ON signin_identities (tenant_id);
GO
CREATE TABLE signin_flows (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	provider_id VARCHAR(64) NOT NULL, 
	purpose VARCHAR(16) NOT NULL, 
	state_hash VARCHAR(64) NOT NULL, 
	browser_hash VARCHAR(64) NOT NULL, 
	verifier VARCHAR(128) NULL, 
	nonce VARCHAR(128) NULL, 
	request_id VARCHAR(64) NULL, 
	next_path VARCHAR(500) NULL, 
	session_id VARCHAR(64) NULL, 
	user_id VARCHAR(64) NULL, 
	handoff_hash VARCHAR(64) NULL, 
	created_at VARCHAR(40) NOT NULL, 
	expires_at VARCHAR(40) NOT NULL, 
	answered_at VARCHAR(40) NULL, 
	used_at VARCHAR(40) NULL, 
	CONSTRAINT signin_flows_pkey PRIMARY KEY (id), 
	CONSTRAINT fk_signin_flows_provider FOREIGN KEY(tenant_id, provider_id) REFERENCES signin_providers (tenant_id, id) ON DELETE CASCADE, 
	CONSTRAINT signin_flows_tenant_id_fkey FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT signin_flows_state_hash_key UNIQUE (state_hash)
);
GO
CREATE INDEX ix_signin_flows_tenant_id ON signin_flows (tenant_id);
GO
CREATE UNIQUE INDEX signin_flows_handoff_hash_key ON signin_flows (handoff_hash) WHERE handoff_hash IS NOT NULL;
GO
IF SCHEMA_ID(N'ops_security') IS NULL EXEC (N'CREATE SCHEMA ops_security AUTHORIZATION dbo');
GO
CREATE FUNCTION ops_security.platform_tenant_read (@tenant_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS visible WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64));
GO
CREATE FUNCTION ops_security.platform_tenant_write (@tenant_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS allowed WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64));
GO
CREATE SECURITY POLICY ops_security.tenants_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(id) ON dbo.tenants,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(id) ON dbo.tenants AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(id) ON dbo.tenants AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.teams_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.teams,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.teams AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.teams AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.users_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.users,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.users AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.users AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.roles_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.roles,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.roles AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.roles AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.policies_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.policies,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.policies AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.policies AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.members_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.members,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.members AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.members AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.api_keys_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.api_keys,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.api_keys AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.api_keys AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.sessions_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.sessions,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.sessions AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.sessions AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.audit_entries_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.audit_entries,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.audit_entries AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.audit_entries AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.role_permissions_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.role_permissions,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.role_permissions AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.role_permissions AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.role_assignments_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.role_assignments,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.role_assignments AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.role_assignments AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.signin_providers_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.signin_providers,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.signin_providers AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.signin_providers AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.password_credentials_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.password_credentials,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.password_credentials AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.password_credentials AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.password_resets_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.password_resets,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.password_resets AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.password_resets AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.signin_lockouts_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.signin_lockouts,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.signin_lockouts AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.signin_lockouts AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.signin_domains_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.signin_domains,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.signin_domains AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.signin_domains AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.signin_identities_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.signin_identities,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.signin_identities AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.signin_identities AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.signin_flows_tenant
    ADD FILTER PREDICATE ops_security.platform_tenant_read(tenant_id) ON dbo.signin_flows,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.signin_flows AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.platform_tenant_write(tenant_id) ON dbo.signin_flows AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE TABLE alembic_version_platform (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_platform_pkc PRIMARY KEY (version_num)
);
GO
INSERT INTO alembic_version_platform (version_num) VALUES ('0025_connections_cells');
GO
