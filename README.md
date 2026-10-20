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

1. **`db/seeds/boards.jsonc`** — where jobs come from. Copy the template
   first (`cp db/seeds/boards.example.jsonc db/seeds/boards.jsonc`); your copy
   is gitignored. Disable what you don't use (`"enabled": 0`), tune JobSpy
   `search_term`/`location`, and replace the account ids with your own (the
   OpenCLI profile id comes from `opencli profile list`). Then
   `python3 -m db.seed` (re-run any time; `--dry-run` previews, `--prune`
   disables boards you removed). Seeding with no copy reads the example.
2. **`scanner/keywords.jsonc`** — how jobs score. Copy the template
   (`cp scanner/keywords.example.jsonc scanner/keywords.jsonc`), then replace
   the terms with words from your own résumé. `title_exclude` regexes veto a posting
   outright (so a support advert that name-drops Kubernetes stays at 0),
   `title_admit` regexes are the gate, and `keywords` are weighted coverage.
   `core_weight` sets what a full match means, so the long tail extends the
   scale instead of compressing it. Plain terms match word-boundaries; use
   `pattern` for regex (alternations, optional words). Edits apply to new
   postings immediately, and to stored ones via
   `python3 -m scanner.tools.rescore`.
3. **`artifacts/` (private, gitignored)** — everything personal. Start from
   the placeholders, then edit them:

   ```bash
   cp artifacts/resume.example.md       artifacts/resume.md
   cp artifacts/cover-letter.example.md artifacts/cover-letter.md
   cp artifacts/profile.example.jsonc   artifacts/profile.jsonc
   ```

   `profile.jsonc` is the one that matters most: it carries your name, email,
   phone, location, links, work-authorization answers, self-identification
   answers, targeting and default pay, so a form fill never guesses. Every
   block in `profile.example.jsonc` has a comment saying what reads it. Your
   resume PDF goes at the path `resumes.canonical_pdf` names, and that file
   name is what a recruiter sees. See `artifacts/README.md`.

   It is a long file, but you do not have to type it by hand. Give an AI agent
   your resume and `artifacts/profile.example.jsonc`, and ask it to write
   `profile.jsonc` from them, keeping the comments. Three blocks are not on a
   resume, so tell the agent to leave them empty and ask you instead:
   `compensation`, `work_authorization` and `self_identification`. Those are
   answers you give, not facts to infer.

Nothing here phones home: all state is the local SQLite file + your files.

## Where things live

| Path | What |
|---|---|
| `db/jobs.db` | SQLite: `boards` → `jobs` → `applications` → `application_events`, plus the question bank (`questions`, `question_instances`) |
| `scanner/` | fetchers (rss / api / jobspy / html modes) + store + matcher + region scope + CLI |
| `scanner/tools/` | helpers: `add_job`, `classify`, `rescore`, `enrich_bookmarks`, `enrich_companies`, `probe_boards`, `x_login` |
| `db/tools/questions.py` | the question bank CLI: `lookup` / `record` / `frequency` / `promotions` / `digest` |
| `db/migrations/` | numbered schema files; `python3 -m db.migrate` applies new ones |
| `db/seeds/` | curated boards: your `boards.jsonc` (gitignored) copied from `boards.example.jsonc`; `python3 -m db.seed` syncs them |
| `scanner/keywords.jsonc` | scoring rules (admit/exclude regexes + weighted terms), yours from `keywords.example.jsonc`; stored jobs need `python3 -m scanner.tools.rescore` |
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

## Triage: can you actually take the job?

A score says a posting matches your résumé. It says nothing about whether the
employer will hire someone in your country — and the boards are mostly
US-facing, so "Remote, USA" used to look exactly like "Remote". Every job now
carries a `region_scope` tag read from the posting's own wording:

| scope | meaning |
|---|---|
| `worldwide` | the posting says it hires anywhere |
| `us_only` | it demands US residence or US work authorisation |
| `region_gated` | it names specific countries or regions (a list to check) |
| `unknown` | it states no restriction — the common case, and **not** a bar |

It tags the **stated restriction, never the company's home country**: a US
company that says just "Remote" stays `unknown`, because plenty of them hire
worldwide, and "US timezones"/"US hours" are overlap, not bars. Only
`us_only` is a real bar, and nothing is filtered out — the daily report just
sorts matches by scope first, so a role you can't take can't bury one you can.
`jobs.region_evidence` keeps the phrase that produced the tag, and
`python3 -m scanner.tools.classify --examples 3` shows both.

```bash
python3 -m scanner.tools.classify                     # re-tag, print counts
python3 -m scanner.tools.classify --examples 3         # audit by phrase
python3 -m scanner.tools.rescore --top 20              # re-score after editing the scoring config
python3 -m scanner.tools.enrich_companies              # employer hidden in an RSS title
python3 -m scanner.tools.enrich_bookmarks              # job hidden in a bookmarked tweet
python3 -m scanner.eligibility                         # the classifier's own test table
```

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
python3 -m db.tools.questions retire --key <slug>          # never reuse this one
python3 -m db.tools.questions digest --kind application \
    --out artifacts/faqs/application-faq.md               # regenerate the FAQ
```

A `lookup` that returns nothing is the signal that a question is new; a
question asked twice has earned a stable key. `artifacts/faqs/*.md` are
generated from the bank (private — `artifacts/` is gitignored), so record
answers here and regenerate, never hand-edit both.

An answer's state is derived from the ledger, never approved by hand: `sent`
means the stored text is exactly what an employer received, `revised` that it
went out and has changed since (so nobody has read the current wording), and
`unsent` that no submitted application has carried it. Submitting *is* the
review; `retire` is the one state a human writes.

## Cron

The daily `python3 -m scanner` run (`cron/daily_scan.sh`, installed via
`cron/install.sh` — 06:30) covers every enabled scanner board; a failing
board is reported in the run's "Errors" section without stopping the others.
