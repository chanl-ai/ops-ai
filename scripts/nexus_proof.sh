#!/usr/bin/env bash
# Proves `make install-cli` against a real Sonatype Nexus Repository, then the wheelhouse upload.
#
#   scripts/nexus_proof.sh               (make nexus-proof)
#   NEXUS_IMAGE=sonatype/nexus3:3.70.4 NEXUS_PORT=8081 scripts/nexus_proof.sh   another image, e.g. one without a licence gate
#
# Running this script accepts Sonatype's Community Edition End User License Agreement (the link is in GET
# /service/rest/v1/system/eula) on behalf of whoever runs it, through the REST API, as Sonatype documents for CE.
#   NEXUS_KEEP=1 leaves the Nexus container running afterwards, for looking at a failure.
#
# 1. Nexus runs with a PyPI proxy of pypi.org, a hosted PyPI repository and a group over both.
# 2. A python:3.12-slim container on a network with no route out except to Nexus installs the command from the group,
#    once with pip and once with uv.
# 3. The wheelhouse is built here, uploaded to the hosted repository with twine, the proxy is turned off, and a fresh
#    container installs from the hosted repository alone.
# The generated admin password is read from the container and never printed. Everything it starts is removed at the end.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE=${NEXUS_IMAGE:-sonatype/nexus3}
PORT=${NEXUS_PORT:-8081}
NAME=ops-nexus-proof
NET=ops-nexus-proof-net
PY=python:3.12-slim
BASE=http://127.0.0.1:$PORT/service/rest/v1
GROUP=http://$NAME:8081/repository/pypi-group/simple/
HOSTED_INDEX=http://$NAME:8081/repository/pypi-hosted/simple/
WHEELS=$(mktemp -d)

say() { printf 'nexus-proof: %s\n' "$*"; }
cleanup() {
  [ -n "${NEXUS_KEEP:-}" ] && { echo "nexus-proof: left $NAME running (NEXUS_KEEP)"; return; }
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$WHEELS"
}
trap cleanup EXIT
cleanup_first() { docker rm -f "$NAME" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
cleanup_first

docker network create --internal "$NET" >/dev/null
# amd64 is the only architecture Nexus publishes; Docker emulates it on Apple silicon.
docker run -d --name "$NAME" --platform linux/amd64 -p "127.0.0.1:$PORT:8081" "$IMAGE" >/dev/null
docker network connect --alias "$NAME" "$NET" "$NAME"

say "waiting for Nexus to start (the first start takes a few minutes)"
for _ in $(seq 1 180); do
  curl -fsS "$BASE/status/writable" >/dev/null 2>&1 && break
  sleep 5
done
curl -fsS "$BASE/status/writable" >/dev/null || { echo "nexus-proof: Nexus did not become ready" >&2; docker logs --tail 20 "$NAME" >&2; exit 1; }

for _ in $(seq 1 60); do
  PASSWORD=$(docker exec "$NAME" cat /nexus-data/admin.password 2>/dev/null || true)
  [ -n "$PASSWORD" ] && break
  sleep 2
done
[ -n "$PASSWORD" ] || { echo "nexus-proof: no generated admin password found" >&2; exit 1; }
api() { curl -fsS -u "admin:$PASSWORD" -H 'Content-Type: application/json' "$@"; }

# Community Edition refuses every repository request until its licence agreement is accepted; an image without the
# agreement answers 404 here and needs nothing.
say "running this script accepts Sonatype's Community Edition End User License Agreement"
if eula=$(api "$BASE/system/eula" 2>/dev/null) && printf '%s' "$eula" | grep -q '"accepted" *: *false'; then
  api -X POST "$BASE/system/eula" -d "$(printf '%s' "$eula" | python3 -c 'import json,sys;d=json.load(sys.stdin);d["accepted"]=True;print(json.dumps(d))')" >/dev/null
fi

STORAGE='"storage":{"blobStoreName":"default","strictContentTypeValidation":true'
api -X POST "$BASE/repositories/pypi/proxy" -d '{"name":"pypi-proxy","online":true,'"$STORAGE"'},
  "proxy":{"remoteUrl":"https://pypi.org/","contentMaxAge":1440,"metadataMaxAge":1440},
  "negativeCache":{"enabled":true,"timeToLive":1440},"httpClient":{"blocked":false,"autoBlock":true}}' >/dev/null
api -X POST "$BASE/repositories/pypi/hosted" -d '{"name":"pypi-hosted","online":true,'"$STORAGE"',"writePolicy":"ALLOW"}}' >/dev/null
api -X POST "$BASE/repositories/pypi/group" -d '{"name":"pypi-group","online":true,'"$STORAGE"'},
  "group":{"memberNames":["pypi-hosted","pypi-proxy"]}}' >/dev/null
api -X PUT "$BASE/security/anonymous" -d '{"enabled":true,"userId":"anonymous","realmName":"NexusAuthorizingRealm"}' >/dev/null
say "repositories ready: pypi-proxy, pypi-hosted, pypi-group"

# A client that can reach only the Nexus container; $1 is the shell it runs. /src is a copy of this checkout.
client() {
  docker run --rm --network "$NET" -v "$ROOT:/src:ro" -v "$WHEELS:/wheels" \
    -e PIP_TRUSTED_HOST="$NAME" -e TWINE_PASSWORD="$PASSWORD" -e TWINE_USERNAME=admin \
    "$@" "$PY" bash -c "$CMD"
}

CMD='python -c "import urllib.request as u
try: u.urlopen(\"https://pypi.org\", timeout=4); print(\"REACHED THE INTERNET\"); raise SystemExit(1)
except OSError: print(\"client: no route to the internet\")"'
client

say "install through the group with pip (no uv)"
CMD='cp -r /src /work && cd /work && export PATH=$PATH:/root/.local/bin && scripts/install_cli.sh && opsai --help | head -1 && ops --version'
client -e PIP_INDEX_URL="$GROUP"

say "install through the group with uv"
CMD='pip install -q uv && cp -r /src /work && cd /work && export PATH=$PATH:/root/.local/bin && scripts/install_cli.sh && opsai --help | head -1'
client -e PIP_INDEX_URL="$GROUP"

say "wheelhouse: build here, upload with twine"
"$ROOT/scripts/wheelhouse.sh" "$WHEELS" >/dev/null 2>&1
CMD='pip install -q twine && twine upload --disable-progress-bar --repository-url http://'"$NAME"':8081/repository/pypi-hosted/ /wheels/*.whl | tail -3'
client -e PIP_INDEX_URL="$GROUP"

say "proxy turned off; install from the hosted repository alone"
api -X PUT "$BASE/repositories/pypi/proxy/pypi-proxy" -d '{"name":"pypi-proxy","online":false,'"$STORAGE"'},
  "proxy":{"remoteUrl":"https://pypi.org/","contentMaxAge":1440,"metadataMaxAge":1440},
  "negativeCache":{"enabled":true,"timeToLive":1440},"httpClient":{"blocked":false,"autoBlock":true}}' >/dev/null
CMD='cp -r /src /work && cd /work && export PATH=$PATH:/root/.local/bin && FROM_INDEX=1 scripts/install_cli.sh && opsai --help | head -1'
client -e PIP_INDEX_URL="$HOSTED_INDEX"
say "passed"
