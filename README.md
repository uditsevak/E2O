# Enquiry Inbox

*Working name.* Every B2B enquiry from every inbox, in one dashboard: read, understood, assigned and
tracked until someone replies. Built for Indian SME manufacturers and traders. DC Engineering is the
first tenant.

- Product context, scope and status: [docs/product.md](docs/product.md)
- Decisions and why: [docs/decisions.md](docs/decisions.md)
- Local test IMAP servers: [docs/dev-imap.md](docs/dev-imap.md)

## What works today

- Sign up with email + password (or Google, when configured), create a workspace, invite teammates
  with a link (owner / admin / member).
- Connect any IMAP mailbox (Zoho, GoDaddy, Rediffmail Pro, cPanel hosting, Gmail with an app
  password…). Presets, connection test, Sent-folder detection, plain-language errors.
- Background sync: 30-day backfill on connect, then new mail every 5 minutes, Inbox + Sent,
  strictly read-only. Raw mail is stored immutably and parsed into emails + attachments.
- Mobile-first dashboard: overview, searchable email list, email detail with attachments,
  mailbox health, team.

Next: Gemini classification and extraction, which turns emails into **Enquiries**. See the build order in
`docs/product.md`.

## Layout

```
backend/    FastAPI app, SQLAlchemy models, Alembic migrations, connectors, pipeline, jobs, tests
  app/api/        HTTP routes (workspace routes live under /api/w/{workspace_id})
  app/core/       tenancy guard, encryption, logging
  app/sources/    SourceConnector interface, IMAP connector, sync service
  app/pipeline/   normalize (email parsing); classify/extract come next
  app/jobs/       procrastinate jobs + worker (Postgres-backed queue)
frontend/   Next.js 16 app (App Router, Tailwind, shadcn/ui, TanStack Query)
docs/       product context, decisions, dev notes
```

## Run it

### Everything in Docker

```bash
docker compose up --build
# open http://localhost:3000
```

### Local development (hot reload)

Prerequisites: Python 3.13 + [uv](https://docs.astral.sh/uv/), Node 22, Docker (for Postgres).

```bash
docker compose up -d db                       # Postgres on :5432 (user/pass/db: e2o)

cd backend
cp .env.example .env                          # dev defaults work as-is
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload          # API on :8000 (docs at /api/docs)
uv run python -m app.jobs.worker              # in another terminal: sync + processing jobs

cd frontend
npm install
npm run dev                                   # http://localhost:3000 (proxies /api to :8000)
```

Want a mailbox to play with? `docker compose --profile dev-imap up -d imap` (see docs/dev-imap.md).

## Checks

```bash
# backend (needs Postgres; tests use the e2o_test database, which they create from scratch)
docker compose exec db createdb -U e2o e2o_test   # once
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest

# frontend
cd frontend && npm run lint && npm run typecheck && npm run build

# after changing API schemas: regenerate the typed client
cd frontend && npm run gen:api
```

CI runs all of the above on every pull request (`.github/workflows/ci.yml`).

## Configuration

Backend settings come from environment variables (see `backend/.env.example`). In production you
**must** set `ENV=prod`, `SECRET_KEY` and `SECRETS_ENCRYPTION_KEYS`, or the app refuses to start.
For Google sign-in, set `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` and add
`{APP_URL}/api/auth/google/callback` as an authorised redirect URI.
