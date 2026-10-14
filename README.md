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

## Run it on your computer

You only need **Docker Desktop** (Windows / Mac) or Docker Engine (Linux).

```bash
git clone https://github.com/uditsevak/E2O.git
cd E2O
git checkout claude/pensive-euler-p6nl1o          # until this branch is merged

# 1. Start everything, plus a fake mailbox to test with (first build takes a few minutes)
docker compose --profile dev-imap up --build -d

# 2. Put sample enquiries into the fake mailbox
docker compose run --rm api python -m scripts.seed_dev_mailbox --host imap
```

3. Open **http://localhost:3000**, create an account, and name your business.
4. On **Connect a mailbox**, pick **Other (IMAP)** and enter:
   - Email address: `sales@dcengineering.in`, Password: anything
   - Server settings: IMAP server `imap`, port `3993`, security SSL
   - Click **Test connection**, tick **Allow this server's certificate anyway** (the test server uses a
     self-signed certificate), **Test connection** again, then **Connect mailbox**.
5. Within a few seconds the 8 sample emails show up under **Emails** and **Overview**.

You can also connect a real mailbox (Zoho, GoDaddy, Gmail with an app password, …). It all runs
on your computer, so the mail stays there.

| To… | Run |
| --- | --- |
| Stop (keeps your data) | `docker compose --profile dev-imap down` |
| Start again | `docker compose --profile dev-imap up -d` |
| Update after pulling new code | `docker compose --profile dev-imap up --build -d` |
| Start from scratch (deletes all data) | `docker compose --profile dev-imap down -v` |
| See what the sync worker is doing | `docker compose logs -f worker` |
| Invite a teammate on the same computer | Team → Invite, then open the link in a private window |

If startup fails with "port is already allocated" or "address already in use", another program is
using one of the ports. The app uses 3000 (web), 8000 (API) and 5433 (database), plus 3143, 3993 and 3025
for the test mailbox, all on `localhost` only. Pick free ones, for example:

```bash
E2O_WEB_PORT=3100 E2O_API_PORT=8100 E2O_DB_PORT=5434 docker compose --profile dev-imap up -d
# then open http://localhost:3100
```

To see what is holding a port on a Mac: `lsof -nP -iTCP:3000 -sTCP:LISTEN`.

### Developer mode (hot reload)

Prerequisites: Python 3.13 + [uv](https://docs.astral.sh/uv/), Node 22, Docker (for Postgres).
On Windows, use WSL2 for this mode (the async Postgres driver doesn't run on the Windows event
loop), or stick to the Docker setup above.

```bash
docker compose up -d db                       # Postgres on localhost:5433 (user/pass/db: e2o)

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

For a test mailbox in this mode, run `docker compose --profile dev-imap up -d imap`, seed it with
`uv run python -m scripts.seed_dev_mailbox`, and connect it with server `localhost` (see
docs/dev-imap.md).

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
