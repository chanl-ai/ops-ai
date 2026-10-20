-- Ops AI schema for SQL Server, compiled from the store models by deploy/database/mssql.py; do not edit.
-- For review; apply bundle.sql, not these.
-- documents-service, stamped at documents_0010
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
CREATE TABLE alembic_version_documents (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_documents_pkc PRIMARY KEY (version_num)
);
GO
INSERT INTO alembic_version_documents (version_num) VALUES ('documents_0010');
GO
