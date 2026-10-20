-- Ops AI schema for SQL Server, compiled from the store models by deploy/database/mssql.py; do not edit.
-- For review; apply bundle.sql, not these.
-- agents-service, stamped at 0072_memories_system_tenants
CREATE TABLE engine_definitions (
	tenant_id VARCHAR(64) NOT NULL, 
	workflow_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	definition NVARCHAR(max) NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	created_by VARCHAR(200) NOT NULL, 
	team_id VARCHAR(64) NULL, 
	stage VARCHAR(16) NOT NULL DEFAULT 'draft', 
	archived_at VARCHAR(32) NULL, 
	archived_by VARCHAR(200) NULL, 
	CONSTRAINT engine_definitions_pkey PRIMARY KEY (tenant_id, workflow_id, version), 
	CONSTRAINT uq_engine_definitions_digest UNIQUE (tenant_id, workflow_id, digest)
);
GO
CREATE INDEX ix_engine_definitions_live ON engine_definitions (tenant_id, workflow_id) WHERE stage = 'live';
GO
CREATE TABLE engine_runs (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	workflow_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	run_key VARCHAR(200) NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	input NVARCHAR(max) NULL, 
	outcome VARCHAR(64) NULL, 
	output NVARCHAR(max) NULL, 
	error VARCHAR(max) NULL, 
	waiting NVARCHAR(max) NULL, 
	created_by VARCHAR(200) NOT NULL, 
	started_via VARCHAR(200) NULL, 
	created_at VARCHAR(32) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	finished_at VARCHAR(32) NULL, 
	CONSTRAINT engine_runs_pkey PRIMARY KEY (id), 
	CONSTRAINT uq_engine_runs_key UNIQUE (tenant_id, workflow_id, run_key)
);
GO
CREATE INDEX ix_engine_runs_parent_status ON engine_runs (tenant_id, created_by, status);
GO
CREATE INDEX ix_engine_runs_team_created ON engine_runs (tenant_id, team_id, created_at);
GO
CREATE INDEX ix_engine_runs_team_status_created ON engine_runs (tenant_id, team_id, status, created_at);
GO
CREATE INDEX ix_engine_runs_tenant_id ON engine_runs (tenant_id);
GO
CREATE INDEX ix_engine_runs_workflow_created ON engine_runs (tenant_id, workflow_id, created_at);
GO
CREATE INDEX ix_engine_runs_workflow_id ON engine_runs (workflow_id);
GO
CREATE TABLE engine_steps (
	run_id VARCHAR(64) NOT NULL, 
	node_id VARCHAR(80) NOT NULL, 
	iteration INTEGER NOT NULL, 
	attempt INTEGER NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	effects VARCHAR(8) NOT NULL, 
	[key] VARCHAR(240) NOT NULL, 
	input NVARCHAR(max) NULL, 
	port VARCHAR(80) NULL, 
	output NVARCHAR(max) NULL, 
	error VARCHAR(max) NULL, 
	started_at VARCHAR(32) NOT NULL, 
	finished_at VARCHAR(32) NULL, 
	node_type VARCHAR(80) NULL, 
	CONSTRAINT engine_steps_pkey PRIMARY KEY (run_id, node_id, iteration, attempt)
);
GO
CREATE INDEX ix_engine_steps_tenant_id ON engine_steps (tenant_id);
GO
CREATE TABLE engine_work (
	id BIGINT NOT NULL IDENTITY, 
	tenant_id VARCHAR(64) NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	payload NVARCHAR(max) NULL, 
	dedupe_key VARCHAR(240) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	build VARCHAR(32) NOT NULL, 
	available_at FLOAT NOT NULL, 
	claimed_by VARCHAR(120) NULL, 
	lease_expires_at FLOAT NULL, 
	attempts INTEGER NOT NULL DEFAULT '0', 
	error VARCHAR(max) NULL, 
	created_at VARCHAR(32) NOT NULL, 
	CONSTRAINT engine_work_pkey PRIMARY KEY (id), 
	CONSTRAINT uq_engine_work_dedupe UNIQUE (tenant_id, dedupe_key)
);
GO
CREATE INDEX ix_engine_work_due ON engine_work (status, build, available_at);
GO
CREATE INDEX ix_engine_work_lease ON engine_work (status, build, lease_expires_at);
GO
CREATE INDEX ix_engine_work_run_id ON engine_work (run_id);
GO
CREATE INDEX ix_engine_work_tenant_id ON engine_work (tenant_id);
GO
CREATE TABLE registry_agents (
	id VARCHAR(64) NOT NULL, 
	slug VARCHAR(120) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	published_version INTEGER NULL, 
	paused BIT NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	template_id VARCHAR(120) NULL, 
	protection VARCHAR(16) NULL, 
	CONSTRAINT registry_agents_pkey PRIMARY KEY (id), 
	CONSTRAINT registry_agents_slug_key UNIQUE (slug)
);
GO
CREATE INDEX ix_registry_agents_template_id ON registry_agents (template_id);
GO
CREATE TABLE registry_publish_requests (
	tenant_id VARCHAR(64) NOT NULL DEFAULT 'local', 
	id VARCHAR(64) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	subject_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	note VARCHAR(max) NOT NULL, 
	requested_by VARCHAR(200) NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	decided_at VARCHAR(32) NULL, 
	decided_by VARCHAR(200) NULL, 
	decision_reason VARCHAR(max) NULL, 
	body NVARCHAR(max) NOT NULL, 
	CONSTRAINT registry_publish_requests_pkey PRIMARY KEY (tenant_id, id)
);
GO
CREATE INDEX ix_registry_publish_requests_subject ON registry_publish_requests (kind, subject_id);
GO
CREATE INDEX ix_registry_publish_requests_tenant_id ON registry_publish_requests (tenant_id);
GO
CREATE TABLE cases (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	producer_key VARCHAR(200) NULL, 
	subject VARCHAR(300) NOT NULL, 
	customer_id VARCHAR(200) NULL, 
	customer_name VARCHAR(300) NULL, 
	status VARCHAR(32) NOT NULL, 
	assignee VARCHAR(320) NULL, 
	priority VARCHAR(16) NOT NULL, 
	response_due_at VARCHAR(32) NOT NULL, 
	resolution_due_at VARCHAR(32) NOT NULL, 
	responded_at VARCHAR(32) NULL, 
	paused_since VARCHAR(32) NULL, 
	fields NVARCHAR(max) NULL, 
	type_id VARCHAR(64) NULL, 
	type_version INTEGER NULL, 
	created_by VARCHAR(320) NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	CONSTRAINT cases_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_cases_team_due ON cases (tenant_id, team_id, resolution_due_at);
GO
CREATE UNIQUE INDEX uq_cases_producer_key ON cases (tenant_id, team_id, producer_key) WHERE producer_key IS NOT NULL;
GO
CREATE TABLE case_events (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	case_id VARCHAR(64) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	ref VARCHAR(200) NULL, 
	detail VARCHAR(max) NOT NULL, 
	[by] VARCHAR(320) NOT NULL, 
	at VARCHAR(32) NOT NULL, 
	CONSTRAINT case_events_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_case_events_case_id ON case_events (case_id);
GO
CREATE INDEX ix_case_events_tenant_id ON case_events (tenant_id);
GO
CREATE TABLE thread_leases (
	thread_id VARCHAR(64) NOT NULL, 
	owner VARCHAR(120) NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	acquired_at FLOAT NOT NULL, 
	heartbeat_at FLOAT NOT NULL, 
	expires_at FLOAT NOT NULL, 
	generation BIGINT NOT NULL DEFAULT '1', 
	released_at FLOAT NULL, 
	CONSTRAINT thread_leases_pkey PRIMARY KEY (thread_id)
);
GO
CREATE INDEX ix_thread_leases_expires_at ON thread_leases (expires_at);
GO
CREATE TABLE thread_events (
	position BIGINT NOT NULL IDENTITY, 
	id VARCHAR(40) NOT NULL, 
	thread_id VARCHAR(64) NOT NULL, 
	seq INTEGER NOT NULL, 
	run_id VARCHAR(80) NULL, 
	type VARCHAR(32) NOT NULL, 
	node VARCHAR(120) NULL, 
	at VARCHAR(32) NOT NULL, 
	data NVARCHAR(max) NULL, 
	team_id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL DEFAULT 'local', 
	CONSTRAINT thread_events_pkey PRIMARY KEY (position), 
	CONSTRAINT uq_thread_events_thread_seq UNIQUE (thread_id, seq), 
	CONSTRAINT thread_events_id_key UNIQUE (id)
);
GO
CREATE INDEX ix_thread_events_run ON thread_events (thread_id, run_id, seq);
GO
CREATE INDEX ix_thread_events_tenant_id ON thread_events (tenant_id);
GO
CREATE INDEX ix_thread_events_tenant_team_position ON thread_events (tenant_id, team_id, position);
GO
CREATE TABLE graph_threads (
	id VARCHAR(64) NOT NULL, 
	graph VARCHAR(64) NOT NULL, 
	meta NVARCHAR(max) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	version INTEGER NULL, 
	digest VARCHAR(64) NULL, 
	external_key VARCHAR(512) NULL, 
	deployment_id VARCHAR(64) NULL, 
	parent_thread_id VARCHAR(64) NULL, 
	overrides NVARCHAR(max) NULL, 
	tenant_id VARCHAR(64) NOT NULL DEFAULT 'local', 
	CONSTRAINT graph_threads_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_graph_threads_deployment_id ON graph_threads (deployment_id);
GO
CREATE INDEX ix_graph_threads_graph ON graph_threads (graph);
GO
CREATE INDEX ix_graph_threads_parent_thread_id ON graph_threads (parent_thread_id);
GO
CREATE INDEX ix_graph_threads_team_updated ON graph_threads (tenant_id, team_id, updated_at);
GO
CREATE INDEX ix_graph_threads_tenant_id ON graph_threads (tenant_id);
GO
CREATE UNIQUE INDEX uq_graph_threads_tenant_external_key ON graph_threads (tenant_id, external_key) WHERE external_key IS NOT NULL;
GO
CREATE TABLE graph_versions (
	name VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	definition NVARCHAR(max) NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	CONSTRAINT graph_versions_pkey PRIMARY KEY (name, version), 
	CONSTRAINT graph_versions_digest_key UNIQUE (digest)
);
GO
CREATE TABLE mailboxes (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	address VARCHAR(320) NOT NULL, 
	provider VARCHAR(16) NOT NULL, 
	imap_host VARCHAR(255) NULL, 
	imap_port INTEGER NULL, 
	imap_tls BIT NOT NULL DEFAULT 1, 
	username VARCHAR(320) NULL, 
	password_secret VARCHAR(120) NULL, 
	graph_tenant_id VARCHAR(64) NULL, 
	graph_client_id VARCHAR(64) NULL, 
	folder VARCHAR(200) NOT NULL DEFAULT 'inbox', 
	sender VARCHAR(16) NOT NULL DEFAULT 'none', 
	from_address VARCHAR(320) NULL, 
	smtp_host VARCHAR(255) NULL, 
	smtp_port INTEGER NULL, 
	smtp_starttls BIT NOT NULL DEFAULT 1, 
	sender_secret VARCHAR(120) NULL, 
	paused BIT NOT NULL DEFAULT 0, 
	created_by VARCHAR(320) NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	CONSTRAINT mailboxes_pkey PRIMARY KEY (id), 
	CONSTRAINT uq_mailboxes_tenant_address UNIQUE (tenant_id, address)
);
GO
CREATE TABLE review_decisions (
	thread_id VARCHAR(64) NOT NULL, 
	decision_id VARCHAR(64) NOT NULL, 
	decision VARCHAR(16) NOT NULL, 
	reason VARCHAR(max) NULL, 
	decided_by VARCHAR(200) NOT NULL, 
	decided_at VARCHAR(32) NOT NULL, 
	review NVARCHAR(max) NOT NULL, 
	attempts INTEGER NOT NULL DEFAULT '0', 
	run_id VARCHAR(80) NULL, 
	resumed_at VARCHAR(32) NULL, 
	tenant_id VARCHAR(64) NOT NULL DEFAULT 'local', 
	team_id VARCHAR(64) NULL, 
	step_up_ref VARCHAR(40) NULL, 
	CONSTRAINT review_decisions_pkey PRIMARY KEY (thread_id, decision_id)
);
GO
CREATE INDEX ix_review_decisions_tenant_id ON review_decisions (tenant_id);
GO
CREATE TABLE review_approvals (
	thread_id VARCHAR(64) NOT NULL, 
	step VARCHAR(200) NOT NULL, 
	approver VARCHAR(200) NOT NULL, 
	input_hash VARCHAR(64) NOT NULL, 
	approved_at VARCHAR(32) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL DEFAULT 'local', 
	team_id VARCHAR(64) NULL, 
	CONSTRAINT review_approvals_pkey PRIMARY KEY (thread_id, step, approver)
);
GO
CREATE INDEX ix_review_approvals_tenant_id ON review_approvals (tenant_id);
GO
CREATE TABLE service_events (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	event_key VARCHAR(200) NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	actor VARCHAR(320) NULL, 
	payload NVARCHAR(max) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	run_ids NVARCHAR(max) NOT NULL, 
	attempts INTEGER NOT NULL, 
	recorded_at VARCHAR(32) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	CONSTRAINT service_events_pkey PRIMARY KEY (id), 
	CONSTRAINT uq_service_events_key UNIQUE (tenant_id, name, event_key)
);
GO
CREATE TABLE trigger_events (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	workflow_id VARCHAR(200) NOT NULL, 
	source VARCHAR(320) NOT NULL, 
	event_key VARCHAR(200) NOT NULL, 
	sender VARCHAR(320) NOT NULL, 
	subject VARCHAR(500) NOT NULL, 
	received_at VARCHAR(40) NOT NULL, 
	outcome VARCHAR(16) NOT NULL, 
	run_id VARCHAR(64) NULL, 
	detail VARCHAR(max) NOT NULL, 
	recorded_at VARCHAR(32) NOT NULL, 
	CONSTRAINT trigger_events_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_trigger_events_workflow ON trigger_events (tenant_id, workflow_id, recorded_at);
GO
CREATE TABLE widget_deployments (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL DEFAULT 'local', 
	team_id VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	agent_id VARCHAR(64) NOT NULL, 
	agent_version INTEGER NULL, 
	origins NVARCHAR(max) NOT NULL, 
	paused BIT NOT NULL, 
	retired_at VARCHAR(32) NULL, 
	created_by VARCHAR(320) NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	CONSTRAINT widget_deployments_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_widget_deployments_tenant_id ON widget_deployments (tenant_id);
GO
CREATE TABLE case_types (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NULL, 
	origin VARCHAR(16) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description VARCHAR(max) NOT NULL, 
	version INTEGER NOT NULL, 
	published_version INTEGER NULL, 
	copied_from NVARCHAR(max) NULL, 
	created_at VARCHAR(32) NOT NULL, 
	created_by VARCHAR(320) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	updated_by VARCHAR(320) NOT NULL, 
	CONSTRAINT case_types_pkey PRIMARY KEY (tenant_id, id)
);
GO
CREATE TABLE case_type_versions (
	tenant_id VARCHAR(64) NOT NULL, 
	type_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	record NVARCHAR(max) NOT NULL, 
	saved_at VARCHAR(32) NOT NULL, 
	saved_by VARCHAR(320) NOT NULL, 
	published_at VARCHAR(32) NULL, 
	published_by VARCHAR(320) NULL, 
	CONSTRAINT case_type_versions_pkey PRIMARY KEY (tenant_id, type_id, version)
);
GO
CREATE TABLE poll_cursors (
	tenant_id VARCHAR(64) NOT NULL, 
	binding_id VARCHAR(80) NOT NULL, 
	source VARCHAR(320) NOT NULL, 
	folder VARCHAR(200) NOT NULL, 
	[cursor] VARCHAR(max) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	CONSTRAINT poll_cursors_pkey PRIMARY KEY (tenant_id, binding_id)
);
GO
CREATE TABLE deployments (
	id VARCHAR(64) NOT NULL, 
	graph VARCHAR(64) NOT NULL, 
	channel VARCHAR(32) NOT NULL, 
	paused BIT NOT NULL DEFAULT 0, 
	multitask VARCHAR(16) NOT NULL DEFAULT 'enqueue', 
	created_at VARCHAR(32) NOT NULL, 
	budget NVARCHAR(max) NULL, 
	team_id VARCHAR(64) NOT NULL DEFAULT '', 
	CONSTRAINT deployments_pkey PRIMARY KEY (id)
);
GO
CREATE TABLE channel_messages (
	deployment_id VARCHAR(64) NOT NULL, 
	message_key VARCHAR(512) NOT NULL, 
	thread_id VARCHAR(64) NULL, 
	role VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	payload NVARCHAR(max) NULL, 
	received_at VARCHAR(32) NOT NULL, 
	CONSTRAINT channel_messages_pkey PRIMARY KEY (deployment_id, message_key)
);
GO
CREATE TABLE channel_cursors (
	deployment_id VARCHAR(64) NOT NULL, 
	delta_link VARCHAR(max) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	CONSTRAINT channel_cursors_pkey PRIMARY KEY (deployment_id)
);
GO
CREATE TABLE thread_inbox (
	thread_id VARCHAR(64) NOT NULL, 
	message_key VARCHAR(512) NOT NULL, 
	seq BIGINT NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	payload NVARCHAR(max) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	delivered_at VARCHAR(32) NULL, 
	CONSTRAINT thread_inbox_pkey PRIMARY KEY (thread_id, message_key)
);
GO
CREATE TABLE channel_files (
	file_id VARCHAR(64) NOT NULL, 
	name VARCHAR(512) NOT NULL, 
	content_type VARCHAR(128) NOT NULL, 
	size INTEGER NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	content VARCHAR(max) NOT NULL, 
	CONSTRAINT channel_files_pkey PRIMARY KEY (file_id)
);
GO
CREATE TABLE chat_attachments (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL DEFAULT 'local', 
	team_id VARCHAR(64) NOT NULL, 
	owner_email VARCHAR(320) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	mime VARCHAR(127) NOT NULL, 
	size INTEGER NOT NULL, 
	pages NVARCHAR(max) NOT NULL, 
	truncated BIT NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	CONSTRAINT chat_attachments_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_chat_attachments_tenant_id ON chat_attachments (tenant_id);
GO
CREATE TABLE chat_search (
	thread_id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL DEFAULT 'local', 
	team_id VARCHAR(64) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	agent_name VARCHAR(200) NOT NULL, 
	preview VARCHAR(400) NOT NULL, 
	questions VARCHAR(max) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	CONSTRAINT chat_search_pkey PRIMARY KEY (thread_id)
);
GO
CREATE INDEX ix_chat_search_team_id ON chat_search (team_id);
GO
CREATE INDEX ix_chat_search_tenant_id ON chat_search (tenant_id);
GO
CREATE TABLE registry_guardrails (
	id VARCHAR(64) NOT NULL, 
	slug VARCHAR(120) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	owner VARCHAR(200) NOT NULL, 
	version INTEGER NOT NULL, 
	published_version INTEGER NULL, 
	status VARCHAR(16) NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	CONSTRAINT registry_guardrails_pkey PRIMARY KEY (id), 
	CONSTRAINT registry_guardrails_slug_key UNIQUE (slug)
);
GO
CREATE TABLE agent_memories (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	agent_id VARCHAR(64) NOT NULL, 
	person VARCHAR(320) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	[key] VARCHAR(120) NULL, 
	value VARCHAR(2000) NOT NULL, 
	confidence FLOAT NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	source_thread_id VARCHAR(64) NULL, 
	created_at VARCHAR(32) NOT NULL, 
	superseded_at VARCHAR(32) NULL, 
	CONSTRAINT agent_memories_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_agent_memories_owner ON agent_memories (tenant_id, person, agent_id);
GO
CREATE INDEX ix_agent_memories_tenant_id ON agent_memories (tenant_id);
GO
CREATE TABLE memory_audit (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	person VARCHAR(320) NOT NULL, 
	agent_id VARCHAR(64) NOT NULL, 
	memory_id VARCHAR(64) NULL, 
	action VARCHAR(16) NOT NULL, 
	actor VARCHAR(320) NOT NULL, 
	at VARCHAR(32) NOT NULL, 
	CONSTRAINT memory_audit_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_memory_audit_tenant_id ON memory_audit (tenant_id);
GO
CREATE TABLE model_call_records (
	id VARCHAR(64) NOT NULL, 
	thread_id VARCHAR(64) NOT NULL, 
	run_id VARCHAR(64) NULL, 
	step VARCHAR(120) NOT NULL, 
	task VARCHAR(200) NULL, 
	kind VARCHAR(40) NOT NULL, 
	model_alias VARCHAR(120) NOT NULL, 
	calls INTEGER NOT NULL, 
	input_tokens BIGINT NOT NULL, 
	output_tokens BIGINT NOT NULL, 
	cost_micros BIGINT NOT NULL, 
	latency_ms INTEGER NULL, 
	request_hash VARCHAR(64) NULL, 
	response NVARCHAR(max) NULL, 
	created_at VARCHAR(40) NOT NULL, 
	CONSTRAINT model_call_records_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_model_call_records_thread_id ON model_call_records (thread_id);
GO
CREATE UNIQUE INDEX uq_model_call_replay ON model_call_records (thread_id, task, request_hash) WHERE task IS NOT NULL AND request_hash IS NOT NULL;
GO
CREATE TABLE review_assignments (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	review_id VARCHAR(200) NOT NULL, 
	assignee VARCHAR(320) NOT NULL, 
	assigned_by VARCHAR(320) NOT NULL, 
	assigned_at VARCHAR(32) NOT NULL, 
	CONSTRAINT review_assignments_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_review_assignments_review ON review_assignments (tenant_id, review_id, assigned_at);
GO
CREATE TABLE registry_skills (
	id VARCHAR(64) NOT NULL, 
	slug VARCHAR(64) NOT NULL, 
	owner_team VARCHAR(200) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	origin VARCHAR(16) NOT NULL, 
	version INTEGER NOT NULL, 
	published_version INTEGER NULL, 
	deprecated_reason VARCHAR(max) NULL, 
	created_at VARCHAR(32) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	updated_by VARCHAR(200) NOT NULL, 
	created_by VARCHAR(200) NOT NULL DEFAULT '', 
	published_loading VARCHAR(16) NULL, 
	CONSTRAINT registry_skills_pkey PRIMARY KEY (id), 
	CONSTRAINT registry_skills_slug_key UNIQUE (slug)
);
GO
CREATE TABLE task_assists (
	tenant_id VARCHAR(64) NOT NULL, 
	step_id VARCHAR(200) NOT NULL, 
	assist NVARCHAR(max) NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	CONSTRAINT task_assists_pkey PRIMARY KEY (tenant_id, step_id)
);
GO
CREATE TABLE task_types (
	tenant_id VARCHAR(64) NOT NULL, 
	id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NULL, 
	origin VARCHAR(16) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description VARCHAR(max) NOT NULL, 
	version INTEGER NOT NULL, 
	published_version INTEGER NULL, 
	copied_from NVARCHAR(max) NULL, 
	created_at VARCHAR(32) NOT NULL, 
	created_by VARCHAR(320) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	updated_by VARCHAR(320) NOT NULL, 
	CONSTRAINT task_types_pkey PRIMARY KEY (tenant_id, id)
);
GO
CREATE TABLE task_type_versions (
	tenant_id VARCHAR(64) NOT NULL, 
	type_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	record NVARCHAR(max) NOT NULL, 
	saved_at VARCHAR(32) NOT NULL, 
	saved_by VARCHAR(320) NOT NULL, 
	published_at VARCHAR(32) NULL, 
	published_by VARCHAR(320) NULL, 
	CONSTRAINT task_type_versions_pkey PRIMARY KEY (tenant_id, type_id, version)
);
GO
CREATE TABLE team_default_agents (
	tenant_id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	agent_id VARCHAR(64) NOT NULL, 
	updated_by VARCHAR(320) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	CONSTRAINT team_default_agents_pkey PRIMARY KEY (tenant_id, team_id)
);
GO
CREATE TABLE thread_budgets (
	thread_id VARCHAR(64) NOT NULL, 
	max_calls INTEGER NULL, 
	max_tokens BIGINT NULL, 
	max_cost_micros BIGINT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	CONSTRAINT thread_budgets_pkey PRIMARY KEY (thread_id)
);
GO
CREATE TABLE widget_mint_keys (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL DEFAULT 'local', 
	deployment_id VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	secret_hash VARCHAR(64) NOT NULL, 
	created_by VARCHAR(320) NOT NULL, 
	created_at VARCHAR(32) NOT NULL, 
	last_used_at VARCHAR(32) NULL, 
	revoked_at VARCHAR(32) NULL, 
	expires_at VARCHAR(32) NULL, 
	CONSTRAINT widget_mint_keys_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_widget_mint_keys_deployment_id ON widget_mint_keys (deployment_id);
GO
CREATE INDEX ix_widget_mint_keys_tenant_id ON widget_mint_keys (tenant_id);
GO
CREATE TABLE widget_mint_key_audit (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL DEFAULT 'local', 
	deployment_id VARCHAR(64) NOT NULL, 
	key_id VARCHAR(64) NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	actor VARCHAR(320) NOT NULL, 
	at VARCHAR(32) NOT NULL, 
	CONSTRAINT widget_mint_key_audit_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_widget_mint_key_audit_deployment_id ON widget_mint_key_audit (deployment_id);
GO
CREATE INDEX ix_widget_mint_key_audit_tenant_id ON widget_mint_key_audit (tenant_id);
GO
CREATE TABLE registry_widgets (
	id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL DEFAULT '', 
	version INTEGER NOT NULL, 
	published_version INTEGER NULL, 
	retired_reason VARCHAR(max) NULL, 
	created_at VARCHAR(32) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	updated_by VARCHAR(200) NOT NULL, 
	CONSTRAINT registry_widgets_pkey PRIMARY KEY (id)
);
GO
CREATE TABLE registry_workflows (
	id VARCHAR(64) NOT NULL, 
	team_id VARCHAR(64) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description VARCHAR(max) NOT NULL, 
	[trigger] VARCHAR(200) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	published_version INTEGER NULL, 
	draft NVARCHAR(max) NULL, 
	draft_saved_at VARCHAR(32) NULL, 
	draft_saved_by VARCHAR(200) NULL, 
	created_at VARCHAR(32) NOT NULL, 
	updated_at VARCHAR(32) NOT NULL, 
	CONSTRAINT registry_workflows_pkey PRIMARY KEY (id)
);
GO
CREATE TABLE registry_validations (
	id VARCHAR(64) NOT NULL, 
	workflow_id VARCHAR(64) NOT NULL, 
	ran_at VARCHAR(32) NOT NULL, 
	target VARCHAR(8) NOT NULL, 
	results NVARCHAR(max) NOT NULL, 
	summary NVARCHAR(max) NOT NULL, 
	CONSTRAINT registry_validations_pkey PRIMARY KEY (id)
);
GO
CREATE INDEX ix_registry_validations_workflow_id ON registry_validations (workflow_id);
GO
CREATE TABLE timers (
	thread_id VARCHAR(64) NOT NULL, 
	timer_id VARCHAR(200) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	node VARCHAR(64) NOT NULL, 
	interrupt_id VARCHAR(64) NULL, 
	due_at DATETIMEOFFSET NOT NULL, 
	fired_at DATETIMEOFFSET NULL, 
	cancelled_at DATETIMEOFFSET NULL, 
	owner VARCHAR(120) NULL, 
	claimed_generation BIGINT NULL, 
	claimed_at DATETIMEOFFSET NULL, 
	attempts INTEGER NOT NULL DEFAULT '0', 
	failed_at DATETIMEOFFSET NULL, 
	created_at DATETIMEOFFSET NOT NULL DEFAULT SYSDATETIMEOFFSET(), 
	CONSTRAINT timers_pkey PRIMARY KEY (thread_id, timer_id)
);
GO
CREATE INDEX ix_timers_due_open ON timers (due_at) WHERE fired_at IS NULL AND cancelled_at IS NULL AND failed_at IS NULL;
GO
CREATE TABLE registry_agent_versions (
	agent_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	spec NVARCHAR(max) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	note VARCHAR(max) NOT NULL, 
	changes NVARCHAR(max) NOT NULL, 
	saved_at VARCHAR(32) NOT NULL, 
	saved_by VARCHAR(200) NOT NULL, 
	published_at VARCHAR(32) NULL, 
	published_by VARCHAR(200) NULL, 
	review_id VARCHAR(64) NULL, 
	CONSTRAINT registry_agent_versions_pkey PRIMARY KEY (agent_id, version), 
	CONSTRAINT registry_agent_versions_agent_id_fkey FOREIGN KEY(agent_id) REFERENCES registry_agents (id) ON DELETE CASCADE
);
GO
CREATE TABLE graph_runs (
	id VARCHAR(64) NOT NULL, 
	thread_id VARCHAR(64) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	events NVARCHAR(max) NOT NULL, 
	input NVARCHAR(max) NULL, 
	created_at VARCHAR(32) NOT NULL, 
	finished_at VARCHAR(32) NULL, 
	tenant_id VARCHAR(64) NOT NULL DEFAULT 'local', 
	team_id VARCHAR(64) NULL, 
	CONSTRAINT graph_runs_pkey PRIMARY KEY (id), 
	CONSTRAINT graph_runs_thread_id_fkey FOREIGN KEY(thread_id) REFERENCES graph_threads (id)
);
GO
CREATE INDEX ix_graph_runs_tenant_id ON graph_runs (tenant_id);
GO
CREATE INDEX ix_graph_runs_thread_id ON graph_runs (thread_id);
GO
CREATE TABLE registry_guardrail_versions (
	guardrail_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	config NVARCHAR(max) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	note VARCHAR(max) NOT NULL, 
	saved_at VARCHAR(32) NOT NULL, 
	saved_by VARCHAR(200) NOT NULL, 
	published_at VARCHAR(32) NULL, 
	published_by VARCHAR(200) NULL, 
	review_id VARCHAR(64) NULL, 
	CONSTRAINT registry_guardrail_versions_pkey PRIMARY KEY (guardrail_id, version), 
	CONSTRAINT registry_guardrail_versions_guardrail_id_fkey FOREIGN KEY(guardrail_id) REFERENCES registry_guardrails (id) ON DELETE CASCADE
);
GO
CREATE TABLE registry_skill_versions (
	skill_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	content NVARCHAR(max) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	tokens INTEGER NOT NULL, 
	note VARCHAR(max) NOT NULL, 
	changes NVARCHAR(max) NOT NULL, 
	saved_at VARCHAR(32) NOT NULL, 
	saved_by VARCHAR(200) NOT NULL, 
	published_at VARCHAR(32) NULL, 
	published_by VARCHAR(200) NULL, 
	review_id VARCHAR(64) NULL, 
	CONSTRAINT registry_skill_versions_pkey PRIMARY KEY (skill_id, version), 
	CONSTRAINT registry_skill_versions_skill_id_fkey FOREIGN KEY(skill_id) REFERENCES registry_skills (id) ON DELETE CASCADE
);
GO
CREATE TABLE registry_widget_versions (
	widget_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	content NVARCHAR(max) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	changes NVARCHAR(max) NOT NULL, 
	saved_at VARCHAR(32) NOT NULL, 
	saved_by VARCHAR(200) NOT NULL, 
	published_at VARCHAR(32) NULL, 
	published_by VARCHAR(200) NULL, 
	review_id VARCHAR(64) NULL, 
	CONSTRAINT registry_widget_versions_pkey PRIMARY KEY (widget_id, version), 
	CONSTRAINT registry_widget_versions_widget_id_fkey FOREIGN KEY(widget_id) REFERENCES registry_widgets (id) ON DELETE CASCADE
);
GO
CREATE TABLE registry_workflow_versions (
	workflow_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	graph NVARCHAR(max) NOT NULL, 
	note VARCHAR(max) NOT NULL, 
	changes NVARCHAR(max) NOT NULL, 
	published_at VARCHAR(32) NOT NULL, 
	published_by VARCHAR(200) NOT NULL, 
	review_id VARCHAR(64) NULL, 
	CONSTRAINT registry_workflow_versions_pkey PRIMARY KEY (workflow_id, version), 
	CONSTRAINT registry_workflow_versions_workflow_id_fkey FOREIGN KEY(workflow_id) REFERENCES registry_workflows (id) ON DELETE CASCADE
);
GO
IF SCHEMA_ID(N'ops_security') IS NULL EXEC (N'CREATE SCHEMA ops_security AUTHORIZATION dbo');
GO
CREATE FUNCTION ops_security.agents_tenant_read (@tenant_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS visible WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64)) OR USER_NAME() = N'ops_runtime_system';
GO
CREATE FUNCTION ops_security.agents_tenant_write (@tenant_id VARCHAR(64))
RETURNS TABLE WITH SCHEMABINDING AS RETURN
SELECT 1 AS allowed WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS VARCHAR(64));
GO
CREATE SECURITY POLICY ops_security.engine_definitions_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.engine_definitions,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.engine_definitions AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.engine_definitions AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.engine_runs_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.engine_runs,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.engine_runs AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.engine_runs AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.engine_steps_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.engine_steps,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.engine_steps AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.engine_steps AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.engine_work_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.engine_work,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.engine_work AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.engine_work AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.registry_publish_requests_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.registry_publish_requests,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.registry_publish_requests AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.registry_publish_requests AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.cases_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.cases,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.cases AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.cases AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.case_events_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.case_events,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.case_events AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.case_events AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.thread_events_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.thread_events,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.thread_events AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.thread_events AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.graph_threads_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.graph_threads,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.graph_threads AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.graph_threads AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.mailboxes_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.mailboxes,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.mailboxes AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.mailboxes AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.review_decisions_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.review_decisions,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.review_decisions AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.review_decisions AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.review_approvals_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.review_approvals,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.review_approvals AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.review_approvals AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.service_events_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.service_events,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.service_events AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.service_events AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.trigger_events_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.trigger_events,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.trigger_events AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.trigger_events AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.widget_deployments_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.widget_deployments,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.widget_deployments AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.widget_deployments AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.case_types_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.case_types,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.case_types AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.case_types AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.case_type_versions_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.case_type_versions,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.case_type_versions AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.case_type_versions AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.poll_cursors_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.poll_cursors,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.poll_cursors AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.poll_cursors AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.chat_attachments_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.chat_attachments,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.chat_attachments AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.chat_attachments AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.chat_search_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.chat_search,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.chat_search AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.chat_search AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.agent_memories_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.agent_memories,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.agent_memories AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.agent_memories AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.memory_audit_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.memory_audit,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.memory_audit AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.memory_audit AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.review_assignments_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.review_assignments,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.review_assignments AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.review_assignments AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.task_assists_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.task_assists,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.task_assists AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.task_assists AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.task_types_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.task_types,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.task_types AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.task_types AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.task_type_versions_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.task_type_versions,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.task_type_versions AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.task_type_versions AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.team_default_agents_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.team_default_agents,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.team_default_agents AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.team_default_agents AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.widget_mint_keys_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.widget_mint_keys,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.widget_mint_keys AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.widget_mint_keys AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.widget_mint_key_audit_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.widget_mint_key_audit,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.widget_mint_key_audit AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.widget_mint_key_audit AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE SECURITY POLICY ops_security.graph_runs_tenant
    ADD FILTER PREDICATE ops_security.agents_tenant_read(tenant_id) ON dbo.graph_runs,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.graph_runs AFTER INSERT,
    ADD BLOCK PREDICATE ops_security.agents_tenant_write(tenant_id) ON dbo.graph_runs AFTER UPDATE
    WITH (STATE = ON, SCHEMABINDING = ON);
GO
CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
GO
INSERT INTO alembic_version (version_num) VALUES ('0072_memories_system_tenants');
GO
