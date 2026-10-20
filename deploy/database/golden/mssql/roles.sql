-- Ops AI schema for SQL Server, compiled from the store models by deploy/database/mssql.py; do not edit.
-- Run once per server in master by a server administrator, with each password as a sqlcmd variable:
--   sqlcmd -b -d master -i roles.sql -v database=ops ops_migrator_password=... ops_agents_runtime_password=... ops_tools_runtime_password=... ops_models_runtime_password=... ops_kb_runtime_password=... ops_platform_runtime_password=... ops_files_runtime_password=... ops_documents_runtime_password=...
-- Runs again safely: an existing login gets the password given, an existing database is left as it is.
-- The database: collation Latin1_General_100_BIN2_UTF8 (VARCHAR holds UTF-8, comparisons are binary like PostgreSQL), and
-- READ_COMMITTED_SNAPSHOT on so readers never block writers. bundle.sql refuses a database without both.
-- Each runtime login's database user, with DML on its own tables only, is made by grants.sql.

IF SUSER_ID(N'ops_migrator') IS NULL CREATE LOGIN ops_migrator WITH PASSWORD = N'$(ops_migrator_password)', CHECK_POLICY = ON;
ELSE ALTER LOGIN ops_migrator WITH PASSWORD = N'$(ops_migrator_password)';
GO
IF SUSER_ID(N'ops_agents_runtime') IS NULL CREATE LOGIN ops_agents_runtime WITH PASSWORD = N'$(ops_agents_runtime_password)', CHECK_POLICY = ON;
ELSE ALTER LOGIN ops_agents_runtime WITH PASSWORD = N'$(ops_agents_runtime_password)';
GO
IF SUSER_ID(N'ops_tools_runtime') IS NULL CREATE LOGIN ops_tools_runtime WITH PASSWORD = N'$(ops_tools_runtime_password)', CHECK_POLICY = ON;
ELSE ALTER LOGIN ops_tools_runtime WITH PASSWORD = N'$(ops_tools_runtime_password)';
GO
IF SUSER_ID(N'ops_models_runtime') IS NULL CREATE LOGIN ops_models_runtime WITH PASSWORD = N'$(ops_models_runtime_password)', CHECK_POLICY = ON;
ELSE ALTER LOGIN ops_models_runtime WITH PASSWORD = N'$(ops_models_runtime_password)';
GO
IF SUSER_ID(N'ops_kb_runtime') IS NULL CREATE LOGIN ops_kb_runtime WITH PASSWORD = N'$(ops_kb_runtime_password)', CHECK_POLICY = ON;
ELSE ALTER LOGIN ops_kb_runtime WITH PASSWORD = N'$(ops_kb_runtime_password)';
GO
IF SUSER_ID(N'ops_platform_runtime') IS NULL CREATE LOGIN ops_platform_runtime WITH PASSWORD = N'$(ops_platform_runtime_password)', CHECK_POLICY = ON;
ELSE ALTER LOGIN ops_platform_runtime WITH PASSWORD = N'$(ops_platform_runtime_password)';
GO
IF SUSER_ID(N'ops_files_runtime') IS NULL CREATE LOGIN ops_files_runtime WITH PASSWORD = N'$(ops_files_runtime_password)', CHECK_POLICY = ON;
ELSE ALTER LOGIN ops_files_runtime WITH PASSWORD = N'$(ops_files_runtime_password)';
GO
IF SUSER_ID(N'ops_documents_runtime') IS NULL CREATE LOGIN ops_documents_runtime WITH PASSWORD = N'$(ops_documents_runtime_password)', CHECK_POLICY = ON;
ELSE ALTER LOGIN ops_documents_runtime WITH PASSWORD = N'$(ops_documents_runtime_password)';
GO
IF DB_ID(N'$(database)') IS NULL CREATE DATABASE [$(database)] COLLATE Latin1_General_100_BIN2_UTF8;
GO
ALTER DATABASE [$(database)] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
GO
-- The migrator owns the database (it is dbo there) and applies the bundle and every upgrade; it is not a
-- server administrator. Security policies apply to it too.
ALTER AUTHORIZATION ON DATABASE::[$(database)] TO ops_migrator;
GO
