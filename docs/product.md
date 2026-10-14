# Enquiry Inbox — product context

> Working name. Rename once we pick a brand. Built by Aakar (Udit Sevak & Pakshal Jain).
> Keep this file updated as scope changes. Decisions and their reasons live in [decisions.md](decisions.md).

## Status (last updated 2026-10-14)

| Build step | State |
| --- | --- |
| 1. Scaffold, Docker Compose, FastAPI, Next.js, auth, workspaces | **Done**: email+password and Google sign-in, workspaces, roles, invite links |
| 2. SourceConnector interface + IMAP connector | **Done**: IMAP (any provider). Gmail and Microsoft Graph not started |
| 3. Raw message + attachment storage, backfill + incremental sync jobs | **Done**: Postgres job queue, 5-minute polling, 30-day backfill |
| 4. Gemini classify + extract | Not started (next) |
| 5. Enquiry model, dedupe, sent-mail reply detection | Not started. Sent mail is already being collected |
| 6. Dashboard | Partly: overview, email list/search, email detail, mailboxes, team. Enquiry views come with 4–5 |
| 7. Eval harness | Not started |

Known gaps in what is built: no password reset or email verification yet (needs a transactional email
sender), no login rate limiting, Postgres row-level security not enabled (app-level isolation + tests only).

---

## What we're building

A self-serve web product for Indian SME / MSME manufacturers and traders. They sign up, connect every place B2B enquiries arrive (multiple email inboxes now; portals and WhatsApp later), and get one dashboard of every enquiry: read, qualified, attachments understood, assigned, and tracked until someone replies.

It started as a custom build for our first client, DC Engineering (a flanges manufacturer in Mumbai). Their pain:

- Enquiries land in several inboxes: the company address, salespeople's own mailboxes, forwarded threads.
- Nobody can see the full list of enquiries, which ones are pending, or which got missed.
- Going from enquiry to quotation takes 3–4 days. Most of that time is enquiries sitting in queues.

We are building it as a product from day one, with DC Engineering as the first tenant and design partner. Anything DC-specific has to be configuration, never code.

## Who it's for

- **Owner** of a family-run manufacturing or trading business. Not technical. Wants to see what came in, what's stuck and what's worth chasing. Usually on his phone.
- **Sales / enquiry handlers.** Want one list instead of five inboxes, with the details already pulled out of the email and the PDF.
- Typical setups:
  - Google Workspace or Gmail
  - Zoho Mail
  - Outlook / Microsoft 365
  - GoDaddy, Rediffmail or other cPanel mail (IMAP)
  - Leads from portals such as IndiaMART and TradeIndia
  - WhatsApp for a large share of the conversations

## MVP scope (v0)

In scope:

1. **Signup + workspace (tenant).** One business = one workspace. Invite teammates.
2. **Connect sources**
   - Gmail / Google Workspace via OAuth.
   - Outlook / M365 via Microsoft Graph.
   - Generic IMAP for everything else (host, port, username, app password).
   - Multiple mailboxes per workspace.
3. **Ingest.** Pull new mail on a schedule (polling is fine for v0). Backfill the last N days on connect.
4. **Classify.** Is this a real business enquiry, or something else (spam, newsletter, supplier mail, internal, existing-order follow-up)?
5. **Extract** structured fields from the email body and its attachments (PDF, Excel, images of drawings or scanned RFQs):
   - customer, contact, products / line items, quantities, specs, delivery date, location, deadline for the quote.
6. **Qualify.** Give each enquiry a simple score and the reasons behind it:
   - complete vs missing info
   - order size
   - known vs new customer
   - urgency
   - fit with what the business makes
7. **Dedupe + thread.** The same enquiry often arrives in several inboxes (CC'd, forwarded). Merge these into one enquiry and keep the sources linked.
8. **Response tracking.** Read the Sent folder to detect when someone replied. This drives:
   - status: New → Seen → Replied
   - time-to-first-reply, the key metric
9. **Dashboard**
   - Unified enquiry list: filters, search, status, assignee, age, score.
   - Enquiry detail: original email, attachments, extracted fields (editable), score reasons, thread history.
   - Overview: enquiries today / this week, pending more than 24h, average time to reply, by source, by assignee.

Not in scope yet (do NOT build, but don't design them out):

- Generating quotations or pricing. That comes later, and will connect to our separate costing product.
- Sending email from our app. We are read-only in v0.
- WhatsApp, IndiaMART and TradeIndia ingestion. These are v1 sources, so the source abstraction must support them.
- Daily WhatsApp / email summary to the owner. v1, and very likely the stickiest feature.
- Billing / payments.

## Key product decisions

- **LLM: Google Gemini, not the Claude API.**
  - Use a Flash-tier model for classification and extraction.
  - Use a Pro-tier model only as a fallback for messy documents.
  - Check current model names; don't hardcode them. Keep them in config.
  - Use Gemini's structured output (response schema) for every extraction.
  - Send PDFs and images natively (multimodal). Don't OCR first unless quality forces it.
- **Industry templates, not hardcoding.**
  - Extraction uses a generic core schema plus a per-workspace field template.
  - Example template for flanges: type, size (NB/inch), pressure class (#150, #300…), material grade (A105, SS316…), standard (ASME B16.5…), facing, quantity, test certificate needs.
  - The template is data (JSON) that the workspace owner or we can edit.
- **Read-only by default.** Request the narrowest scopes possible. Owners in this market are wary of "access to my email", so trust is a product feature: say clearly what we read and why.
- **Human corrections are gold.** Every field the user edits gets stored as a correction, so we can use it later for evals and few-shot prompting per tenant.
- **Simple, Indian-SME-friendly UI.**
  - Mobile-first overview.
  - English UI for now, with plain words: "Enquiries", "Waiting for reply" — not "Leads pipeline".

## Stack

See [decisions.md](decisions.md) for what was chosen and why. In short: Python 3.13, FastAPI, SQLAlchemy 2 (async) + Alembic, Postgres (also the job queue, via procrastinate), Next.js 16 + TypeScript + Tailwind + shadcn/ui, S3-compatible blob storage (local disk in dev), self-built auth (email + Google sign-in).

## Architecture sketch

```
Sources (Gmail API | MS Graph | IMAP | later: IndiaMART, WhatsApp)
   └─ SourceConnector interface: connect(), backfill(since), fetch_new(cursor), fetch_sent(cursor)
        ↓ raw messages + attachments (stored as-is, immutable)
Pipeline (per message, async jobs)
   1. normalize  → Message (headers, body text/html, attachments, thread ids)
   2. classify   → is_enquiry? category, confidence
   3. extract    → core fields + template fields (body + attachments), per-field confidence
   4. dedupe     → match to existing Enquiry (thread ids, sender+subject+content similarity)
   5. qualify    → score + reasons
   6. reply-detect (from sent mail) → status, first_reply_at
        ↓
Enquiry (the unit the user sees) ← many Messages, many Sources
        ↓
API → Dashboard
```

Core entities (first pass; ✓ = exists):

- Workspace ✓
- User ✓
- Membership (with role) ✓
- SourceConnection (type, credentials encrypted, sync cursor, status) ✓
- RawMessage ✓ (plus Message: the normalized, re-derivable view of a RawMessage)
- Attachment ✓
- Enquiry (status, assignee, score, extracted fields as JSONB, first_reply_at)
- EnquiryMessage (link table)
- FieldTemplate
- Correction
- ProcessingRun (model, prompt version, tokens, cost, latency — for evals and cost tracking)

## Non-negotiables

- **Tenant isolation everywhere.** Every query is scoped by `workspace_id`. Add tests for it.
- **Secrets:** OAuth refresh tokens and IMAP passwords are encrypted at rest. Never log them, never log email bodies in plain logs.
- **Raw data is immutable.** Re-running the pipeline with a new prompt or model must be possible without re-fetching mail.
- **Prompts are versioned files**, not inline strings. Every extraction records the prompt version and model used.
- **Cost per enquiry is tracked** from day one.

## Known risks / things to check early

- **Gmail restricted scopes.** `gmail.readonly` is a restricted scope.
  - Publishing to the public needs Google's verification and a security assessment, which takes time and money.
  - For pilot tenants: run as an unverified/testing app (user cap applies) or use IMAP with app passwords.
  - Plan the verification path before public launch. Verify current requirements.
- **Microsoft 365:** some tenants need admin consent for Mail.Read.
- **IMAP in India:** cPanel / Rediff / GoDaddy mail is common and often flaky. Handle timeouts, folder name differences ("Sent", "Sent Items", "INBOX.Sent") and encoding issues.
- **Attachments:**
  - Scanned PDFs and photos of hand-marked drawings.
  - Excel RFQs with many line items.
  - Mixed Hindi/English in WhatsApp later.
  - Build an eval set from DC Engineering's real enquiries as soon as we have them.
- **Dedupe false merges are worse than missed merges.** Be conservative; let users merge or split manually.

## Build order

1. Repo scaffold, Docker Compose (Postgres, Redis), FastAPI skeleton, Next.js skeleton, auth, workspaces.
2. SourceConnector interface + IMAP connector first (works with any provider, no OAuth verification needed for the pilot). Then Gmail, then Graph.
3. Raw message + attachment storage, backfill + incremental sync jobs.
4. Gemini classify + extract with structured output, using a generic schema plus the DC flanges template.
5. Enquiry model, dedupe, sent-mail reply detection.
6. Dashboard: list, detail with editable fields, overview metrics.
7. Small eval harness: labelled sample enquiries → field-level accuracy per prompt version.

(Redis was dropped from step 1: the job queue runs on Postgres. See decisions.md.)

## Working agreement (Udit)

- Direct and fast. Make sensible decisions and keep moving. Ask only when a choice is expensive to reverse: data model, auth, provider choices.
- Before big chunks, give a short plan, then build.
- Prefer small, working vertical slices over broad scaffolding.
- Keep `docs/decisions.md` (one line per decision + why) and keep this file updated as scope changes.

## Open questions (not decided yet)

- Product name and positioning: "one inbox for every enquiry" vs "never miss an enquiry" vs "time-to-quote tracker".
- Pricing model for self-serve: per workspace, per connected mailbox, or per enquiry processed?
- Onboarding: how much self-serve vs us setting up the field template for each industry?
- Which v1 source to add first: WhatsApp Business or IndiaMART?
- Owner daily summary channel and format.
- How and when this connects to the costing product (enquiry → price → quotation → work order).
