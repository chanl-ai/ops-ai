# syntax=docker/dockerfile:1
# The install container of the behind-a-mirror lane. Built on a connected machine, run on a network with no way out.
ARG IMAGE_REGISTRY=
FROM ${IMAGE_REGISTRY}node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS node-image
FROM ${IMAGE_REGISTRY}ghcr.io/astral-sh/uv:0.8.4@sha256:40775a79214294fb51d097c9117592f193bcfdfc634f4daa0e169ee965b10ef0 AS uv-image

FROM ${IMAGE_REGISTRY}python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl tar \
 && apt-get clean && find /var/lib/apt/lists -type f -delete
COPY --from=uv-image /uv /usr/local/bin/uv
# Node's /usr/local merges into the Python image's, so npm and corepack keep their relative links.
COPY --from=node-image /usr/local/ /usr/local/
ENV UV_PROJECT_ENVIRONMENT=/work/.venv
WORKDIR /work
