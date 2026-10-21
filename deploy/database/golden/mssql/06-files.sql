-- Ops AI schema for SQL Server, compiled from the store models by deploy/database/mssql.py; do not edit.
-- For review; apply bundle.sql, not these.
-- files-service, stamped at files_0012
CREATE TABLE files (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	team VARCHAR(64) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	mime VARCHAR(127) NOT NULL, 
	sniffed_mime VARCHAR(127) NULL, 
	size BIGINT NOT NULL, 
	digest VARCHAR(64) NULL, 
	purpose VARCHAR(32) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	scan_status VARCHAR(16) NOT NULL, 
	scan_engine VARCHAR(64) NULL, 
	scan_at DATETIMEOFFSET NULL, 
	scan_detail VARCHAR(500) NULL, 
	sensitivity VARCHAR(16) NOT NULL, 
	sensitivity_suggested BIT NOT NULL, 
	retention_class_id VARCHAR(64) NOT NULL, 
	delete_after DATE NULL, 
	immutable BIT NOT NULL, 
	storage_backend VARCHAR(16) NOT NULL, 
	storage_container VARCHAR(255) NOT NULL, 
	storage_key VARCHAR(512) NOT NULL, 
	multipart_upload_id VARCHAR(255) NULL, 
	declared_size BIGINT NOT NULL, 
	declared_digest VARCHAR(64) NULL, 
	upload_expires_at DATETIMEOFFSET NULL, 
	uploaded_by VARCHAR(320) NOT NULL, 
	uploaded_at DATETIMEOFFSET NOT NULL, 
	version_count INTEGER NOT NULL, 
	data NVARCHAR(max) NULL, 
	read_as VARCHAR(64) NULL, 
	read_path VARCHAR(16) NULL, 
	CONSTRAINT files_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_files_delete_after ON files (tenant_id, delete_after);
GO
CREATE INDEX ix_files_read_as ON files (tenant_id, team, read_as);
GO
CREATE INDEX ix_files_team_status ON files (tenant_id, team, status, uploaded_at);
GO
CREATE TABLE files_outbox (
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
	CONSTRAINT files_outbox_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_files_outbox_due ON files_outbox (sent_at, next_at);
GO
CREATE TABLE file_blobs (
	tenant_id VARCHAR(64) NOT NULL, 
	team VARCHAR(64) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	file_id VARCHAR(64) NOT NULL, 
	CONSTRAINT file_blobs_pkey PRIMARY KEY (tenant_id, team, digest)
);
GO
CREATE TABLE file_versions (
	file_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	size BIGINT NOT NULL, 
	storage_key VARCHAR(512) NOT NULL, 
	uploaded_by VARCHAR(320) NOT NULL, 
	uploaded_at DATETIMEOFFSET NOT NULL, 
	[current] BIT NOT NULL, 
	team VARCHAR(64) NOT NULL, 
	CONSTRAINT file_versions_pkey PRIMARY KEY (file_id, version)
);
GO
CREATE TABLE file_references (
	file_id VARCHAR(64) NOT NULL, 
	ref_type VARCHAR(32) NOT NULL, 
	ref_id VARCHAR(128) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	owner_service VARCHAR(32) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	href VARCHAR(512) NULL, 
	added_at DATETIMEOFFSET NOT NULL, 
	blocked VARCHAR(500) NULL, 
	team VARCHAR(64) NOT NULL, 
	CONSTRAINT file_references_pkey PRIMARY KEY (file_id, ref_type, ref_id)
);
GO
CREATE INDEX ix_file_references_owner ON file_references (tenant_id, ref_type, ref_id);
GO
CREATE TABLE file_idempotency (
	tenant_id VARCHAR(64) NOT NULL, 
	key_hash VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	file_id VARCHAR(64) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT file_idempotency_pkey PRIMARY KEY (tenant_id, key_hash)
);
GO
CREATE INDEX ix_file_idempotency_file ON file_idempotency (tenant_id, file_id);
GO
CREATE TABLE file_legal_holds (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	file_id VARCHAR(64) NOT NULL, 
	placed_by VARCHAR(320) NOT NULL, 
	placed_at DATETIMEOFFSET NOT NULL, 
	reason VARCHAR(500) NOT NULL, 
	released_by VARCHAR(320) NULL, 
	released_at DATETIMEOFFSET NULL, 
	release_reason VARCHAR(500) NULL, 
	team VARCHAR(64) NOT NULL, 
	CONSTRAINT file_legal_holds_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_file_legal_holds_file ON file_legal_holds (file_id, released_at);
GO
CREATE TABLE file_read_requests (
	tenant_id VARCHAR(64) NOT NULL, 
	request_key VARCHAR(200) NOT NULL, 
	file_id VARCHAR(64) NOT NULL, 
	team VARCHAR(64) NOT NULL, 
	requested_by VARCHAR(320) NOT NULL, 
	document_type_id VARCHAR(64) NULL, 
	version INTEGER NULL, 
	type_name VARCHAR(200) NULL, 
	status VARCHAR(16) NOT NULL, 
	run_id VARCHAR(64) NULL, 
	requested_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT file_read_requests_pkey PRIMARY KEY (tenant_id, request_key)
);
GO
CREATE INDEX ix_file_read_requests_file ON file_read_requests (tenant_id, file_id);
GO
CREATE TABLE storage_settings (
	tenant_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	document VARCHAR(max) NOT NULL, 
	updated_by VARCHAR(320) NOT NULL, 
	updated_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT storage_settings_pkey PRIMARY KEY (tenant_id)
);
GO
CREATE TABLE storage_credentials (
	tenant_id VARCHAR(64) NOT NULL, 
	name VARCHAR(64) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	sealed VARCHAR(max) NOT NULL, 
	set_by VARCHAR(320) NOT NULL, 
	set_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT storage_credentials_pkey PRIMARY KEY (tenant_id, name)
);
GO
CREATE TABLE storage_settings_audit (
	id INTEGER NOT NULL IDENTITY, 
	tenant_id VARCHAR(64) NOT NULL, 
	action VARCHAR(32) NOT NULL, 
	subject VARCHAR(64) NOT NULL, 
	detail VARCHAR(max) NOT NULL, 
	actor VARCHAR(320) NOT NULL, 
	at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT storage_settings_audit_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_storage_settings_audit_tenant ON storage_settings_audit (tenant_id, at);
GO
IF SCHEMA_ID(N'ops_security') IS NULL EXEC (N'CREATE SCHEMA ops_security AUTHORIZATION dbo');
GO
CREATE FUNCTION ops_security.files_tenant_read (@tenant_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS visible WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64)) OR USER_NAME() = N'ops_files_system';
GO
CREATE FUNCTION ops_security.files_tenant_write (@tenant_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS allowed WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64)) OR USER_NAME() = N'ops_files_system';
GO
CREATE FUNCTION ops_security.files_team_read (@tenant_id VARCHAR(64), @team_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS visible WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64)) AND (CAST(SESSION_CONTEXT(N'scope') AS NVARCHAR(16)) = N'tenant' OR @team_id IS NULL OR @team_id = CAST(SESSION_CONTEXT(N'team_id') AS VARCHAR(64))) OR USER_NAME() = N'ops_files_system';
GO
CREATE FUNCTION ops_security.files_team_write (@tenant_id VARCHAR(64), @team_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS allowed WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64)) AND (CAST(SESSION_CONTEXT(N'scope') AS NVARCHAR(16)) = N'tenant' OR @team_id = CAST(SESSION_CONTEXT(N'team_id') AS VARCHAR(64))) OR USER_NAME() = N'ops_files_system';
GO
CREATE SECURITY POLICY ops_security.files_isolation
    ADD FILTER PREDICATE ops_security.files_team_read(tenant_id, team) ON dbo.files,
    ADD BLOCK PREDICATE ops_security.files_team_write(tenant_id, team) ON dbo.files AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.files_team_write(tenant_id, team) ON dbo.files AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.files_outbox_tenant
    ADD FILTER PREDICATE ops_security.files_tenant_read(tenant_id) ON dbo.files_outbox,
    ADD BLOCK PREDICATE ops_security.files_tenant_write(tenant_id) ON dbo.files_outbox AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.files_tenant_write(tenant_id) ON dbo.files_outbox AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.file_blobs_isolation
    ADD FILTER PREDICATE ops_security.files_team_read(tenant_id, team) ON dbo.file_blobs,
    ADD BLOCK PREDICATE ops_security.files_team_write(tenant_id, team) ON dbo.file_blobs AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.files_team_write(tenant_id, team) ON dbo.file_blobs AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.file_versions_isolation
    ADD FILTER PREDICATE ops_security.files_team_read(tenant_id, team) ON dbo.file_versions,
    ADD BLOCK PREDICATE ops_security.files_team_write(tenant_id, team) ON dbo.file_versions AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.files_team_write(tenant_id, team) ON dbo.file_versions AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.file_references_isolation
    ADD FILTER PREDICATE ops_security.files_team_read(tenant_id, team) ON dbo.file_references,
    ADD BLOCK PREDICATE ops_security.files_team_write(tenant_id, team) ON dbo.file_references AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.files_team_write(tenant_id, team) ON dbo.file_references AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.file_idempotency_tenant
    ADD FILTER PREDICATE ops_security.files_tenant_read(tenant_id) ON dbo.file_idempotency,
    ADD BLOCK PREDICATE ops_security.files_tenant_write(tenant_id) ON dbo.file_idempotency AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.files_tenant_write(tenant_id) ON dbo.file_idempotency AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.file_legal_holds_isolation
    ADD FILTER PREDICATE ops_security.files_team_read(tenant_id, team) ON dbo.file_legal_holds,
    ADD BLOCK PREDICATE ops_security.files_team_write(tenant_id, team) ON dbo.file_legal_holds AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.files_team_write(tenant_id, team) ON dbo.file_legal_holds AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.file_read_requests_isolation
    ADD FILTER PREDICATE ops_security.files_team_read(tenant_id, team) ON dbo.file_read_requests,
    ADD BLOCK PREDICATE ops_security.files_team_write(tenant_id, team) ON dbo.file_read_requests AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.files_team_write(tenant_id, team) ON dbo.file_read_requests AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.storage_settings_tenant
    ADD FILTER PREDICATE ops_security.files_tenant_read(tenant_id) ON dbo.storage_settings,
    ADD BLOCK PREDICATE ops_security.files_tenant_write(tenant_id) ON dbo.storage_settings AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.files_tenant_write(tenant_id) ON dbo.storage_settings AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.storage_credentials_tenant
    ADD FILTER PREDICATE ops_security.files_tenant_read(tenant_id) ON dbo.storage_credentials,
    ADD BLOCK PREDICATE ops_security.files_tenant_write(tenant_id) ON dbo.storage_credentials AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.files_tenant_write(tenant_id) ON dbo.storage_credentials AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.storage_settings_audit_tenant
    ADD FILTER PREDICATE ops_security.files_tenant_read(tenant_id) ON dbo.storage_settings_audit,
    ADD BLOCK PREDICATE ops_security.files_tenant_write(tenant_id) ON dbo.storage_settings_audit AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.files_tenant_write(tenant_id) ON dbo.storage_settings_audit AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE TABLE alembic_version_files (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_files_pkc PRIMARY KEY (version_num)
);
GO
INSERT INTO alembic_version_files (version_num) VALUES ('files_0012');
GO
