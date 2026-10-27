# syntax=docker/dockerfile:1
# The install container of the behind-a-mirror lane. Built on a connected machine, run on a network with no way out.
ARG IMAGE_REGISTRY=
FROM ${IMAGE_REGISTRY}node:22-bookworm-slim AS node-image
FROM ${IMAGE_REGISTRY}ghcr.io/astral-sh/uv:0.8.4 AS uv-image

FROM ${IMAGE_REGISTRY}python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl tar \
 && apt-get clean && find /var/lib/apt/lists -type f -delete
COPY --from=uv-image /uv /usr/local/bin/uv
# Node's /usr/local merges into the Python image's, so npm and corepack keep their relative links.
COPY --from=node-image /usr/local/ /usr/local/
ENV UV_PROJECT_ENVIRONMENT=/work/.venv
WORKDIR /work
