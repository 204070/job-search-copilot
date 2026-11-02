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
| `questions` | Canonical, deduped application/interview questions: `question_key` (stable slug), `kind` (application/technical), `canonical_text`, `answer`, `reasoning`, `answer_source` (`profile:<path>` / `answer_bank`), `aliases` JSON, `promotes_to` (profile path awaiting promotion), `retired_at` (NULL while in use; the state itself is derived, see below) |
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

`questions_with_frequency` reads a question with its `times_asked`,
`last_asked_at` and the derived `state` + `last_sent_text`. `questions_fts` is a
stdlib FTS5 index kept in sync by triggers; the CLI treats it as an accelerator
and falls back to a LIKE scan if it is ever absent (a SQLite build without FTS5
makes migration `0002` fail, so keep FTS5 binaries).

The CLI is `python3 -m db.tools.questions`:

| Command | What it does |
|---|---|
| `lookup "<label>"` | Best canonical matches for a form's wording, with answer + reasoning + frequency. `--kind technical`, `--evidence`. Exit 1 on a miss |
| `record` | Upsert the canonical question and append one instance (`--key`, `--label`, `--option`, `--field-type`, `--required`, `--answer-given`, `--job-id`, `--application-id`, `--source`, `--promotes-to`, `--clear-promotes-to`, `--alias`) |
| `retire --key KEY [--undo]` | Set an answer aside so `lookup` stops offering it, or bring it back |
| `frequency` | Every question by times asked (`--kind`, `--min-count`) |
| `promotions` | Facts with a `promotes_to` path not yet in `profile.jsonc` |
| `digest --kind application\|technical` | Regenerate a FAQ doc (`--out PATH`, else stdout) |
| `import-faq` | One-off: load the pre-bank `artifacts/faqs/*.md` format |
| `selftest` | Drive one answer through every derived state on a throwaway database |

`artifacts/faqs/application-faq.md` and `technical-faq.md` are **generated** by
`digest`, not hand-written. Record answers with `record`, then regenerate. The
awkward case worth naming: a question a form phrases with no words in common
with the canonical text misses until you add that phrasing as an `--alias`.

**An answer's state is derived, never approved.** Submitting is the review, and
the command that used to record it (`approve --from-app N`) recorded only that
a command had been run: on the live bank it marked all 18 answers approved in
one call, and only 10 of those had ever been on a submitted application. What
the bank shows instead comes from the ledger, in `questions_with_frequency`:

- `unsent` — no submitted application has ever carried this question;
- `sent` — the stored text is exactly what an employer received;
- `revised` — it went out and the text has changed since, so the current
  wording has not been read in this form; the one state the digest raises;
- `retired` — deliberately set aside with `retire`, the only state a human
  writes.

"Reached an employer" is `applications.applied_at`, not the current status: an
application withdrawn after it went out still carried the text, so withdrawing
must not un-send it. `record --answer` writes the *reusable* answer, so a note
about a form belongs in `metadata` (the FAQ renders `original_answer`), not in
`answer`; otherwise the sent/revised comparison compares a note with an answer.

A long answer that was typed into a form but never recorded in the bank still
exists: `applications.metadata.drafts` holds the text as it was filled, and
`submitted_answers` holds the short fields. Two postings on one board share one
form template, so before writing a new essay, read the earlier application's
`metadata.drafts` and reuse the text the user already approved. On 22/10/2026 a
second posting on the same Ashby board was filled with fresh drafts and the user
asked for the first one back; the originals were recovered from that column.
`essay_final_note` records that the user may have edited the text after review,
so it can differ from what was sent.

`promotes_to` marks a question whose answer looks like it belongs in
`profile.jsonc`. When that turns out to be wrong — compensation expectations,
say, which are answered case by case rather than as one fixed fact — drop the
flag with `--clear-promotes-to` rather than leaving `promotions` listing it
forever. Put the reasoning for the reversal in the same `record` call so the
next reader learns from it.

## Review digest (`db/tools/review.py`)

The decision queue: your own open actions, what changed since you last looked,
follow-ups due, applications with their age and next action, the next roles
worth a look, pipeline health, and what the question bank now knows.

It is **one living file**, `artifacts/review.md`, rewritten in place. There are
no dated copies, because there is nothing to accumulate: the digest holds no
state. A stale line leaves because the row behind it was resolved in the
database, never because it was edited out of the text, and hand edits are lost
on the next rewrite. Every actionable line therefore carries the command that
closes it. The file is private (gitignored), because it names employers and
this repo is public.

Almost every line is derived from a row that exists for its own sake, so it
cannot drift. The exception is an action with no job, application or question
behind it ("create the resume variant"): nothing to derive it from, and a chat
scrollback is not a memory. Those live in `todos`, render as the leading
checkboxes in section 2, and disappear when closed. The page still holds
nothing; the row does.

Section 1 is the point of the format: it is computed against the `Refreshed:`
line the file carried last time, so reading it "from time to time" costs one
section instead of six, and the marker needs no table of its own.

**A change to what a query RETURNS needs a run against a real database.** The
pure selftest drives the helpers and never builds a digest from rows, so when a
status event was compared against a column that was missing from one SELECT
list, all 40 cases passed and the renderer raised `IndexError` on the first real
row. `python3 -m db.tools.review` on the live database is the cheap proof.

| Command | What it does |
|---|---|
| `python3 -m db.tools.review` | Rewrite `artifacts/review.md` and print what needs action |
| `digest --out PATH \| --stdout` | Write somewhere else, or print instead |
| `follow-up --app 3 --in-days 7 [--note "..."]` | Schedule a follow-up: an `application_events` row with `scheduled_for` |
| `submitted --app 6 [--method ...] [--confirmation URL] [--note "..."] [--date ISO]` | Record that the user sent it: both rows go to `applied` (the application with `applied_at`), an `applied` event is appended, and the 7-day follow-up reminder counts from `applied_at`. Refuses a second recording |
| `reply --app 6 --summary "..." [--details "..."] [--date ISO]` | Record contact FROM the employer that moves no status; this is what clears the follow-up reminder |
| `resolve --event 4 [--note "..."]` | Mark a scheduled follow-up done (`metadata.done`, `done_at`) |
| `dismiss --job 616 --reason "posting closed"` | Archive a lead, recording `metadata.reason_for_archive` |
| `todo --add "..." [--owner user\|agent] [--context "..."]` | Remember an action that has no row behind it |
| `todo` / `todo --close 3` | List the open ones, or close one |
| `selftest` | Check the follow-up decision logic on fixed cases |

### The follow-up reminder

Nothing runs in the background and nothing is "started" or "stopped": the
reminder is a line the digest derives on every rewrite, from two inputs.

1. **The date**: `applications.applied_at`, set by `review submitted` when the
   form went out.
2. **A contact check**: whether an `application_events` row of type
   `interview`, `offer`, `rejection` or `reply` exists for that application
   (`SIGNAL_EVENT_TYPES` in `db/tools/review.py`).

With no contact row and `applied_at` at least `FOLLOW_UP_AFTER_DAYS` (7) days in
the past, section 2 raises "Consider a follow-up" and section 3's next-action
cell changes from `nothing yet (follow up on day 7)` to `consider a follow-up
(out N days)`. Recording contact, or scheduling one with `follow-up --app N`,
changes those same lines. Only the suggestion is automatic; scheduling stays an
explicit command.

Our own `note` ("recon done", "form filled in one pass") and our own `follow_up`
rows are NOT contact, and must not be added to `SIGNAL_EVENT_TYPES`. When they
were, our own notes cleared the reminder, so the better an application was
documented the more reliably its reminder disappeared, and a freshly submitted
one read "no action (a reply is on record)" with nobody having replied. `reply`
is how contact that moves no status gets recorded.

A follow-up already sent is the second input, and it is not contact either. The
digest reads the newest `follow_up` row for the application (a plain one, or a
scheduled one marked done, dated by `done_at`) and, while it is inside the same
7-day window, replaces the suggestion with `followed up Nd ago; nudge after day
7`. Without that, an application stayed in section 2 asking for a follow-up the
day after one went out. Record a sent follow-up as its own `follow_up` row so
the date is real, and let the suggestion return once the window passes with
still no reply.

A `revised` bank answer is reported in section 6 but is not a task. Wording is
chosen per application, so the stored text differing from what one employer
received is the normal state of the bank; what carries forward is `reasoning`,
which `lookup` prints as `WHY` beside the text that went out.

"Next roles" sorts in four steps, and each one is a separate, tested rule:

1. **Can you take it?** `scanner.eligibility.scope_rank` puts worldwide, a
   `region_gated` list that names a region you are in (EMEA, MEA, Africa) and
   `unknown` in one group, ordered by score, because silence is not a bar and a
   Lagos role at 96 should not sit under a worldwide role at 38. A list that
   names only other regions, and `us_only`, stay below that group.
2. **Is it remote work or a relocation?** An office or hybrid posting abroad,
   and an `unknown` workplace type beside a named foreign city, sits below every
   remote posting. A local office in Nigeria stays in the main group. This is
   what keeps a 99-point Berlin requisition out of the top of a remote search.
3. **Employer history.** `adjust` is added to the score before the sort: -15 for
   each application sent in the last 90 days, -20 for each rejection in the same
   window, plus a named weight from `employer_weights` (see below). The raw
   score stays in the table so the decision is visible.
4. **Then the floor and the caps.** A posting older than 45 days leaves the
   table even while its board still lists it, the same role reposted under a new
   id is kept once, each employer is capped at two rows, and a score below 15 is
   only kept when `Matcher.admits()` calls the title a target role. The gate is
   shared with the scanner so the two cannot disagree about what a role is.

`employer_weights` is the named part: `python3 -m db.tools.review employer --set
"Company" --weight -25 --reason "why"` demotes every posting from that employer,
`--remove "Company"` drops it, and no flag lists them. It is a table rather than
a config file because it names employers and this repo is public. Use it for a
judgement the data cannot carry, such as requirements that make a rejection
likely; use the automatic weights for what the applications already say.

`skipped_countries` is the same shape for a place: `python3 -m db.tools.review
country --add <key> --term '<regex>' --reason "why"` hides every posting whose
`location` or `region_evidence` matches one of the patterns, `--remove <key>`
brings them back, and no flag lists them. Terms are regular expressions because
one country has several spellings on these boards: the name, a two-letter code
inside a city list, and a city that never names the country at all.

There is a second list, `--text-term`, matched against the posting text. It
exists because some boards leave the location field empty and put the place in
the first line of the ad ("Location - India (Remote)", "This is a fulltime
position based in Bangalore"), and those postings escaped the first list. Keep
it to phrasings that declare where the work sits, and it is applied only when
`location` and `region_evidence` are both empty: a company also names its
offices, its team and the places it has customers, so "India" anywhere in a
description proves nothing. The selftest holds the false positives that matter
(a team based abroad, a multi-region list, an office list) as cases.

A hidden posting is not archived: it stays in the pool, and the digest reports
how many it left out, so the decision is one row to delete rather than a
rescan. Use it for a place where an application cannot realistically convert; a
named office location that a candidate may relocate to is not that, and belongs
in `location_policy` instead.

An employer that has already received two applications inside seven days leaves
the table entirely and appears under it as cooling down, with the date the
window clears (`employer_cooldown`). Two applications make the case: a third
inside the week reads as spraying, and it costs nothing to wait, because the
employer's next requisition is worth more to them than our impatience. The rule
is derived from `applications.applied_at` on every rewrite, so there is no flag
to set and none to clear; a withdrawn or archived application does not count,
and neither does a row still waiting to be submitted.

`region_gated` means the posting names countries, and is a prompt to read that
list, not a verdict: EMEA includes Africa, so it is not a bar, and it sorts
above `unknown` for that reason. The same order decides the "nothing matched"
table, which lists the newest score-0 rows first (recency is real ordering
where a score of 0 is not) and omits any posting that already has an
application.

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

-- What a form is most likely to ask, how often, and whether it has been sent
SELECT question_key, kind, times_asked, last_asked_at, state, canonical_text
FROM questions_with_frequency
WHERE retired_at IS NULL ORDER BY times_asked DESC, last_asked_at DESC;

-- The exact wording and options a given form showed, most recent first
SELECT i.asked_at, i.field_label, i.field_type, i.options_seen, i.answer_given,
       j.company, j.title
FROM question_instances i
JOIN questions q ON q.id = i.question_id
LEFT JOIN jobs j ON j.id = i.job_id
WHERE q.question_key = 'us_sponsorship_required'
ORDER BY i.asked_at DESC;
```
