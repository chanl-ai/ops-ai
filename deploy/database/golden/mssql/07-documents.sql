-- Ops AI schema for SQL Server, compiled from the store models by deploy/database/mssql.py; do not edit.
-- For review; apply bundle.sql, not these.
-- documents-service, stamped at documents_0013
CREATE TABLE document_types (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	team VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description VARCHAR(1000) NULL, 
	latest_version INTEGER NOT NULL, 
	created_by VARCHAR(320) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT document_types_pkey PRIMARY KEY (tenant_id, id), 
	CONSTRAINT uq_document_types_name UNIQUE (tenant_id, team, name)
);
GO
CREATE TABLE document_type_versions (
	tenant_id VARCHAR(64) NOT NULL, 
	type_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	fields VARCHAR(max) NOT NULL, 
	many BIT NOT NULL, 
	review_below FLOAT NULL, 
	date_order VARCHAR(3) NULL, 
	templates VARCHAR(max) NULL, 
	checks VARCHAR(max) NULL, 
	page_images BIT NULL, 
	offer_at INTEGER NULL, 
	note VARCHAR(500) NULL, 
	created_by VARCHAR(320) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	team VARCHAR(64) NOT NULL, 
	CONSTRAINT document_type_versions_pkey PRIMARY KEY (tenant_id, type_id, version)
);
GO
CREATE TABLE document_type_samples (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	type_id VARCHAR(64) NOT NULL, 
	file_id VARCHAR(64) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	expected VARCHAR(max) NOT NULL, 
	added_by VARCHAR(320) NOT NULL, 
	added_at DATETIMEOFFSET NOT NULL, 
	team VARCHAR(64) NOT NULL, 
	CONSTRAINT document_type_samples_pkey PRIMARY KEY (tenant_id, id)
);
GO
CREATE INDEX ix_document_type_samples_type ON document_type_samples (tenant_id, type_id);
GO
CREATE TABLE document_type_tests (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	type_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	team VARCHAR(64) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	samples INTEGER NOT NULL, 
	result VARCHAR(max) NULL, 
	error VARCHAR(max) NULL, 
	asked_by VARCHAR(320) NOT NULL, 
	asked_at DATETIMEOFFSET NOT NULL, 
	finished_at DATETIMEOFFSET NULL, 
	CONSTRAINT document_type_tests_pkey PRIMARY KEY (tenant_id, id)
);
GO
CREATE INDEX ix_document_type_tests_status ON document_type_tests (status);
GO
CREATE INDEX ix_document_type_tests_type ON document_type_tests (tenant_id, type_id, version);
GO
CREATE TABLE document_type_examples (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	team VARCHAR(64) NOT NULL, 
	type_id VARCHAR(64) NOT NULL, 
	field VARCHAR(128) NOT NULL, 
	line VARCHAR(max) NULL, 
	value VARCHAR(max) NOT NULL, 
	extraction_id VARCHAR(64) NOT NULL, 
	record INTEGER NOT NULL, 
	corrected_by VARCHAR(320) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT document_type_examples_pkey PRIMARY KEY (tenant_id, id), 
	CONSTRAINT uq_document_type_examples_read UNIQUE (tenant_id, extraction_id, field, record)
);
GO
CREATE INDEX ix_document_type_examples_type ON document_type_examples (tenant_id, team, type_id, created_at);
GO
CREATE TABLE extractions (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	team VARCHAR(64) NOT NULL, 
	file_id VARCHAR(64) NOT NULL, 
	file_digest VARCHAR(64) NOT NULL, 
	request VARCHAR(max) NOT NULL, 
	schema_digest VARCHAR(64) NOT NULL, 
	alias VARCHAR(64) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	outcome VARCHAR(16) NULL, 
	result VARCHAR(max) NULL, 
	error_code VARCHAR(64) NULL, 
	error VARCHAR(max) NULL, 
	attempts INTEGER NOT NULL, 
	key_hash VARCHAR(64) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	asked_by VARCHAR(320) NOT NULL, 
	asked_at DATETIMEOFFSET NOT NULL, 
	started_at DATETIMEOFFSET NULL, 
	finished_at DATETIMEOFFSET NULL, 
	type_id VARCHAR(64) NULL, 
	input_tokens INTEGER NULL, 
	output_tokens INTEGER NULL, 
	layout_fingerprint VARCHAR(32) NULL, 
	CONSTRAINT extractions_pkey PRIMARY KEY (id), 
	CONSTRAINT uq_extractions_key UNIQUE (tenant_id, key_hash)
);
GO
CREATE INDEX ix_extractions_file ON extractions (tenant_id, file_id);
GO
CREATE INDEX ix_extractions_status ON extractions (status);
GO
CREATE INDEX ix_extractions_type_reads ON extractions (tenant_id, team, type_id, status, finished_at);
GO
CREATE TABLE documents_outbox (
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
	CONSTRAINT documents_outbox_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_documents_outbox_due ON documents_outbox (sent_at, next_at);
GO
CREATE TABLE extraction_corrections (
	id INTEGER NOT NULL IDENTITY, 
	tenant_id VARCHAR(64) NOT NULL, 
	extraction_id VARCHAR(64) NOT NULL, 
	field VARCHAR(128) NOT NULL, 
	record INTEGER NULL, 
	original VARCHAR(max) NOT NULL, 
	original_confidence FLOAT NOT NULL, 
	corrected VARCHAR(max) NOT NULL, 
	corrected_by VARCHAR(320) NOT NULL, 
	corrected_at DATETIMEOFFSET NOT NULL, 
	team VARCHAR(64) NOT NULL, 
	CONSTRAINT extraction_corrections_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_extraction_corrections_extraction ON extraction_corrections (tenant_id, extraction_id);
GO
CREATE TABLE documents_layouts (
	tenant_id VARCHAR(64) NOT NULL, 
	file_digest VARCHAR(64) NOT NULL, 
	engine VARCHAR(32) NOT NULL, 
	ocr BIT NOT NULL, 
	pages INTEGER NOT NULL, 
	layout VARCHAR(max) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT documents_layouts_pkey PRIMARY KEY (tenant_id, file_digest, engine, ocr)
);
GO
IF SCHEMA_ID(N'ops_security') IS NULL EXEC (N'CREATE SCHEMA ops_security AUTHORIZATION dbo');
GO
CREATE FUNCTION ops_security.documents_tenant_read (@tenant_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS visible WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64)) OR USER_NAME() = N'ops_documents_system';
GO
CREATE FUNCTION ops_security.documents_tenant_write (@tenant_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS allowed WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64)) OR USER_NAME() = N'ops_documents_system';
GO
CREATE FUNCTION ops_security.documents_team_read (@tenant_id VARCHAR(64), @team_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS visible WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64)) AND (CAST(SESSION_CONTEXT(N'scope') AS NVARCHAR(16)) = N'tenant' OR @team_id = CAST(SESSION_CONTEXT(N'team_id') AS VARCHAR(64))) OR USER_NAME() = N'ops_documents_system';
GO
CREATE FUNCTION ops_security.documents_team_write (@tenant_id VARCHAR(64), @team_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS allowed WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64)) AND (CAST(SESSION_CONTEXT(N'scope') AS NVARCHAR(16)) = N'tenant' OR @team_id = CAST(SESSION_CONTEXT(N'team_id') AS VARCHAR(64))) OR USER_NAME() = N'ops_documents_system';
GO
CREATE SECURITY POLICY ops_security.document_types_isolation
    ADD FILTER PREDICATE ops_security.documents_team_read(tenant_id, team) ON dbo.document_types,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.document_types AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.document_types AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.document_type_versions_isolation
    ADD FILTER PREDICATE ops_security.documents_team_read(tenant_id, team) ON dbo.document_type_versions,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.document_type_versions AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.document_type_versions AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.document_type_samples_isolation
    ADD FILTER PREDICATE ops_security.documents_team_read(tenant_id, team) ON dbo.document_type_samples,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.document_type_samples AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.document_type_samples AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.document_type_tests_isolation
    ADD FILTER PREDICATE ops_security.documents_team_read(tenant_id, team) ON dbo.document_type_tests,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.document_type_tests AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.document_type_tests AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.document_type_examples_isolation
    ADD FILTER PREDICATE ops_security.documents_team_read(tenant_id, team) ON dbo.document_type_examples,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.document_type_examples AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.document_type_examples AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.extractions_isolation
    ADD FILTER PREDICATE ops_security.documents_team_read(tenant_id, team) ON dbo.extractions,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.extractions AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.extractions AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.documents_outbox_tenant
    ADD FILTER PREDICATE ops_security.documents_tenant_read(tenant_id) ON dbo.documents_outbox,
    ADD BLOCK PREDICATE ops_security.documents_tenant_write(tenant_id) ON dbo.documents_outbox AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.documents_tenant_write(tenant_id) ON dbo.documents_outbox AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.extraction_corrections_isolation
    ADD FILTER PREDICATE ops_security.documents_team_read(tenant_id, team) ON dbo.extraction_corrections,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.extraction_corrections AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.documents_team_write(tenant_id, team) ON dbo.extraction_corrections AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.documents_layouts_tenant
    ADD FILTER PREDICATE ops_security.documents_tenant_read(tenant_id) ON dbo.documents_layouts,
    ADD BLOCK PREDICATE ops_security.documents_tenant_write(tenant_id) ON dbo.documents_layouts AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.documents_tenant_write(tenant_id) ON dbo.documents_layouts AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE TABLE alembic_version_documents (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_documents_pkc PRIMARY KEY (version_num)
);
GO
INSERT INTO alembic_version_documents (version_num) VALUES ('documents_0013');
GO
