# Job Search Copilot

Finds suitable roles across job boards **and your X (Twitter) bookmarks**,
scores them against your resume keywords, and tracks applications from first
lead to offer. Optimised for lead quality and interview conversion — not
application volume.

## Quickstart

```bash
python3 -m db.migrate                 # schema (idempotent)
python3 -m db.seed                   # curated boards from db/seeds/*.jsonc
python3 -m scanner                    # scan all enabled boards
```

Reports print to stdout and append to `logs/leads/YYYY-MM-DD.md`
(accumulating across the day's runs). New matches = score ≥ threshold;
X-bookmarked leads are listed **regardless** of score ("Bookmarked on X").

> **Requires SQLite with FTS5.** `python3 -m db.migrate` creates the question
> bank's full-text index, and a Python whose SQLite was built without FTS5 will
> fail on migration `0002`. Check first:
>
> ```bash
> python3 -c "import sqlite3; sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(x)')"
> ```
>
> No error means you're set. If it fails, use a Python built with FTS5
> (the common case: python.org and most distro builds have it). Everything
> else in the repo needs only stock `sqlite3`.

### First run: make it yours

The repo ships working EXAMPLE config — three files to review before your
first real scan:

1. **`db/seeds/boards.jsonc`** — where jobs come from. Disable what you
   don't use (`"enabled": 0`), tune JobSpy `search_term`/`location`, and set
   the X Bookmarks `scan_config.profile` to your own OpenCLI profile id
   (`opencli profile list`). Then `python3 -m db.seed` (re-run any time;
   `--dry-run` previews, `--prune` disables boards you removed).
2. **`scanner/keywords.jsonc`** — how jobs score. Replace the example terms
   with words from your own resume: `field: "title"` entries are the OR-gate
   (a posting scores 0 unless its title matches one), `field: "any"` entries
   are weighted coverage. Plain terms match word-boundaries; use `pattern`
   for regex (alternations, optional words). Edits apply on the next scan —
   no migrate needed.
3. **`artifacts/` (private, gitignored)** — drop in your resume
   (`artifacts/resume.md` from the example), base cover letter, and
   `artifacts/profile.jsonc` (name, email, phone, location, links) so
   application fills never guess. See `artifacts/README.md`.

Nothing here phones home: all state is the local SQLite file + your files.

## Where things live

| Path | What |
|---|---|
| `db/jobs.db` | SQLite: `boards` → `jobs` → `applications` → `application_events`, plus the question bank (`questions`, `question_instances`) |
| `scanner/` | fetchers (rss / api / jobspy / html modes) + store + matcher + CLI |
| `db/tools/questions.py` | the question bank CLI: `lookup` / `record` / `frequency` / `promotions` / `digest` |
| `db/migrations/` | numbered schema files; `python3 -m db.migrate` applies new ones |
| `db/seeds/` | curated boards (`boards.jsonc`); `python3 -m db.seed` syncs them |
| `scanner/keywords.jsonc` | scoring terms (plain or regex `pattern`); edits apply on next scan |
| `logs/leads/` | daily scan reports (log output, gitignored) |
| `artifacts/` | **your private documents** — resume, cover letters… gitignored; see `artifacts/README.md` |
| `_docs/` | deeper docs: [`scanning.md`](_docs/scanning.md), [`jobs-db.md`](_docs/jobs-db.md) |

## Sources: every job knows where it came from

`jobs.board_id` → `boards` is the **source** of a job (its origin board).
Browse it directly:

```sql
SELECT id, title, source, status FROM jobs_with_source ORDER BY id DESC;
```

Boards scan via `scan_strategy` (`rss` / `jobspy` / `api` / `html`;
`manual` / `disabled` are never scanned). Strategy-specific settings live in
the board's `scan_config` JSON.

### X bookmarks

```bash
python3 -m scanner --board 'X Bookmarks'
```

Pulls your bookmarks through [OpenCLI](https://github.com/jackwener/opencli)'s
OpenCLI extension — it reads from **your real logged-in Chrome** (keep Chrome
open; `opencli doctor` diagnoses daemon/extension/session). No API key, no
automation browser. Every bookmark is stored as a lead (tweet URL kept when
there's no external link), t.co links are resolved, and intent is recorded in
`jobs.bookmarked_at`. Manual-first: run it when you want; under cron it
degrades gracefully on days Chrome is closed.

### Manual leads

Add jobs that didn't come from a scan — referrals, meetups, friends:

```bash
python3 -m scanner.tools.add_job --title "Senior Backend Eng" \
    --url https://boards.example.com/job/123 --company Acme \
    --note "referred by Jane" --workplace remote
```

Hand-added jobs land on the `Manual` board (never scanned) and are scored
like scanned jobs. Any unknown `--board NAME` is created on the fly, also
marked non-scannable — so e.g. `--board "Referral: Jane"` just works.

## The question bank: stop re-answering the same form question

Forms ask the same things (compensation, sponsorship, "which Go concurrency
patterns do you favour"). Those answers live in the database in two layers, so
*"is this frequently asked?"* is a `COUNT` rather than a judgement call:

- `questions` — one canonical row per distinct question: the answer, the
  reasoning behind it, and the wordings a form might use. Facts point at
  `artifacts/profile.jsonc` (`answer_source = 'profile:$.location.city'`) so
  there is one source of truth.
- `question_instances` — one row per time a form actually asked it: the date,
  the job, and the options that form showed.

```bash
python3 -m db.tools.questions lookup "compensation"      # before you fill
python3 -m db.tools.questions record --key <slug> \
    --question "<the form's question>" --answer "<the answer>" \
    --label "<this form's label>" --field-type text --required \
    --application-id <id>                                 # after you fill
python3 -m db.tools.questions frequency                   # what recurs
python3 -m db.tools.questions promotions                  # facts -> profile.jsonc
python3 -m db.tools.questions digest --kind application   # regenerate the FAQ
```

A `lookup` that returns nothing is the signal that a question is new; a
question asked twice has earned a stable key. `artifacts/faqs/*.md` are
generated from the bank (private — `artifacts/` is gitignored), so record
answers here and regenerate, never hand-edit both.

## Cron

The daily `python3 -m scanner` run (`cron/daily_scan.sh`, installed via
`cron/install.sh` — 06:30) covers every enabled scanner board; a failing
board is reported in the run's "Errors" section without stopping the others.
