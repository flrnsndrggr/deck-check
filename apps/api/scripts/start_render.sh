#!/usr/bin/env sh
set -eu

sh /app/scripts/migrate.sh
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}" --workers "${WEB_CONCURRENCY:-2}"
