# Jobs database

SQLite database for the jobs board and application tracking. Location:
`db/jobs.db` (override with `JOBS_DB_PATH`); WAL mode, foreign keys on.

## Usage

```bash
python3 -m db.migrate          # apply db/migrations/*.sql (idempotent)
```

```python
from db import connect, run_migrations
run_migrations()
conn = connect()               # sqlite3.Row rows; commit() after writes
```

No ORM: stdlib `sqlite3` only. Schema lives in squashed baseline
`db/migrations/0001_baseline.sql` (folded from the original 0001–0011 once
the schema settled, 2026-10-17; the live database was rebuilt into it with
all data preserved — pre-squash copy kept at `db/jobs.db.pre-squash.bak`).
Curated content (boards) lives in `db/seeds/*.jsonc`, synced by
`python3 -m db.seed`; scoring terms in `scanner/keywords.jsonc` (read
directly, never in the DB).
All future schema changes go in new numbered files on top of the baseline
(`db/migrations/000N_<description>.sql`; never edit an applied file).

## Tables (baseline `0001_baseline.sql`)

| Table | Purpose |
|---|---|
| `boards` | Job boards / sources (`kind`: job_board, careers_page, rss, referral, agency, other); `last_checked_at` = last scrape/refresh (null until first); `metadata` JSON |
| `jobs` | Postings: `status` ∈ bookmarked → ready_to_apply → archived; `workplace_type` ∈ remote, hybrid, onsite, unknown (default unknown); nullable `match_score` 0–100; salary range pair; `metadata` JSON |
| `applications` | One per submission: `status` ∈ ready_to_apply, applied, screening, interviewing, offer, rejected, withdrawn, archived; `applied_at`, method, resume/cover-letter variants, referrer, notes; `metadata` JSON |
| `application_events` | Append-only timeline: status_change, applied, follow_up, interview, offer, rejection, withdrawal, note; `occurred_at` + optional `scheduled_for`; `metadata` JSON |
| `schema_migrations` | Applied filenames, owned by the runner |

Deleting a job cascades to its applications and events. Statuses are separate
by design: `jobs.status` is the board column, `applications.status` is the
pipeline — a job sits in `bookmarked` while its application (if any) advances.

## Scanning features (also consolidated into the baseline)

- `boards.scan_strategy` (`rss` / `jobspy` / `api` / `html` / `manual` /
  `disabled`) + `boards.scan_config` JSON (feed URL, JobSpy params, API
  endpoint) — everything strategy-specific lives in one JSON column.
- Dedupe unique indexes on `jobs`, both partial so NULLs never collide:
  `ux_jobs_board_source_ref (board_id, source_ref)` and
  `ux_jobs_url (lower(url))` — boards often link the same ATS page.
- `jobs.source_ref` (board's own id/guid), `jobs.last_seen_at` (re-discovery
  timestamp; NULL until first scan), `jobs.posted_at` (source's posting date).
- Scoring terms live in `scanner/keywords.jsonc` (never in the DB); the
  scanner's `Matcher` reads that file directly, so swapping in a classifier
  later needs no schema change.
- Board seeds: curated in `db/seeds/boards.jsonc`, synced by
  `python3 -m db.seed` (21 boards; RemoteOK uses `api` — its RSS returns
  HTTP 410; paywalled/dormant boards sit at `manual`, Cleverjobs `disabled`).
- X bookmarks board: `jobs.bookmarked_at` — when the user's X-bookmark
  feed first mentioned this job; set even when the URL is already known from
  another board (intent survives global URL dedupe), and the daily report lists
  bookmarked jobs regardless of score. Board row `X Bookmarks` is
  `scan_strategy='html'`; `scan_config.mode` picks the fetcher —
  `x_bookmarks_cli` (OpenCLI Browser Bridge, primary) or `x_bookmarks`
  (Playwright fallback). See `_docs/scanning.md`.
- Manual entries: board row `Manual` (`scan_strategy='manual'`, so
  scanners skip it) for leads added via
  `python3 -m scanner.tools.add_job`; the tool auto-creates any unknown board
  name the same way. Plus the **`jobs_with_source` view** — `jobs.*` joined
  with `b.name AS source` / `b.kind AS source_kind` — because `jobs.board_id`
  is the source of truth and a join is the cheap way to read it.

Scanner, scoring and cron details: see `_docs/scanning.md`.

## Conventions

- Timestamps: ISO-8601 UTC text `2026-10-17T09:00:00Z` (`strftime('%Y-%m-%dT%H:%M:%SZ','now')` defaults).
- Booleans: `INTEGER` 0/1 with `CHECK (x IN (0,1))`.
- Enums: `TEXT` with `CHECK (... IN (...))`; keep them tight.
- `metadata` (all tables except `schema_migrations`): JSON text,
  `NOT NULL` default `'{}'`, `CHECK (json_valid(metadata))` — any valid JSON
  passes; store objects as the convention. Read with
  `json_extract(metadata, '$.key')`; write valid JSON only.

## Common queries

```sql
-- Active pipeline, most recently touched first
SELECT a.id, j.title, j.company, a.status, a.applied_at
FROM applications a JOIN jobs j ON j.id = a.job_id
WHERE a.status NOT IN ('archived') ORDER BY a.updated_at DESC;

-- Full timeline of one application
SELECT occurred_at, event_type, summary FROM application_events
WHERE application_id = ? ORDER BY occurred_at;

-- Board columns
SELECT status, COUNT(*) FROM jobs GROUP BY status;

-- Source of every job (board name it came from)
SELECT id, title, source, source_kind, status
FROM jobs_with_source ORDER BY id DESC LIMIT 20;
```
