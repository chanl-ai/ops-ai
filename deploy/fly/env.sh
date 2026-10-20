# Sourced by entrypoint.sh and release.sh. Every service reads one database URL, OPS_DATABASE_URL, in SQLAlchemy's
# asyncpg form; a Fly Postgres attach writes DATABASE_URL as postgres://...?sslmode=disable. The query is dropped:
# asyncpg takes no sslmode, and the attached database is reached over Fly's private network.
if [ -z "${OPS_DATABASE_URL:-}" ] && [ -n "${DATABASE_URL:-}" ]; then
  url="${DATABASE_URL%%\?*}"
  export OPS_DATABASE_URL="postgresql+asyncpg://${url#*://}"
fi
