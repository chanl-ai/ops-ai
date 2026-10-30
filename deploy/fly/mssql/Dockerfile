# SQL Server 2025 Developer edition with Full-Text Search (c-563), which the stock image leaves out: memory search uses
# CONTAINSTABLE where the server has it and counts words where it does not, and the test machine proves the first.
# Installing mssql-server-fts brings the mssql-server build it was released with.
FROM mcr.microsoft.com/mssql/server:2025-latest
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://packages.microsoft.com/config/ubuntu/24.04/mssql-server-2025.list \
      -o /etc/apt/sources.list.d/mssql-server-2025.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends mssql-server-fts \
 && apt-get purge -y curl && apt-get autoremove -y && apt-get clean && rm -rf /var/lib/apt/lists/*
USER mssql
