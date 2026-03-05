#!/usr/bin/env sh
set -eu
cd /app
if alembic upgrade head; then
  exit 0
fi

echo "alembic upgrade failed; attempting legacy bootstrap for local dev DB..."
python - <<'PY'
import os
from sqlalchemy import create_engine, text

db = os.environ.get("DATABASE_URL")
if not db:
    raise SystemExit("DATABASE_URL is required")

engine = create_engine(db)
with engine.begin() as conn:
    has_version = bool(conn.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL")).scalar())
    has_core = bool(conn.execute(text("SELECT to_regclass('public.data_source_status') IS NOT NULL")).scalar())
    if not has_version and has_core:
        conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("TRUNCATE TABLE alembic_version"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0001_initial_core')"))
        print("Bootstrapped alembic_version to 0001_initial_core.")
    else:
        print("No bootstrap condition met; leaving DB untouched.")
PY

alembic upgrade head
