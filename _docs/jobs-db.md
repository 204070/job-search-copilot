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
| `jobs` | Postings: `status` ∈ bookmarked → ready_to_apply → applied → archived; `workplace_type` ∈ remote, hybrid, onsite, unknown (default unknown); nullable `match_score` 0–100; salary range pair; `metadata` JSON (include `reason_for_archive` when archived) |
| `applications` | One per submission: `status` ∈ ready_to_apply → applied → screening → interviewing → offer → rejected/withdrawn → archived; `applied_at` set on `applied` transition; method, resume/cover-letter variants, referrer, notes; `metadata` JSON |
| `application_events` | Append-only timeline: status_change, applied, follow_up, interview, offer, rejection, withdrawal, note; `occurred_at` + optional `scheduled_for`; `metadata` JSON |
| `questions` | Canonical, deduped application/interview questions: `question_key` (stable slug), `kind` (application/technical), `canonical_text`, `answer`, `reasoning`, `answer_source` (`profile:<path>` / `answer_bank`), `aliases` JSON, `promotes_to` (profile path awaiting promotion), `status` (draft/approved/retired) |
| `question_instances` | Append-only ledger: one row per time a form asked a question — `field_label`, `field_type`, `required`, `options_seen` JSON, `answer_given`, `asked_at`, optional `application_id`/`job_id` |
| `questions_fts` | FTS5 external-content index over canonical text, answer and aliases (kept in sync by triggers) — powers `lookup` |
| `schema_migrations` | Applied filenames, owned by the runner |

Deleting a job cascades to its applications and events. Statuses are separate
by design: `jobs.status` tracks the posting lifecycle (board column),
`applications.status` tracks the submission pipeline. On submit, **both**
`jobs.status` and `applications.status` become `applied`. `archived` is only
for terminal outcomes (rejected, withdrawn, or deliberately closed).

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

## Question bank (`0002_question_bank.sql`)

Two layers, so "is this frequently asked?" is a `COUNT`, not a judgement call:

- `questions` — the canonical, deduped row: one per distinct question, with the
  reusable answer, the reasoning behind it, and the aliases a form might use.
  No date, no company. When the answer is really a fact, `answer_source` points
  into `artifacts/profile.jsonc` (`profile:$.location.city`) instead of holding
  a second copy.
- `question_instances` — the append-only ledger of every time a form actually
  asked it, carrying the date, the job/application, and the options that form
  showed. Frequency and provenance live here, not in the canonical row.

`questions_with_frequency` reads a question with its `times_asked` and
`last_asked_at`. `questions_fts` is a stdlib FTS5 index kept in sync by
triggers; the CLI treats it as an accelerator and falls back to a LIKE scan if
it is ever absent (a SQLite build without FTS5 makes migration `0002` fail, so
keep FTS5 binaries).

The CLI is `python3 -m db.tools.questions`:

| Command | What it does |
|---|---|
| `lookup "<label>"` | Best canonical matches for a form's wording, with answer + reasoning + frequency. `--kind technical`, `--evidence`. Exit 1 on a miss |
| `record` | Upsert the canonical question and append one instance (`--key`, `--label`, `--option`, `--field-type`, `--required`, `--answer-given`, `--job-id`, `--application-id`, `--source`, `--promotes-to`, `--alias`) |
| `frequency` | Every question by times asked (`--kind`, `--min-count`) |
| `promotions` | Facts with a `promotes_to` path not yet in `profile.jsonc` |
| `digest --kind application\|technical` | Regenerate a FAQ doc (`--out PATH`, else stdout) |
| `import-faq` | One-off: load the pre-bank `artifacts/faqs/*.md` format |

`artifacts/faqs/application-faq.md` and `technical-faq.md` are **generated** by
`digest`, not hand-written. Record answers with `record`, then regenerate. The
awkward case worth naming: a question a form phrases with no words in common
with the canonical text misses until you add that phrasing as an `--alias`.

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

-- What a form is most likely to ask, and how often it has come up
SELECT question_key, kind, times_asked, last_asked_at, canonical_text
FROM questions_with_frequency
WHERE status <> 'retired' ORDER BY times_asked DESC, last_asked_at DESC;

-- The exact wording and options a given form showed, most recent first
SELECT i.asked_at, i.field_label, i.field_type, i.options_seen, i.answer_given,
       j.company, j.title
FROM question_instances i
JOIN questions q ON q.id = i.question_id
LEFT JOIN jobs j ON j.id = i.job_id
WHERE q.question_key = 'us_sponsorship_required'
ORDER BY i.asked_at DESC;
```
