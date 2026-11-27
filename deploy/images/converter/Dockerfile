# The converter worker: draws Word files and decks as PDF with LibreOffice (MPL-2.0) so documents-service can show them
# as pages. Runs with no network access in every target (docs/deploy/converter.md). Build from this folder:
#   docker build -t ops-ai/converter:dev deploy/images/converter
# APT_MIRROR and IMAGE_REGISTRY follow the same rules as deploy/fly/Dockerfile (docs/deploy/install.md, company mirror).
ARG IMAGE_REGISTRY=
FROM ${IMAGE_REGISTRY}python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
ARG APT_MIRROR=
# Carlito and Caladea are metric-compatible with Calibri and Cambria, so a Word file keeps its line breaks and pages.
RUN if [ -n "$APT_MIRROR" ]; then sed -i "s|http://deb.debian.org|$APT_MIRROR|g; s|http://security.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; fi \
 && apt-get update \
 && apt-get install -y --no-install-recommends libreoffice-writer libreoffice-impress \
      fonts-liberation fonts-dejavu-core fonts-crosextra-carlito fonts-crosextra-caladea fonts-noto-core \
 && apt-get clean && find /var/lib/apt/lists -type f -delete
RUN useradd --system --uid 10001 --home-dir /home/ops --create-home ops
COPY server.py /app/server.py
USER ops
WORKDIR /app
ENV OPS_CONVERTER_PORT=8770 OPS_CONVERTER_HOST=0.0.0.0
EXPOSE 8770
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8770/health', timeout=2).status == 200 else 1)"]
CMD ["python", "/app/server.py"]
