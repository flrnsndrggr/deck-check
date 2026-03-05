# Netlify + Render + Neon + Upstash Rollout

This is the production rollout path for Deck.Check:
- GitHub = source + CI
- Netlify = `apps/web`
- Render = API + worker + scheduler
- Neon = Postgres
- Upstash = Redis

## 1) GitHub setup
- Default branch: `main`.
- Branch protection on `main`:
  - require pull request before merge
  - require status checks (`API tests`, `Web build`)
- CI workflow: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)

## 2) Neon (Postgres)
- Create database and user.
- Use SQLAlchemy DSN format:
  - `postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require`

## 3) Upstash (Redis)
- Create Redis database.
- Use TLS URL:
  - `rediss://:PASSWORD@HOST:PORT`

## 4) Render services
Use [`render.yaml`](../../render.yaml), then set non-synced variables in Render UI.

Services:
- `deck-check-api` (web service)
- `deck-check-worker` (background worker)
- `deck-check-scheduler` (daily cron)

Important commands:
- API start:
  - `sh /app/scripts/migrate.sh && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`
- Worker start:
  - `python -m app.workers.rq_worker`
- Scheduler:
  - `python /app/scripts/update_data.py --all`

## 5) Netlify web deploy
- Connect repo.
- Build config from [`netlify.toml`](../../netlify.toml):
  - base: `apps/web`
  - command: `npm install && npm run build`
- Set env vars:
  - `NEXT_PUBLIC_API_BASE=https://your-api-domain`
  - `NEXT_PUBLIC_SITE_URL=https://your-netlify-domain`
  - plus legal/contact vars from [`apps/web/.env.example`](../../apps/web/.env.example)

## 6) Cross-service env values
API:
- `APP_BASE_URL=https://your-netlify-domain`
- `CORS_ALLOWED_ORIGINS=https://your-netlify-domain`
- `TRUSTED_HOSTS=api.your-api-domain`
- `FORCE_HTTPS=1`

Web:
- `NEXT_PUBLIC_API_BASE=https://your-api-domain`

## 7) Smoke checks
- API:
  - `/health/live`
  - `/health/ready`
- App flow:
  - parse -> tag -> sim -> analyze -> guides
- Queue:
  - worker consumes jobs
- Scheduler:
  - data update job runs
