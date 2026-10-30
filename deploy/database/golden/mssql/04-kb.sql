-- Ops AI schema for SQL Server, compiled from the store models by deploy/database/mssql.py; do not edit.
-- For review; apply bundle.sql, not these.
-- kb-service, stamped at kb_0012
-- not on SQL Server yet: kb_chunks.tsv (TSVECTOR)
-- not on SQL Server yet: index ix_kb_chunks_tsv
CREATE TABLE kb_bases (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	slug VARCHAR(200) NOT NULL, 
	description VARCHAR(max) NOT NULL, 
	color VARCHAR(32) NOT NULL, 
	owner VARCHAR(200) NOT NULL, 
	collections NVARCHAR(max) NOT NULL, 
	retrieval NVARCHAR(max) NOT NULL, 
	created_by VARCHAR(200) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	last_refreshed_at DATETIMEOFFSET NULL, 
	template_id VARCHAR(120) NULL, 
	protection VARCHAR(16) NULL, 
	documents_source_id VARCHAR(64) NULL, 
	CONSTRAINT kb_bases_pkey PRIMARY KEY (tenant_id, id), 
	CONSTRAINT uq_kb_bases_name UNIQUE (tenant_id, team_id, name)
);
GO
CREATE TABLE kb_sources (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	type VARCHAR(32) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	collection VARCHAR(120) NOT NULL, 
	owner VARCHAR(200) NOT NULL, 
	sensitivity VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	tags NVARCHAR(max) NOT NULL, 
	file_ids NVARCHAR(max) NOT NULL, 
	file_names NVARCHAR(max) NULL, 
	created_by VARCHAR(200) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	last_sync_at DATETIMEOFFSET NULL, 
	last_run_status VARCHAR(16) NULL, 
	config NVARCHAR(max) NULL, 
	lease_until DATETIMEOFFSET NULL, 
	CONSTRAINT kb_sources_pkey PRIMARY KEY (tenant_id, id)
);
GO
CREATE TABLE kb_retired_bases (
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	retired_by VARCHAR(200) NOT NULL, 
	retired_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT kb_retired_bases_pkey PRIMARY KEY (tenant_id, id)
);
GO
CREATE TABLE kb_changes (
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	item_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(64) NOT NULL, 
	title VARCHAR(400) NOT NULL, 
	section VARCHAR(400) NOT NULL, 
	from_version INTEGER NOT NULL, 
	to_version INTEGER NOT NULL, 
	before VARCHAR(max) NOT NULL, 
	after VARCHAR(max) NOT NULL, 
	changed_by VARCHAR(200) NOT NULL, 
	changed_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT kb_changes_pkey PRIMARY KEY (tenant_id, id)
);
GO
CREATE INDEX ix_kb_changes_at ON kb_changes (tenant_id, changed_at);
GO
CREATE TABLE kb_base_sources (
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	kb_id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(64) NOT NULL, 
	CONSTRAINT kb_base_sources_pkey PRIMARY KEY (tenant_id, kb_id, source_id), 
	CONSTRAINT fk_kb_link_base FOREIGN KEY(tenant_id, kb_id) REFERENCES kb_bases (tenant_id, id) ON DELETE CASCADE, 
	CONSTRAINT fk_kb_link_source FOREIGN KEY(tenant_id, source_id) REFERENCES kb_sources (tenant_id, id) ON DELETE CASCADE
);
GO
CREATE TABLE kb_items (
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(64) NOT NULL, 
	path VARCHAR(400) NOT NULL, 
	title VARCHAR(400) NOT NULL, 
	mime VARCHAR(120) NOT NULL, 
	size INTEGER NOT NULL, 
	file_id VARCHAR(64) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	error_class VARCHAR(32) NULL, 
	error VARCHAR(max) NULL, 
	warning VARCHAR(max) NULL, 
	page_count INTEGER NULL, 
	chunk_count INTEGER NOT NULL, 
	owner VARCHAR(200) NOT NULL, 
	verified BIT NOT NULL DEFAULT 0, 
	verified_by VARCHAR(200) NULL, 
	verified_at DATETIMEOFFSET NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	processed_at DATETIMEOFFSET NULL, 
	marker VARCHAR(120) NULL, 
	parent_id VARCHAR(64) NULL, 
	url VARCHAR(max) NULL, 
	CONSTRAINT kb_items_pkey PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_kb_item_source FOREIGN KEY(tenant_id, source_id) REFERENCES kb_sources (tenant_id, id) ON DELETE CASCADE, 
	CONSTRAINT uq_kb_items_path UNIQUE (tenant_id, source_id, path)
);
GO
CREATE TABLE kb_runs (
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	source_id VARCHAR(64) NOT NULL, 
	[trigger] VARCHAR(16) NOT NULL, 
	started_at DATETIMEOFFSET NOT NULL, 
	duration_sec FLOAT NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	counts NVARCHAR(max) NOT NULL, 
	errors NVARCHAR(max) NOT NULL, 
	log NVARCHAR(max) NOT NULL, 
	started_by VARCHAR(200) NOT NULL, 
	CONSTRAINT kb_runs_pkey PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_kb_run_source FOREIGN KEY(tenant_id, source_id) REFERENCES kb_sources (tenant_id, id) ON DELETE CASCADE
);
GO
CREATE INDEX ix_kb_runs_source ON kb_runs (tenant_id, source_id, started_at);
GO
CREATE TABLE kb_item_versions (
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	item_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	file_id VARCHAR(64) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	created_by VARCHAR(200) NOT NULL, 
	created_at DATETIMEOFFSET NOT NULL, 
	CONSTRAINT kb_item_versions_pkey PRIMARY KEY (tenant_id, item_id, version), 
	CONSTRAINT fk_kb_version_item FOREIGN KEY(tenant_id, item_id) REFERENCES kb_items (tenant_id, id) ON DELETE CASCADE
);
GO
CREATE TABLE kb_chunks (
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	item_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	position INTEGER NOT NULL, 
	title VARCHAR(400) NOT NULL, 
	section VARCHAR(400) NOT NULL, 
	page INTEGER NULL, 
	tokens INTEGER NOT NULL, 
	text VARCHAR(max) NOT NULL, 
	withdrawn_at DATETIMEOFFSET NULL, 
	CONSTRAINT kb_chunks_pkey PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_kb_chunk_item FOREIGN KEY(tenant_id, item_id) REFERENCES kb_items (tenant_id, id) ON DELETE CASCADE
);
GO
IF SCHEMA_ID(N'ops_security') IS NULL EXEC (N'CREATE SCHEMA ops_security AUTHORIZATION dbo');
GO
CREATE FUNCTION ops_security.kb_team_read (@tenant_id VARCHAR(64), @team_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS visible WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64)) AND (CAST(SESSION_CONTEXT(N'scope') AS NVARCHAR(16)) = N'tenant' OR @team_id = CAST(SESSION_CONTEXT(N'team_id') AS VARCHAR(64)));
GO
CREATE FUNCTION ops_security.kb_team_write (@tenant_id VARCHAR(64), @team_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS allowed WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64)) AND (CAST(SESSION_CONTEXT(N'scope') AS NVARCHAR(16)) = N'tenant' OR @team_id = CAST(SESSION_CONTEXT(N'team_id') AS VARCHAR(64)));
GO
CREATE SECURITY POLICY ops_security.kb_bases_isolation
    ADD FILTER PREDICATE ops_security.kb_team_read(tenant_id, team_id) ON dbo.kb_bases,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_bases AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_bases AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.kb_sources_isolation
    ADD FILTER PREDICATE ops_security.kb_team_read(tenant_id, team_id) ON dbo.kb_sources,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_sources AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_sources AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.kb_retired_bases_isolation
    ADD FILTER PREDICATE ops_security.kb_team_read(tenant_id, team_id) ON dbo.kb_retired_bases,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_retired_bases AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_retired_bases AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.kb_changes_isolation
    ADD FILTER PREDICATE ops_security.kb_team_read(tenant_id, team_id) ON dbo.kb_changes,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_changes AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_changes AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.kb_base_sources_isolation
    ADD FILTER PREDICATE ops_security.kb_team_read(tenant_id, team_id) ON dbo.kb_base_sources,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_base_sources AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_base_sources AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.kb_items_isolation
    ADD FILTER PREDICATE ops_security.kb_team_read(tenant_id, team_id) ON dbo.kb_items,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_items AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_items AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.kb_runs_isolation
    ADD FILTER PREDICATE ops_security.kb_team_read(tenant_id, team_id) ON dbo.kb_runs,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_runs AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_runs AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.kb_item_versions_isolation
    ADD FILTER PREDICATE ops_security.kb_team_read(tenant_id, team_id) ON dbo.kb_item_versions,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_item_versions AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_item_versions AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.kb_chunks_isolation
    ADD FILTER PREDICATE ops_security.kb_team_read(tenant_id, team_id) ON dbo.kb_chunks,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_chunks AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.kb_team_write(tenant_id, team_id) ON dbo.kb_chunks AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE TABLE alembic_version_kb (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_kb_pkc PRIMARY KEY (version_num)
);
GO
INSERT INTO alembic_version_kb (version_num) VALUES ('kb_0012');
GO
