# syntax=docker/dockerfile:1
# Every Ops AI image, built from the repo root. Stages:
#   python-base       the Python workspace (every service's dependencies and source); shared by every service image
#   platform, agents, tools, models, kb, files, documents
#                     one image per service: python-base plus its command, port, health check and a non-root user;
#                     the workflow worker is the agents image run with `python -m ops_agents.api.worker`
#   console           the console, built once with placeholder URLs that its start script swaps for the container's
#   opa, proxy        tools-service's policy engine with the policy built in; the one origin in front (Caddy)
#   runtime           Fly's one image running everything under deploy/host/ops_host.py (kept last: Fly builds it)
# Per-service:  docker build -f deploy/fly/Dockerfile --target agents -t ops-ai/agents .   (deploy/compose/app.yaml)
# Fly:          docker build -f deploy/fly/Dockerfile --build-arg OPS_PUBLIC_ORIGIN=<origin> .

# The console's JavaScript is built on the build machine's own platform: `next build` under emulation (an arm64 laptop
# building for amd64 Fly machines) dies with a segfault. Its output is platform-free apart from sharp, which only
# next/image's optimizer loads; the console does not use it, so the console stage drops it.
FROM --platform=$BUILDPLATFORM node:22-bookworm-slim AS console-deps
# package.json names pnpm@10, which corepack rejects as not a full version.
RUN npm install -g pnpm@10.19.0
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/console/package.json apps/console/
COPY apps/embed/package.json apps/embed/
COPY packages/usecase-runner/package.json packages/usecase-runner/
RUN pnpm install --frozen-lockfile --filter @ops-ai/console...
COPY apps/console apps/console
# What's new and Coming next, read by next.config.ts into the build.
COPY changelog changelog
COPY roadmap.json roadmap.json
ENV NEXT_TELEMETRY_DISABLED=1 NODE_OPTIONS=--max-old-space-size=3072

# Fly's console: service URLs baked for the one public origin it serves, every area through Caddy on that origin;
# models-service has no browser caller and is not routed.
FROM console-deps AS console-fly
ARG OPS_PUBLIC_ORIGIN
RUN test -n "$OPS_PUBLIC_ORIGIN" || { echo "build with --build-arg OPS_PUBLIC_ORIGIN=https://<host>"; exit 1; }
ENV NEXT_PUBLIC_AUTH_PROVIDER=platform \
    NEXT_PUBLIC_OPS_PLATFORM_API_URL=${OPS_PUBLIC_ORIGIN}/api/platform \
    NEXT_PUBLIC_OPS_CHAT_API_URL=${OPS_PUBLIC_ORIGIN}/api/agents \
    NEXT_PUBLIC_OPS_CASES_API_URL=${OPS_PUBLIC_ORIGIN}/api/agents \
    NEXT_PUBLIC_OPS_REGISTRY_API_URL=${OPS_PUBLIC_ORIGIN}/api/agents \
    NEXT_PUBLIC_OPS_TOOLS_API_URL=${OPS_PUBLIC_ORIGIN}/api/tools \
    NEXT_PUBLIC_OPS_KNOWLEDGE_API_URL=${OPS_PUBLIC_ORIGIN}/api/kb \
    NEXT_PUBLIC_OPS_FILES_API_URL=${OPS_PUBLIC_ORIGIN}/api/files \
    NEXT_PUBLIC_OPS_DOCUMENTS_API_URL=${OPS_PUBLIC_ORIGIN}/api/documents
# The version What's new shows (next.config.ts): the build has no .git, so stg_deploy.sh passes the tag and commit.
ARG OPS_VERSION=
ARG OPS_COMMIT=
RUN pnpm --filter @ops-ai/console exec next build

# The portable console: every URL variable the console reads is set to its placeholder (console-build.ts), so the
# build takes the HTTP path for every area; deploy/images/console-start.mjs writes the real URLs in at start.
FROM console-deps AS console-build
ENV NEXT_PUBLIC_AUTH_PROVIDER=platform \
    NEXT_PUBLIC_OPS_PLATFORM_API_URL=http://ph-next-public-ops-platform-api-url.invalid \
    NEXT_PUBLIC_OPS_CHAT_API_URL=http://ph-next-public-ops-chat-api-url.invalid \
    NEXT_PUBLIC_OPS_CASES_API_URL=http://ph-next-public-ops-cases-api-url.invalid \
    NEXT_PUBLIC_OPS_REGISTRY_API_URL=http://ph-next-public-ops-registry-api-url.invalid \
    NEXT_PUBLIC_OPS_TOOLS_API_URL=http://ph-next-public-ops-tools-api-url.invalid \
    NEXT_PUBLIC_OPS_KNOWLEDGE_API_URL=http://ph-next-public-ops-knowledge-api-url.invalid \
    NEXT_PUBLIC_OPS_FILES_API_URL=http://ph-next-public-ops-files-api-url.invalid \
    NEXT_PUBLIC_OPS_DOCUMENTS_API_URL=http://ph-next-public-ops-documents-api-url.invalid \
    OPS_CONSOLE_STANDALONE=1
ARG OPS_VERSION=
ARG OPS_COMMIT=
RUN pnpm --filter @ops-ai/console exec next build

FROM node:22-bookworm-slim AS console
WORKDIR /app
# The traced server and the static assets it serves; .next-pristine stays as built and each start copies it to .next.
COPY --from=console-build /app/apps/console/.next/standalone ./
COPY --from=console-build /app/apps/console/.next/static apps/console/.next-pristine/static
RUN mv apps/console/.next/* apps/console/.next-pristine/ && rmdir apps/console/.next \
 && find /app/node_modules -maxdepth 3 \( -name 'sharp*' -o -name '@img+sharp*' \) -exec rm -rf {} +
COPY packages/usecase-runner/src/console-build.ts packages/usecase-runner/src/console-build.ts
COPY deploy/images/console-start.mjs deploy/images/console-start.mjs
RUN useradd --system --uid 10001 --home-dir /app ops && chown -R ops:ops /app/apps/console
USER ops
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3016
EXPOSE 3016
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3016/login').then(r=>process.exit(r.ok?0:1),()=>process.exit(1))"]
CMD ["node", "--experimental-strip-types", "--no-warnings", "/app/deploy/images/console-start.mjs"]

FROM python:3.12-slim-bookworm AS python-base
# tesseract for scanned pages in knowledge sources and documents (ops_ingest[ocr]).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates tesseract-ocr tesseract-ocr-eng \
 && apt-get clean && find /var/lib/apt/lists -type f -delete
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv
WORKDIR /app
# Editable workspace installs: settings find each service's seed and policy files under the repo tree.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PYTHON=/usr/local/bin/python3.12
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY services services
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# runner-service's CPython for WASI (c-531), pinned by SHA-256 in settings: fetched at build, so no machine fetches it
# when it starts.
RUN python -m ops_runner.fetch

# What every service image adds: the deploy scripts, a non-root user owning /data (files and knowledge bytes), and the
# listen address every container needs so the others reach it.
FROM python-base AS service
COPY deploy deploy
# The runner writes wasmtime's compiled-module cache beside its Python build, so the service user owns that folder.
RUN useradd --system --uid 10001 --home-dir /app ops && mkdir -p /data && chown ops:ops /data \
 && chown -R ops:ops /app/.data/runner
USER ops
ENV OPS_BIND_HOST=0.0.0.0 OPS_ENVIRONMENT=production OPS_AUTH_MODE=platform
ENTRYPOINT ["/app/deploy/images/entrypoint.sh"]

FROM service AS platform
EXPOSE 8710 8711
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 CMD ["python", "/app/deploy/images/healthcheck.py", "http://127.0.0.1:8710/v1/health"]
CMD ["python", "-m", "ops_platform"]

# The workflow worker runs from this image too: command `python -m ops_agents.api.worker`, health check
# `python /app/deploy/images/healthcheck.py db` (it serves no port).
FROM service AS agents
EXPOSE 8700
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 CMD ["python", "/app/deploy/images/healthcheck.py", "http://127.0.0.1:8700/health"]
CMD ["python", "-m", "ops_agents.api"]

FROM service AS tools
EXPOSE 8720
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 CMD ["python", "/app/deploy/images/healthcheck.py", "http://127.0.0.1:8720/health"]
CMD ["python", "-m", "ops_tools"]

FROM service AS models
EXPOSE 8730
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 CMD ["python", "/app/deploy/images/healthcheck.py", "http://127.0.0.1:8730/health"]
CMD ["python", "-m", "ops_models"]

FROM service AS kb
EXPOSE 8740
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 CMD ["python", "/app/deploy/images/healthcheck.py", "http://127.0.0.1:8740/health"]
CMD ["python", "-m", "ops_kb"]

FROM service AS files
EXPOSE 8750
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 CMD ["python", "/app/deploy/images/healthcheck.py", "http://127.0.0.1:8750/health"]
CMD ["python", "-m", "ops_files"]

FROM service AS documents
EXPOSE 8760
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 CMD ["python", "/app/deploy/images/healthcheck.py", "http://127.0.0.1:8760/health"]
CMD ["python", "-m", "ops_documents"]

# Code tools' functions (c-531): Python on WASM with no network; tools-service is its only caller.
FROM service AS runner
EXPOSE 8770
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 CMD ["python", "/app/deploy/images/healthcheck.py", "http://127.0.0.1:8770/health"]
CMD ["python", "-m", "ops_runner"]

# tools-service's policy engine with its policy built in, so an install needs no copy of the repo.
FROM openpolicyagent/opa:1.21.1-static AS opa
COPY services/tools-service/policy /policy
USER 10001
EXPOSE 8181
CMD ["run", "--server", "--addr", "0.0.0.0:8181", "--log-level", "error", "/policy"]

# The one origin in front of the services (deploy/fly/Caddyfile, each upstream from OPS_UPSTREAM_*).
FROM caddy:2.10.2 AS proxy
COPY deploy/fly/Caddyfile /etc/caddy/Caddyfile
# The image gives caddy a file capability to bind ports below 1024; the proxy listens on 8080, and a binary with file
# capabilities will not start where every capability is dropped (Kubernetes' drop ALL), so it is removed.
RUN apk add --no-cache libcap && setcap -r /usr/bin/caddy && apk del libcap \
 && adduser -D -u 10001 ops && chown -R ops /config /data
USER ops
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/api/platform/v1/health"]

# SQL Server tooling (c-345): the workspace with Microsoft's ODBC Driver 18 and sqlcmd, so deploy/database/mssql_live.py
# installs and compares the SQL Server bundle from Linux and no driver goes on a laptop.
FROM python-base AS test-mssql
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl gnupg \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
      > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 mssql-tools18 unixodbc \
 && apt-get clean && find /var/lib/apt/lists -type f -delete
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen
COPY deploy deploy

# The DBA's PostgreSQL scripts for this commit (deploy/database/schema.py ddl: roles.sql, bundle.sql, grants.sql,
# manifest.json), so an install from a clone or registry needs no uv, pg_dump or scratch server of its own (install.sh
# --db-mode dba copies /db/postgres out). The chains migrate a throwaway PostgreSQL 17 inside the build, on the build
# machine's own platform: the SQL is the same for every platform, and migrating under emulation only costs time.
# uv for the build machine's platform: a plain COPY --from an image takes the target's, which runs under emulation and
# fetches that platform's Python.
FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:0.8.4 AS uv-build

FROM --platform=$BUILDPLATFORM postgres:17-bookworm AS db-scripts-build
COPY --from=uv-build /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_PYTHON_INSTALL_DIR=/opt/uv-python
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY services services
RUN --mount=type=cache,target=/root/.cache/uv uv python install 3.12 && uv sync --frozen --no-dev --python 3.12 \
 && chmod -R a+rX /opt/uv-python
COPY deploy deploy
RUN mkdir -p /out/postgres && chown -R postgres /out
USER postgres
ARG OPS_COMMIT=unversioned
ENV PYTHONDONTWRITEBYTECODE=1 OPS_COMMIT=$OPS_COMMIT
RUN initdb -D /tmp/pg -A trust -U postgres >/dev/null \
 && pg_ctl -D /tmp/pg -o "-c listen_addresses=127.0.0.1 -k /tmp" -w start >/dev/null \
 && /app/.venv/bin/python deploy/database/schema.py ddl --server postgresql://postgres@127.0.0.1:5432/postgres \
      --ref . --out /out/postgres >/dev/null \
 && pg_ctl -D /tmp/pg -m fast -w stop >/dev/null

FROM scratch AS db-scripts
COPY --from=db-scripts-build /out /db

FROM python-base AS runtime
# libstdc++ for node.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libstdc++6 \
 && apt-get clean && find /var/lib/apt/lists -type f -delete
COPY --from=caddy:2.10.2 /usr/bin/caddy /usr/local/bin/caddy
COPY --from=openpolicyagent/opa:1.21.1-static /opa /usr/local/bin/opa
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=console-fly /app/node_modules node_modules
COPY --from=console-fly /app/apps/console apps/console
COPY deploy deploy
ENV NODE_ENV=production
EXPOSE 8080
ENTRYPOINT ["/app/deploy/fly/entrypoint.sh"]
