#!/usr/bin/env bash
# The parts of `make db-move-image` that touch a PostgreSQL server, each run through PG_EXEC, the command that runs a
# program on that server (the stack's: docker compose ... exec -T postgres) as PG_USER (ops).
#
#   db-move-image.sh rows               every table's row count, one "database schema.table rows" line each, sorted
#   db-move-image.sh dump FILE ROWS     pg_dumpall into FILE, refused unless its data holds every row ROWS counted
#   db-move-image.sh restore FILE       FILE into a fresh server; stops at the first error
#
# A fresh server already has its superuser and the image's own database, which the dump creates again: restore drops
# the fresh server's databases (apart from postgres) and skips the dump's CREATE ROLE for its own login, so every
# remaining error is a real one and stops the restore.
set -euo pipefail

PG_USER=${PG_USER:-ops}
read -r -a EXEC <<<"${PG_EXEC:?set PG_EXEC to the command that runs a program on the server}"

psql_() { "${EXEC[@]}" psql -X -q -U "$PG_USER" -v ON_ERROR_STOP=1 "$@"; }

databases() { psql_ -d postgres -Atc "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY 1"; }

rows() {
  # query_to_xml counts each table inside one statement, so a database needs one round trip however many tables it has.
  local sql="SELECT n.nspname || '.' || c.relname, (xpath('/row/n/text()',
      query_to_xml(format('SELECT count(*) AS n FROM %I.%I', n.nspname, c.relname), false, true, '')))[1]::text
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND n.nspname NOT LIKE 'pg_toast%' ORDER BY 1"
  local d
  for d in $(databases); do
    psql_ -d "$d" -At -F ' ' -c "$sql" | sed "s/^/$d /"
  done | LC_ALL=C sort
}

# Rows in the dump's COPY blocks: pg_dumpall writes one line per row and ends each block with \.
dumped_rows() { awk '/^COPY .* FROM stdin;$/ { on = 1; next } on && /^\\\.$/ { on = 0; next } on { n++ } END { print n + 0 }' "$1"; }

dump() {
  local file=$1 counted=$2 expected got
  "${EXEC[@]}" pg_dumpall -U "$PG_USER" >"$file" || { echo "db-move-image: the dump failed" >&2; return 1; }
  expected=$(awk '{ n += $3 } END { print n + 0 }' "$counted")
  got=$(dumped_rows "$file")
  if [ "$got" != "$expected" ]; then
    echo "db-move-image: the dump holds $got rows where the server has $expected; refused" >&2
    return 1
  fi
  if [ "$expected" = 0 ]; then
    echo "db-move-image: the server has no rows to move; refused" >&2
    return 1
  fi
}

restore() {
  local file=$1 d held
  # Only a fresh server is restored into: dropping databases on one with data would lose it.
  held=$(rows | awk '{ n += $3 } END { print n + 0 }')
  if [ "$held" != 0 ]; then
    echo "db-move-image: this server already holds $held rows; restore goes to a fresh one" >&2
    return 1
  fi
  for d in $(databases); do
    [ "$d" = postgres ] || psql_ -d postgres -c "DROP DATABASE \"$d\""
  done
  grep -vx "CREATE ROLE $PG_USER;" "$file" | psql_ -d postgres
}

case ${1:-} in
  rows) rows ;;
  dump) dump "${2:?dump FILE ROWS}" "${3:?dump FILE ROWS}" ;;
  restore) restore "${2:?restore FILE}" ;;
  *) echo "usage: db-move-image.sh rows | dump FILE ROWS | restore FILE" >&2; exit 2 ;;
esac
