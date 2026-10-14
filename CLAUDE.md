# Working on this repo

Read `docs/product.md` (scope, non-negotiables, build order, status) and `docs/decisions.md` first.
Udit wants: short plan before big chunks, small working vertical slices, ask only for expensive-to-
reverse choices (data model, auth, providers). Log every decision as one line + why in
`docs/decisions.md`, and update the status table in `docs/product.md` when a slice lands.

## Non-negotiables and where they live

- **Tenant isolation.** Workspace routes are `/api/w/{workspace_id}/...` and take `ctx: Ws` (or
  `WsAdmin`/`WsOwner`) from `app/api/deps.py`. Still filter by `ctx.workspace_id` explicitly. New
  tenant tables inherit `TenantScoped` (`app/models/base.py`). Background jobs call
  `bind_workspace(session, workspace_id)` before touching tenant data. `tests/test_tenant_isolation.py`
  sweeps every workspace route automatically; keep it green.
- **Secrets.** Credentials go through `app/core/crypto.py` into `credentials_encrypted`. Never put
  them in `config`, API responses or logs. Never log email bodies or subjects.
- **Raw data is immutable.** `raw_messages` is insert-only (DB trigger). Everything else is derived
  and must be re-buildable from raw + blob storage.
- **Prompts are versioned files; every LLM call records model, prompt version, tokens, cost.** (Comes
  with the Gemini slice. Model names live in config, never hard-coded.)
- **Read-only mail access.** IMAP uses EXAMINE + BODY.PEEK. Never add anything that sends, moves,
  deletes or flags mail.

## Adding a source connector

Implement `SourceConnector` (`app/sources/base.py`): `connect()`, `backfill(since)`,
`fetch_new(cursor)`, `fetch_sent(cursor)`, each yielding `FetchPage`s with an opaque JSON cursor.
Raise `SourceAuthError` / `SourceConfigError` (user must act) or `SourceTemporaryError` (retried),
with messages a non-technical owner understands. Register it in `app/sources/registry.py`.

## Commands

- Backend: `cd backend && uv run pytest` (compose Postgres at localhost:5433, db `e2o_test`),
  `uv run ruff check . && uv run ruff format . && uv run mypy app`, `uv run alembic revision --autogenerate -m "..."`.
- Live IMAP tests: see `docs/dev-imap.md` (`E2O_IMAP_TEST=...`).
- Frontend: `cd frontend && npm run lint && npm run typecheck && npm run build`. After API schema
  changes run `npm run gen:api` and commit `src/lib/api/schema.d.ts`.

## Frontend notes (Next.js 16)

- Read `frontend/node_modules/next/dist/docs/` for APIs. This version differs from older training data.
- Cache Components is on: client components using `useParams`/`useSearchParams` must sit under a
  `<Suspense>` (pages are thin server components wrapping a client component).
- Visited routes stay mounted but hidden (React Activity). Use `useFieldId()` for form ids, and don't
  rely on DOM-global ids.
- UI copy: plain words for non-technical owners ("Emails", "Waiting for reply"), mobile-first.
