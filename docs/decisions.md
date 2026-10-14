# Decisions

One line per decision, and why. Newest at the bottom of each section. Change a decision by adding a
new line that supersedes it. Don't rewrite history.

## 2026-10-14: slices 1–2 (foundations, first mailbox end to end)

### Stack and infrastructure
- **Monorepo** (`backend/`, `frontend/`, `docs/`). Two people, one deploy story, one PR per feature.
- **Python 3.13 + uv, FastAPI, SQLAlchemy 2 (async, psycopg 3), Alembic.** SQLAlchemy instead of SQLModel because the tenancy guard needs SQLAlchemy ORM events (`do_orm_execute`, `with_loader_criteria`). API schemas are plain Pydantic.
- **Job queue on Postgres (procrastinate), no Redis.** One less service to run and pay for. Retries, locks, periodic jobs and enqueue de-duplication (queueing locks) come built in.
- **Procrastinate's schema is vendored** (`backend/alembic/sql/`) and applied by an Alembic migration, so every environment is migrated one way. Upgrading procrastinate means adding a migration with its upgrade SQL.
- **Blob storage behind one interface:** local disk (dev, single-box pilot) or any S3 API. Cloudflare R2 is the likely prod choice because it charges no egress.
- **One backend image** for the API, the worker and migrations. The frontend is a standalone Next.js image.

### Auth and tenancy
- **Self-built auth (Udit's call):** email + password (argon2) and Google sign-in (OIDC + PKCE, `openid email profile` only). No vendor and no per-user cost.
- **Opaque session token in an httpOnly, SameSite=Lax cookie. The DB stores only its SHA-256.** Sessions can be revoked server-side and a DB leak can't be replayed.
- **The browser only talks to the Next.js origin. Next.js rewrites `/api/*` to FastAPI.** No CORS, and cookies and Google redirects are same-origin. An `Origin` check on unsafe methods adds CSRF defence in depth.
- **Google sign-in links to an existing password account only if Google says the email is verified.** This prevents account takeover through an unverified Google address.
- **Every workspace route is `/api/w/{workspace_id}/…` and uses the `Ws` dependency.** It checks membership and binds the DB session to the workspace.
- **ORM safety net:** a bound session auto-filters SELECT/UPDATE/DELETE on `TenantScoped` models and refuses to write another workspace's rows. A forgotten `where` returns nothing instead of leaking.
- **A test sweeps every `/api/w/{workspace_id}` route automatically**, so new endpoints are covered by the isolation test without anyone remembering to add them.
- **Other workspaces return 404, not 403.** This doesn't reveal that they exist.
- **Postgres row-level security is deferred.** App-level scoping plus the guard and tests cover v0. Revisit before onboarding many tenants.
- **Roles: owner / admin / member.** Admins and owners connect mailboxes and invite. Only owners manage owners. A workspace always keeps one owner.
- **Invites are copy-and-share links (WhatsApp-friendly) valid for 7 days, and must be accepted by the invited email.** v0 sends no email, and binding to the email stops forwarded links from being used by others.

### Data model
- **`raw_messages` is insert-only.** A DB trigger rejects UPDATE. The bytes live in blob storage. This enforces "raw data is immutable" in the database, not by convention.
- **`messages` is a 1:1 normalized view of a raw message, updated in place with a `normalizer_version`.** It can be rebuilt without re-fetching, and ids stay stable for future enquiry links.
- **Attachments are content-addressed per workspace (`ws/{id}/att/{sha256}`).** The same PDF CC'd to three inboxes is stored once.
- **Enums are stored as VARCHAR, not native Postgres enums.** New sources and statuses don't need migrations.
- **The source connection stores non-secret `config` (JSON) separately from `credentials_encrypted`.** The API can show settings without ever touching secrets.

### Secrets and logging
- **Connector credentials are encrypted with Fernet (MultiFernet) using keys from env.** Rotation means adding a new key first. The app refuses to start in prod with the dev keys.
- **The API never returns credentials. Logs carry ids and counts, never mail content, and a redaction filter is the last line of defence.**

### IMAP connector
- **IMAP first** (works with every provider, no OAuth verification needed for the pilot).
- **Read-only by construction:** folders are opened with EXAMINE and bodies fetched with `BODY.PEEK[]`, so nothing is ever marked as read. A live Dovecot test checks this.
- **Each folder has a cursor (`UIDVALIDITY` + last UID) saved in the same transaction as each page.** A crash resumes where it stopped.
- **Raw mail is de-duplicated by provider id and by content SHA-256 per connection.** This survives UIDVALIDITY resets and backfill re-runs.
- **After a dated backfill, the cursor moves to the folder's top.** Older mail moved into the inbox later is outside the window and must not leak in through the incremental fetch.
- **The Sent folder is found by the SPECIAL-USE `\Sent` flag, then by common names** ("Sent", "Sent Items", "INBOX.Sent", "[Gmail]/Sent Mail"…). The user can override it when connecting.
- **TLS certificates are verified by default, with a per-mailbox opt-out offered only after a certificate error.** Shared cPanel hosting often presents the host's certificate, not the customer's domain.
- **A rejected password stops syncing** (status `error`, shown to the user). **Network errors are retried** (5 attempts, exponential backoff), and the scheduler retries once per interval, based on the last attempt.
- **Poll every 5 minutes, backfill 30 days by default (max 180).** Cheap enough for the pilot, and fresh enough for "what came in today".
- **IMAP presets are a JSON data file**, not code. Microsoft 365 is shown as "coming soon" because Microsoft has turned off password IMAP for most tenants, so it needs the Graph connector.

### Email parsing
- **Charset fallback order: declared → UTF-8 → statistical detection (only for 200 bytes or more) → Windows-1252.** Detection on short text guesses CJK, and undeclared legacy mail here is mostly Windows-1252.
- **Forwarded emails attached as `message/rfc822` are kept whole as `.eml` attachments.** Forwarded enquiries arrive this way and need their own extraction later.
- **Wrong content types are corrected by sniffing** (PDFs sent as `application/octet-stream` are common). Extraction will route on the corrected type.
- **Attached emails that were base64 or quoted-printable encoded get decoded, and the attachment is named after their subject.** The RFC forbids encoding them, but some mail clients do it, and otherwise the forwarded enquiry was lost. This was found with the seeded test mailbox.
- **Raising `PARSER_VERSION` re-parses every stored email automatically** (the scheduler's sweep picks up outdated messages, 500 a minute). Parser fixes reach old mail without re-fetching it.
- **HTML email is only shown in a sandboxed iframe with a CSP that blocks remote content.** No scripts and no tracking pixels.

### Frontend
- **Next.js 16 (App Router, Cache Components on), TanStack Query, openapi-fetch with types generated from FastAPI** (`npm run gen:api`). The UI and API can't drift silently.
- **Data is client-rendered behind the same-origin proxy.** Pages are prerendered shells with a Suspense boundary, as Cache Components requires for URL params.
- **Form field ids come from `useId()`.** Next 16 keeps visited pages mounted (hidden), so fixed ids collide and labels can focus a hidden input. This was found in browser testing.
- **shadcn/ui components are written in the shadcn layout** (`components.json`, `components/ui`). The registry was unreachable from the build sandbox. `npx shadcn add` works normally later.
- **Mobile-first:** bottom tab bar on phones, sidebar on desktop, native `<select>` so phones use the OS picker.
- **Plain words: "Emails", "Mailboxes", "Team".** "Enquiries" becomes the main tab when the classifier lands, so the UI never shows an empty promise.
- **The working name "Enquiry Inbox" appears only in the UI** (`PRODUCT_NAME`). Code and infrastructure use neutral names, so renaming is cosmetic.

### Local setup
- **The first-run path is Docker only** (`docker compose --profile dev-imap up --build`), with a GreenMail test mailbox and a seeder script with realistic sample enquiries. Anyone can see the product working in a few commands, without a real mailbox.
- **Compose publishes ports on 127.0.0.1 only, Postgres on host port 5433, all overridable** (`E2O_WEB_PORT`, `E2O_API_PORT`, `E2O_DB_PORT`). Developer Macs often already run Postgres on 5432 (first install failed on exactly this), and the dev database shouldn't be reachable from the local network.
