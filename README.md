# Deck.Check

Production-focused monorepo for Commander deck parsing, tagging, simulation, and optimization.

## Monorepo layout
- `apps/web`: Next.js TypeScript UI (6-tab output workflow)
- `apps/api`: FastAPI backend, update pipeline, async simulation queue
- `packages/shared`: shared zod types + OpenAPI TypeScript generation
- `packages/sim`: pure Python simulation engine (heuristic goldfish)

## Setup

1. Build and run all services:
```bash
docker compose up --build
```

Equivalent helper script:
```bash
sh scripts/dev/up.sh
```

2. Open:
- Web UI: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`

If running web outside Docker:
- use Node `20` or `22` LTS (`apps/web/.nvmrc` = `20`)
- Node 23+ (for example Node 25) can break Next static chunk delivery and cause unstyled/unhydrated pages

3. (Optional) trigger data refresh manually:
```bash
curl -X POST http://localhost:8000/api/admin/update-data
```

4. Run quick smoke checks:
```bash
sh scripts/dev/smoke.sh
```

5. Stop local stack:
```bash
sh scripts/dev/down.sh
```

## Migrations (Alembic)

Schema changes are managed with Alembic (not implicit startup table creation).

Run migrations locally:
```bash
cd apps/api
alembic upgrade head
```

Inside container/CI:
```bash
sh /app/scripts/migrate.sh
```

4. Seed sample flow:
```bash
python apps/api/scripts/seed_sample.py
```

## API endpoints
- `POST /api/decks/parse`
- `POST /api/decks/tag`
- `GET /api/tags/taxonomy`
- `GET /api/cards/display?names=...`
- `POST /api/sim/run` (async queue)
- `GET /api/sim/{job_id}`
- `POST /api/analyze`
- `POST /api/combos/intel`
- `POST /api/rules/watchouts`
- `POST /api/guides/generate`
- `GET /api/rules/search?q=...`
- `GET /api/meta/updates` (last-updated indicators)
- `GET /api/meta/integrations` (data/source provenance)
- `GET /api/meta/runtime` (DB/Redis/queue/worker diagnostics)
- `GET /health/live`
- `GET /health/ready`

## How tagging works
Deterministic + explainable tagger:
1. Intrinsic pass: tag by type line and oracle-text patterns (`#Land`, `#Ramp`, `#Draw`, `#Tutor`, `#Removal`, etc.).
2. Context pass: infer archetype weights from commander + deck corpus, then add `#CommanderSynergy` and archetype tags.
3. Multi-role: cards can hold multiple tags (`#Engine` and `#Protection`, etc.).
4. Confidence + explanation: each tag stores numeric confidence and a short reason.

Universal taxonomy model:
- Core function tags (`#Ramp`, `#Draw`, `#Removal`, ...)
- Pace modifiers (`#FastMana`, `#Ritual`, `#Rock`, `#Dork`, ...)
- Archetype axes (`#Artifacts`, `#Spellslinger`, ...)
- Parent/child normalization (example: `#FastMana` always implies `#Ramp`)

Moxfield-compatible output line format:
```text
{qty} {card name} #!Tag1 #!Tag2
```

## How simulation policies work
The simulator uses London mulligan (including multiplayer first-mulligan-free bottoming behavior), tracks commander tax, and runs solitaire heuristics by turn priorities.

Backend execution:
- default backend: `vectorized` (NumPy batch core)
- automatic safety net: `python_fallback` if vectorized backend is unavailable or throws runtime errors
- every sim summary returns `summary.backend_used` (+ optional warning metadata on fallback)
- runtime diagnostics includes `simulation_backend.vectorized_available` and any import error message

Presets:
- `casual`: keeps broader value hands, slower commander timing
- `optimized`: balanced acceleration/engine sequencing
- `cedh`: tolerates riskier 1-land + fast-mana keeps
- `commander-centric`: prioritizes early commander cast
- `hold commander`: develops mana/value before commander
- `auto`: maps from bracket (lower bracket -> casual; higher -> faster)

## Combo Intel enrichment
`POST /api/analyze` now enriches intent and optimization with CommanderSpellbook combo intel:
- fetches and caches combo variants by deck card names
- classifies `complete` and `near_miss` combo lines
- adds `combo_support_score`, evidence, and warnings to analysis payload
- never blocks analysis if upstream fails (warning-only fallback)

## Color identity enforcement
- Commander color identity is detected immediately after parse.
- Simulation color-access metrics are capped by detected identity size (including colorless handling).
- Recommendation candidates are hard-filtered to legal commander color identity (including colorless-only decks).

## Import sources
- Moxfield URL import (best effort; can be blocked by anti-bot)
- Archidekt URL import via `https://archidekt.com/api/decks/{id}/`
- text paste import remains the guaranteed fallback

## Analytics lenses
The outcomes panel includes multi-lens charts with plain-English interpretation:
- reliability/mana lens
- dedicated mana-base analyzer (pip demand vs source supply, per-color stress/gap)
- mana-value curve diagnostics (permanent vs spell buckets, estimated on-curve cast odds, avg/median MV with/without lands)
- fastest-win replay lens (top 3 fastest wins with mulligan history and turn-by-turn lines)
- phase timeline lens
- risk/failure lens
- mulligan and commander timing lens
- dead-card concentration lens

Detailed lens definitions: [docs/research/ANALYSIS_LENSES.md](docs/research/ANALYSIS_LENSES.md)
Complex-systems adaptation notes: [docs/research/COMPLEX_SYSTEMS_ADAPTATION.md](docs/research/COMPLEX_SYSTEMS_ADAPTATION.md)

## API research notes
See [docs/research/AUTOPILOT_API_RESEARCH.md](docs/research/AUTOPILOT_API_RESEARCH.md) for integrated and candidate data sources.

## Documentation map
See [docs/README.md](docs/README.md) for the organized doc structure (reference, research, plans, product).
Public website hardening and legal launch items: [docs/plans/PUBLIC_LAUNCH_CHECKLIST.md](docs/plans/PUBLIC_LAUNCH_CHECKLIST.md)
Managed hosting rollout (GitHub + Netlify + Render + Neon + Upstash): [docs/plans/NETLIFY_RENDER_NEON_UPSTASH_ROLLOUT.md](docs/plans/NETLIFY_RENDER_NEON_UPSTASH_ROLLOUT.md)

## Data update pipeline
Scheduled (daily via `scheduler` service) and on-demand update jobs:
- Scryfall bulk oracle snapshot download and ingest
- Commander bracket/game changers/banned source refresh
- Rules index refresh (Commander rules pages + Comprehensive Rules PDF)

Each source persists:
- `last_fetched_at`
- `source_url`
- `checksum`
- optional warning when source disagreement/parse ambiguity is detected

## Production Deployment

Delivery stack:
- Terraform (`infra/`)
- GitHub Actions CI workflow (`.github/workflows/ci.yml`)
- Managed hosting blueprint files (`render.yaml`, `netlify.toml`)

AWS target architecture:
- CloudFront + WAF -> ALB -> ECS services (`web`, `api`, `worker`)
- RDS PostgreSQL
- ElastiCache Redis
- EventBridge scheduled ECS task for daily data update

Infrastructure quick start:
```bash
cd infra/envs/staging
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan
terraform apply
```

Container build notes:
- API image build context is repository root so `packages/sim` is embedded:
```bash
docker build -f apps/api/Dockerfile -t deckcheck-api:local .
```
- Web image build context remains `apps/web`:
```bash
docker build -t deckcheck-web:local apps/web
```

Important runtime env vars:
- `ENVIRONMENT`
- `CORS_ALLOWED_ORIGINS`
- `APP_BASE_URL`
- `CARD_CACHE_BACKEND` (`postgres` in staging/prod, `sqlite` for local fallback)
- `DATABASE_URL`
- `REDIS_URL`

## Known limitations
- Not a full multiplayer stack/interactions engine; this is a heuristic, consistent goldfish simulator.
- Game Changers parsing from announcement/formats pages is best-effort and may include false positives without curated normalization.
- Recommendation generation uses role-gap + Scryfall constrained search; it is intentionally conservative.
- Moxfield URL import is best effort; text paste remains fallback.

## Dev runbook note
After simulation backend changes, rebuild worker/API images to ensure NumPy and packaged `packages/sim` code are loaded:
```bash
docker compose up --build
```
