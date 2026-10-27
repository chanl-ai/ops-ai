# syntax=docker/dockerfile:1
# Workspace image for .devcontainer: Python 3.12 and uv at the versions the repo pins
# (requires-python >=3.12,<3.13; uv 0.8.4 as deploy/fly/Dockerfile). Node 22 and pnpm are installed
# below (package.json packageManager). Playwright browsers stay off unless OPS_PLAYWRIGHT=1 in
# post-create.
# Behind a company mirror (docs/deploy/install.md, "Behind a company mirror"): IMAGE_REGISTRY prefixes the base images
# (end it with a slash), and the other arguments point each download at the mirror. Empty keeps the public address.
ARG IMAGE_REGISTRY=
FROM ${IMAGE_REGISTRY}node:22.23.4-bookworm-slim AS node-image
FROM ${IMAGE_REGISTRY}ghcr.io/astral-sh/uv:0.8.4 AS uv-image

FROM ${IMAGE_REGISTRY}mcr.microsoft.com/devcontainers/python:1-3.12-bookworm
ARG APT_MIRROR=
ARG UV_DEFAULT_INDEX=
ARG NPM_CONFIG_REGISTRY=

COPY --from=uv-image /uv /usr/local/bin/uv

USER root
# The base image's Yarn apt source is unsigned; drop it so apt-get update can run.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
 && if [ -n "$APT_MIRROR" ]; then sed -i "s|http://deb.debian.org|$APT_MIRROR|g; s|http://security.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; fi \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      make \
      netcat-openbsd \
      openssl \
      lsof \
      socat \
      tesseract-ocr \
      tesseract-ocr-eng \
 && apt-get clean && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir --break-system-packages ${UV_DEFAULT_INDEX:+--index-url $UV_DEFAULT_INDEX} 'fastapi>=0.115' 'uvicorn[standard]>=0.30' 'pydantic>=2'

ENV UV_PYTHON_DOWNLOADS=never UV_PYTHON=/usr/local/bin/python3.12
# Node 22 comes from the Node image (no download from nodejs.org), pnpm at the version package.json pins from the
# npm registry in NPM_CONFIG_REGISTRY.
COPY --from=node-image /usr/local/ /usr/local/
RUN npm install -g ${NPM_CONFIG_REGISTRY:+--registry $NPM_CONFIG_REGISTRY} pnpm@10.34.5
USER vscode
WORKDIR /workspaces/ops-ai
