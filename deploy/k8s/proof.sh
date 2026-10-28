#!/bin/sh
# Proves the Kubernetes manifests on a local kind cluster, no cloud: the same images as compose and Fly, a throwaway
# PostgreSQL outside the cluster with the baseline installed as a DBA would (deploy/database: one login per service),
# the per-service Secrets, the migrate Job, the fake model, and the smoke walk through the proxy on localhost:18891.
# Every pod runs as uid 10001. No real model is called.
# The images and the schema come from one commit (REF, default HEAD, exported with git archive), so the migrations the
# Job runs are the ones the baseline was made from.
#   sh deploy/k8s/proof.sh            KEEP=1 leaves the cluster and the database; BUILD=0 reuses ops-ai/*:dev as built
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
K8S=$ROOT/deploy/k8s
OVERLAY=$K8S/overlays/kind
CLUSTER=ops-ai-proof
PG=ops-k8s-proof-pg
PG_PORT=${OPS_K8S_PROOF_PG_PORT:-15497}
DB=ops_k8s
ORIGIN=http://localhost:18891
WORK=$(mktemp -d)
KUBECTL="kubectl --context kind-$CLUSTER -n ops-ai"
cleanup() {
  [ "${KEEP:-0}" = 1 ] && { echo "proof: kept cluster $CLUSTER, $PG and $WORK"; return; }
  kind delete cluster --name $CLUSTER >/dev/null 2>&1 || true
  docker rm -fv $PG >/dev/null 2>&1 || true
  rm -f "$OVERLAY"/*.env "$OVERLAY/postgres-endpoint.yaml"
  rm -r "$WORK"
}
trap cleanup EXIT

IMAGES="platform agents tools models kb files documents runner opa proxy console"
REF=${REF:-HEAD}
SRC=$ROOT
if git -C "$ROOT" rev-parse --verify -q "$REF" >/dev/null; then
  SRC=$WORK/src
  mkdir -p "$SRC" && git -C "$ROOT" archive "$REF" | tar -x -C "$SRC"
  echo "proof: images and schema from $REF ($(git -C "$ROOT" rev-parse --short "$REF"))"
else
  REF=.
  echo "proof: images and schema from this folder (no git)"
fi
if [ "${BUILD:-1}" = 1 ]; then
  for target in $IMAGES; do
    echo "proof: building ops-ai/$target"
    docker build -q -f "$SRC/deploy/fly/Dockerfile" --target "$target" -t "ops-ai/$target:dev" "$SRC" >/dev/null
  done
  sh "$ROOT/deploy/images/prune_build_cache.sh"
fi

echo "proof: kind cluster $CLUSTER, the proxy's NodePort on $ORIGIN"
kind delete cluster --name $CLUSTER >/dev/null 2>&1 || true
cat > "$WORK/kind.yaml" <<YAML
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraPortMappings:
      - {containerPort: 30890, hostPort: 18891, listenAddress: 127.0.0.1}
YAML
kind create cluster --name $CLUSTER --config "$WORK/kind.yaml" --wait 120s >"$WORK/kind.log" 2>&1 || { tail -20 "$WORK/kind.log"; exit 1; }
for target in $IMAGES; do
  kind load docker-image "ops-ai/$target:dev" --name $CLUSTER >"$WORK/kind.log" 2>&1 || { tail -20 "$WORK/kind.log"; exit 1; }
done

echo "proof: PostgreSQL outside the cluster, the baseline installed with one login per service"
docker rm -fv $PG >/dev/null 2>&1 || true
docker run -d --name $PG --network kind -e POSTGRES_PASSWORD=proof -p 127.0.0.1:$PG_PORT:5432 postgres:17-alpine >/dev/null
# The image first runs a temporary server on its socket only while it initialises; wait for the real one on TCP.
until docker exec $PG pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; do sleep 1; done
SERVER=postgresql://postgres:proof@localhost:$PG_PORT/postgres
SCHEMA="uv run --quiet --project $ROOT python $ROOT/deploy/database/schema.py"
$SCHEMA ddl --server "$SERVER" --out "$WORK/ddl" --ref "$REF" | head -1
$SCHEMA install --server "$SERVER" --dir "$WORK/ddl" --database $DB --passwords "$WORK/logins"
ADDRESS=$(docker inspect -f '{{(index .NetworkSettings.Networks "kind").IPAddress}}' $PG)
sed "s/<db IPv4 address>/$ADDRESS/" "$K8S/overlays/example/postgres-endpoint.yaml" > "$OVERLAY/postgres-endpoint.yaml"
PASSWORD="proof admin password $(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')"
printf 'OPS_BOOTSTRAP_TENANT_NAME=Kubernetes proof\nOPS_BOOTSTRAP_TEAM_NAME=Security\nOPS_BOOTSTRAP_ADMIN_EMAIL=admin@k8s.example\nOPS_BOOTSTRAP_ADMIN_NAME=K8s Admin\nOPS_BOOTSTRAP_ADMIN_PASSWORD=%s\n' "$PASSWORD" > "$WORK/admin.env"
SECRETS="uv run --quiet --project $ROOT python $K8S/write_secrets.py --overlay $OVERLAY --db-host postgres:5432 --db-name $DB --logins $WORK/logins --admin $WORK/admin.env"
$SECRETS

echo "proof: kubectl apply -k deploy/k8s/overlays/kind"
kubectl --context kind-$CLUSTER apply -k "$OVERLAY" >/dev/null
$KUBECTL wait --for=condition=complete job/migrate --timeout=300s
for d in platform tools models kb files documents runner opa console proxy fake-model; do
  $KUBECTL rollout status deploy/$d --timeout=300s >/dev/null
done

echo "proof: the fake model connected from agents-service, its keys into the Secrets"
connect() {
  $KUBECTL exec deploy/agents -- python /app/deploy/fly/connect_model.py --models-url http://models:8730 \
    --base-url http://fake-model:8746/v1 --alias default --model fake-chat --input-price 1 --output-price 1 \
    --budget 5 --key-id "$1" | sed -n 's/^OPS_MODELS_KEY=//p'
}
printf 'OPS_MODELS_KEY_AGENTS=%s\nOPS_MODELS_KEY_DOCUMENTS=%s\n' "$(connect purpose:agents)" "$(connect purpose:documents)" > "$WORK/models.env"
$SECRETS --models "$WORK/models.env"
kubectl --context kind-$CLUSTER apply -k "$OVERLAY" >/dev/null
for d in agents worker documents; do $KUBECTL rollout status deploy/$d --timeout=300s >/dev/null; done
$KUBECTL get pods -o 'custom-columns=POD:.metadata.name,READY:.status.containerStatuses[0].ready,UID:.spec.securityContext.runAsUser,RO_ROOT:.spec.containers[0].securityContext.readOnlyRootFilesystem,SECCOMP:.spec.securityContext.seccompProfile.type,PHASE:.status.phase'

# tools introspects API keys on platform's internal port; the worker (same image as agents, not a client) must not reach
# it. Both run python, so one probe serves both.
echo "proof: platform's internal port $($KUBECTL get networkpolicy platform-internal -o name) admits its clients only"
reach() { $KUBECTL exec deploy/$1 -- python -c "import socket; socket.create_connection(('platform', 8711), 3).close()" >/dev/null 2>&1; }
reach tools || { echo "proof: tools cannot reach platform:8711"; exit 1; }
if reach worker; then echo "proof: worker reached platform:8711, so this cluster does not enforce NetworkPolicy"; exit 1; fi
echo "proof: tools reached platform:8711; worker was refused"

# A rollout is done when the new pod is ready; the Service's endpoints follow a moment later.
for _ in $(seq 1 60); do curl -sf -o /dev/null "$ORIGIN/api/agents/health" && break; sleep 2; done
echo "proof: walking $ORIGIN"
OPS_SMOKE_EMAIL=admin@k8s.example OPS_SMOKE_PASSWORD=$PASSWORD node "$ROOT/deploy/fly/smoke.mjs" "$ORIGIN"
echo "proof: provider connections (the fake's only) and the logins the pods hold:"
docker exec $PG psql -q -U postgres -d $DB -At -c "SELECT name || ' ' || base_url FROM provider_connections"
docker exec $PG psql -q -U postgres -d $DB -At -c "SELECT DISTINCT usename || ' superuser=' || usesuper FROM pg_stat_activity JOIN pg_user USING (usename) WHERE datname = '$DB' AND pid <> pg_backend_pid() ORDER BY 1"
