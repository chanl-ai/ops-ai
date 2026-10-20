#!/bin/sh
# Proves the mailbox demo against the release images on this machine, with the fake model and a test mailbox: starts
# the compose proof stack (proof.sh, KEEP=1) with mailbox-demo.yaml's GreenMail and bank stand-in, prepares it as
# staging is prepared (deploy/fly/staging/mailbox_demo.py seed), then walks it (walk): a levy notice emailed to the
# team mailbox becomes a run, levy cases, Human Tasks and a reply in the sender's inbox. Everything it starts is
# removed at the end; the bank's certificate, keys and the env file live in a temp folder and are never printed.
#   sh deploy/compose/mailbox_proof.sh        BUILD=1 rebuilds the images first; KEEP=1 leaves the stack running
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PROJECT=ops-compose
PORT=${OPS_PROOF_PORT:-18890}
WORK=$(mktemp -d)
ENV=
cleanup() {
  if [ "${KEEP:-0}" = 1 ]; then echo "mailbox proof: left running as $PROJECT on http://localhost:$PORT"; return; fi
  if [ -n "$ENV" ]; then
    docker compose -p $PROJECT -f "$ROOT/deploy/compose/app.yaml" -f "$ROOT/deploy/compose/try.yaml" \
      -f "$ROOT/deploy/compose/mailbox-demo.yaml" --env-file "$ENV" --profile fake-model down -v --remove-orphans \
      >/dev/null 2>&1 || true
    rm -rf "$(dirname "$ENV")"
  fi
  docker rm -fv ops-compose-proof-pg >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

mkdir "$WORK/bank"
# One throwaway RSA certificate for the bank, GreenMail's IMAP and Mailpit's STARTTLS (Java reads RSA keystores).
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj /CN=api.bank.test \
  -addext "subjectAltName=DNS:api.bank.test,DNS:mail.demo.test,DNS:smtp.demo.test" \
  -keyout "$WORK/bank/bank.key" -out "$WORK/bank/bank.crt" 2>/dev/null
openssl pkcs12 -export -in "$WORK/bank/bank.crt" -inkey "$WORK/bank/bank.key" -out "$WORK/bank/demo.p12" \
  -passout pass:demo -name demo
# The images' users read them through a read-only mount; they are a throwaway set for this run.
chmod 644 "$WORK/bank/"*
OPS_DEMO_BANK_DIR=$WORK/bank
FAKE_BANK_KEY=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
FAKE_BANK_WEBHOOK_SECRET=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
export OPS_DEMO_BANK_DIR FAKE_BANK_KEY FAKE_BANK_WEBHOOK_SECRET
printf 'FAKE_BANK_KEY=%s\nFAKE_BANK_WEBHOOK_SECRET=%s\n' "$FAKE_BANK_KEY" "$FAKE_BANK_WEBHOOK_SECRET" >"$WORK/bank.env"

status=0
KEEP=1 BUILD=${BUILD:-0} OPS_PROOF_COMPOSE_EXTRA="-f $ROOT/deploy/compose/mailbox-demo.yaml" \
  sh "$ROOT/deploy/compose/proof.sh" >"$WORK/proof.log" 2>&1 || status=$?
grep -v -E '^ *(Container|Volume|Network) ' "$WORK/proof.log"
ENV=$(sed -n 's/^proof: left running as .* (env \(.*\))$/\1/p' "$WORK/proof.log")
[ $status = 0 ] || { echo "mailbox proof: the stack proof failed (above)"; exit 1; }
# GreenMail and the bank answer on the compose network's private range, which egress refuses until it is listed.
RANGE=$(docker network inspect ${PROJECT}_default -f '{{(index .IPAM.Config 0).Subnet}}')
DEMO="uv run --quiet --project $ROOT python $ROOT/deploy/fly/staging/mailbox_demo.py"
ORIGIN=http://localhost:$PORT

echo "mailbox proof: preparing $ORIGIN as staging is prepared"
$DEMO seed --origin $ORIGIN --admin-env "$ENV" --people "$WORK/people.env" --bank https://api.bank.test \
  --bank-env "$WORK/bank.env" --egress-range "$RANGE"
echo "mailbox proof: walking it with a GreenMail mailbox and the fake model"
$DEMO walk --origin $ORIGIN --admin-env "$ENV" --people "$WORK/people.env" --mailbox intake@demo.test \
  --imap mail.demo.test:3993 --smtp smtp.demo.test:1025 --send-smtp 127.0.0.1:${OPS_DEMO_SMTP_PORT:-13025} \
  --read-mailpit http://127.0.0.1:${OPS_DEMO_MAILPIT_PORT:-18025}
