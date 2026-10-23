-- Ops AI schema for SQL Server, compiled from the store models by deploy/database/mssql.py; do not edit.
-- Run as ops_migrator in the database after the bundle and after each upgrade; every statement runs again.
-- Each service's user: SELECT, INSERT, UPDATE, DELETE on its own tables and SELECT on its version table.
-- No other permission, so it can create, alter or drop nothing, read no other service's tables, and
-- every security policy applies to it. A chain's user may also impersonate that chain's system user (no
-- login), which reads every tenant's rows of the tables and columns granted to it below, as on PostgreSQL.
-- agents-service
IF USER_ID(N'ops_agents_runtime') IS NULL CREATE USER ops_agents_runtime FOR LOGIN ops_agents_runtime WITH DEFAULT_SCHEMA = dbo;
GO
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.engine_definitions TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.engine_runs TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.engine_steps TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.engine_work TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.registry_agents TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.registry_publish_requests TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.background_heartbeats TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.background_jobs TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.cases TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.case_events TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.thread_leases TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.thread_events TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.graph_threads TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.graph_versions TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.mailboxes TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.review_decisions TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.review_approvals TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.service_events TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.trigger_events TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.widget_deployments TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.case_types TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.case_type_versions TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.poll_cursors TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.deployments TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.channel_messages TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.channel_cursors TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.thread_inbox TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.channel_files TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.chat_attachments TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.chat_search TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.registry_guardrails TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.agent_memories TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.memory_audit TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.model_call_records TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.review_assignments TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.registry_skills TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.task_assists TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.task_types TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.task_type_versions TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.team_default_agents TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.thread_budgets TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.widget_mint_keys TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.widget_mint_key_audit TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.registry_widgets TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.registry_workflows TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.registry_validations TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.timers TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.registry_agent_versions TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.graph_runs TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.registry_guardrail_versions TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.registry_skill_versions TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.registry_widget_versions TO ops_agents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.registry_workflow_versions TO ops_agents_runtime;
GRANT SELECT ON dbo.alembic_version TO ops_agents_runtime;
GO
IF USER_ID(N'ops_runtime_system') IS NULL CREATE USER ops_runtime_system WITHOUT LOGIN;
GO
GRANT SELECT ON dbo.graph_threads TO ops_runtime_system;
GRANT SELECT ON dbo.graph_runs TO ops_runtime_system;
GRANT SELECT ON dbo.thread_events TO ops_runtime_system;
GRANT SELECT ON dbo.review_decisions TO ops_runtime_system;
GRANT SELECT ON dbo.review_approvals TO ops_runtime_system;
GRANT SELECT ON dbo.engine_definitions TO ops_runtime_system;
GRANT SELECT, UPDATE ON dbo.engine_work TO ops_runtime_system;
GRANT SELECT ON dbo.agent_memories (tenant_id) TO ops_runtime_system;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.background_heartbeats TO ops_runtime_system;
GRANT SELECT ON dbo.background_jobs TO ops_runtime_system;
GRANT IMPERSONATE ON USER::ops_runtime_system TO ops_agents_runtime;
GO
-- tools-service
IF USER_ID(N'ops_tools_runtime') IS NULL CREATE USER ops_tools_runtime FOR LOGIN ops_tools_runtime WITH DEFAULT_SCHEMA = dbo;
GO
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.gateway_calls TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.gateway_fences TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.tool_modules TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.service_outbox TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.connections TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.oauth_states TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.connection_audit TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.egress_hosts TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.egress_ranges TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.egress_audit TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.operation_mocks TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.operation_rate_windows TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.tool_secrets TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.secret_audit TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.send_policies TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.send_checks TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.module_operations TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.module_versions TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.module_approvals TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.module_egress_hosts TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.connection_environments TO ops_tools_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.connection_tokens TO ops_tools_runtime;
GRANT SELECT ON dbo.alembic_version_tools TO ops_tools_runtime;
GO
-- models-service
IF USER_ID(N'ops_models_runtime') IS NULL CREATE USER ops_models_runtime FOR LOGIN ops_models_runtime WITH DEFAULT_SCHEMA = dbo;
GO
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.provider_connections TO ops_models_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.model_keys TO ops_models_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.model_key_tenants TO ops_models_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.model_call_log TO ops_models_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.model_aliases TO ops_models_runtime;
GRANT SELECT ON dbo.alembic_version_models TO ops_models_runtime;
GO
-- kb-service
IF USER_ID(N'ops_kb_runtime') IS NULL CREATE USER ops_kb_runtime FOR LOGIN ops_kb_runtime WITH DEFAULT_SCHEMA = dbo;
GO
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.kb_bases TO ops_kb_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.kb_sources TO ops_kb_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.kb_retired_bases TO ops_kb_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.kb_changes TO ops_kb_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.kb_base_sources TO ops_kb_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.kb_items TO ops_kb_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.kb_runs TO ops_kb_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.kb_item_versions TO ops_kb_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.kb_chunks TO ops_kb_runtime;
GRANT SELECT ON dbo.alembic_version_kb TO ops_kb_runtime;
GO
-- platform-service
IF USER_ID(N'ops_platform_runtime') IS NULL CREATE USER ops_platform_runtime FOR LOGIN ops_platform_runtime WITH DEFAULT_SCHEMA = dbo;
GO
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.tenants TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.signin_email_failures TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.teams TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.users TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.roles TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.policies TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.members TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.api_keys TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.sessions TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.audit_entries TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.role_permissions TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.role_assignments TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.signin_providers TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.password_credentials TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.password_resets TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.signin_lockouts TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.signin_domains TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.signin_identities TO ops_platform_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.signin_flows TO ops_platform_runtime;
GRANT SELECT ON dbo.alembic_version_platform TO ops_platform_runtime;
GO
-- files-service
IF USER_ID(N'ops_files_runtime') IS NULL CREATE USER ops_files_runtime FOR LOGIN ops_files_runtime WITH DEFAULT_SCHEMA = dbo;
GO
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.files TO ops_files_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.files_outbox TO ops_files_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.file_blobs TO ops_files_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.file_versions TO ops_files_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.file_references TO ops_files_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.file_idempotency TO ops_files_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.file_legal_holds TO ops_files_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.file_read_requests TO ops_files_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.storage_settings TO ops_files_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.storage_credentials TO ops_files_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.storage_settings_audit TO ops_files_runtime;
GRANT SELECT ON dbo.alembic_version_files TO ops_files_runtime;
GO
IF USER_ID(N'ops_files_system') IS NULL CREATE USER ops_files_system WITHOUT LOGIN;
GO
GRANT SELECT, UPDATE, DELETE ON dbo.files_outbox TO ops_files_system;
GRANT IMPERSONATE ON USER::ops_files_system TO ops_files_runtime;
GO
-- documents-service
IF USER_ID(N'ops_documents_runtime') IS NULL CREATE USER ops_documents_runtime FOR LOGIN ops_documents_runtime WITH DEFAULT_SCHEMA = dbo;
GO
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.document_types TO ops_documents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.document_type_versions TO ops_documents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.document_type_samples TO ops_documents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.document_type_tests TO ops_documents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.document_type_examples TO ops_documents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.extractions TO ops_documents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.documents_outbox TO ops_documents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.extraction_corrections TO ops_documents_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.documents_layouts TO ops_documents_runtime;
GRANT SELECT ON dbo.alembic_version_documents TO ops_documents_runtime;
GO
IF USER_ID(N'ops_documents_system') IS NULL CREATE USER ops_documents_system WITHOUT LOGIN;
GO
GRANT SELECT, UPDATE, DELETE ON dbo.documents_outbox TO ops_documents_system;
GRANT SELECT ON dbo.extractions TO ops_documents_system;
GRANT SELECT ON dbo.document_type_tests TO ops_documents_system;
GRANT IMPERSONATE ON USER::ops_documents_system TO ops_documents_runtime;
GO
