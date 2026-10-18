# Daily job-board scanning

`python3 -m scanner` fetches every enabled board according to its
`boards.scan_strategy` / `boards.scan_config`, dedupes, scores each new job
against `scanner/keywords.jsonc`, and appends new matches to
`logs/leads/YYYY-MM-DD.md`.

## Strategies

| strategy | handler | config keys | notes |
|---|---|---|---|
| `rss`     | `scanner/fetchers.fetch_rss`     | `feed_url` | RSS 2.0, namespace-tolerant; repairs bare `&`/double-encoded entities; reads `content:encoded` when `description` is empty; recovers an employer embedded in the title (WWR, Himalayas, Real Work From Anywhere) |
| `api`     | `scanner/fetchers.fetch_api`     | `source` (`remotive`/`remoteok`/`mapped`), `endpoint` | public JSON APIs; `mapped` needs no code — see below |
| `jobspy`  | `scanner/fetchers.fetch_jobspy`  | `source`, `search_term`, `location`, `results_wanted`, `hours_old` | needs `pip install python-jobspy` |
| `html`    | `scanner/fetchers.fetch_html` (mode-dispatched) | `mode` (+ mode keys: `profile_dir`, `scrolls`, `cap` for `x_bookmarks`) | browser-scraped boards; unknown `mode` = "not scanned yet" |
| `manual`  | never auto-scanned | — | e.g. saved Google searches |

### `source: mapped` — a JSON board with no new code

`scan_config` names the list and the field paths:

```jsonc
{ "source": "mapped", "endpoint": "https://jobicy.com/api/v2/remote-jobs?count=50",
  "items": "jobs", "source_ref": "id",
  "fields": { "title": "jobTitle", "company": "companyName", "url": "url",
              "location": "jobGeo", "description": "jobDescription",
              "posted_at": "pubDate" } }
```

Recognised `fields` keys are the ones `store.upsert_job` takes; `description`
is HTML-stripped, `location`/`company` are trimmed to `None` when empty. Add a
branch in `fetch_api` only when a board needs real logic.

Active sources: WWR (programming RSS), Himalayas (RSS), Real Work From
Anywhere (RSS), Jobspresso (dev-category RSS), Jobicy (mapped API), Remotive +
RemoteOK (APIs), Indeed/LinkedIn/ZipRecruiter (JobSpy), X Bookmarks
(OpenCLI/Playwright, your own session). ZipRecruiter currently returns 403 from
this network; LinkedIn rate-limits. 6 `html` boards stay pending —
reconnaissance status for each lives in `boards.notes` (migration 0009);
paywalled/dormant boards (Remote4Africa, RemoteAfrica, Crossover) are
`manual`, Cleverjobs is disabled.


## Region scope: can you actually take this job?

The boards are overwhelmingly US-facing (Indeed/LinkedIn) plus region-gated
marketplaces, so an unread board made "Remote, USA" and "Remote" look
identical. `jobs.region_scope` tags where each posting says it will hire:

| scope | meaning |
|---|---|
| `worldwide` | the posting says it hires anywhere |
| `us_only` | it demands US residence or US work authorisation |
| `region_gated` | it names specific countries or regions (a list to check) |
| `unknown` | it states no restriction — the common case, and **not** a bar |

It describes the **stated restriction, never the company's home country**: a US
company with no restriction stays `unknown`, because plenty of them hire
worldwide. Only `us_only` is a real bar. "US timezones"/"US hours" describe
overlap and are NOT bars. Nothing is ever filtered out on this basis — the tag
groups the board; the daily report sorts matches by scope first, so a role you
can't take no longer buries one you can. `jobs.region_evidence` keeps the
phrase that produced the tag.

### Not every `region_gated` list excludes you

`region_gated` covers two opposite situations, and the tag alone cannot tell
them apart, so the sort reads the evidence phrase as well
(`eligibility.scope_rank`, shared by the scanner report and the digest):

| order | scope | why |
|---|---|---|
| 1 | `worldwide` | open to anyone |
| 2 | `region_gated` naming a region you are in | EMEA, MEA, Africa, Nigeria: officially open to you |
| 3 | `unknown` | states nothing, so not a bar, but not a promise either |
| 4 | `region_gated` naming only other regions | Europe alone, the Americas, APAC, the Gulf: read the list |
| 5 | `us_only` | the only real bar |

A named region that includes West Africa is better information than silence,
which is why it ranks above `unknown` instead of below it. `EMEA` includes
Africa; `Middle East` and `GCC` do not, so they stay in row 4. Short board
abbreviations (`AMER`, `EMEA`, `APAC`, `MEA`) are location strings in their own
right; a missing one used to read as "no restriction stated" rather than as a
list. `covers_home()` is the only place that vocabulary lives, and
`python3 -m scanner.eligibility` checks it alongside the tags.

```bash
python3 -m scanner.tools.classify              # re-tag every job, print counts
python3 -m scanner.tools.classify --examples 3  # audit the tags by phrase
python3 -m scanner.tools.classify --dry-run
```

The rules and their worked cases live in `scanner/eligibility.py`; run
`python3 -m scanner.eligibility` to see the table the classifier is specified
by. Classification is a separate pass over stored rows (not part of insert)
because a re-discovered job keeps its original row, so a tag written at insert
time would never refresh. `python3 -m scanner` runs it at the end of every scan.

## Repairs for rows a re-scan cannot fix

`upsert_job` only refreshes `last_seen_at` for a job it already has, so an
improved extractor never reaches rows stored earlier. Three idempotent tools
re-derive those in place:

```bash
python3 -m scanner.tools.enrich_bookmarks   # pull company/location/role out of bookmarked tweets
python3 -m scanner.tools.enrich_companies   # recover an employer left inside an RSS title
python3 -m scanner.tools.rescore            # re-derive match_score after the scoring config changed
```

## Dedupe

- `ux_jobs_url` (global, on `lower(url)`): the same posting URL = one job,
  even when two boards link to the same ATS page.
- `ux_jobs_board_source_ref`: a board's own id/guid is stored once per board.
- Re-discovered jobs only get `last_seen_at` refreshed, never duplicated.
- Known limit: identical roles at the same company posted to two boards with
  *different* URLs (e.g. "Copy of ..." on Indeed) can appear twice.

## Matching

- Rules come from `scanner/keywords.jsonc` (committed example — replace the
  terms with your own; edits apply on the next run, no migrate):
  - `title_exclude` — regexes that veto a posting outright, checked first. This
    is what keeps a "Support Engineer" advert that name-drops Kubernetes from
    scoring like an infrastructure role.
  - `title_admit` — regexes; the title must match at least one. The in-scope
    role families are legible across these two lists: engineering, product and
    forward-deployed IC roles, architects, SRE, and Engineering Manager. The
    manager family is a target role (18/10), which is why the blanket
    `\bmanager\b` veto is gone and the manager kinds that are *not* engineering
    management are named instead; director and above deliberately stays out.
  - `core_weight` — the weight tier that counts as a full match (see below).
  - `keywords[]` — `term`, `weight`, `enabled`; optional hand-written `pattern`
    regex override for alternations/optional words plain terms can't express
    (invalid patterns raise at load). Plain terms compile to case-insensitive
    `\bterm\b`, so `rust` never hits `robust`. A legacy `field: "title"` entry
    still loads, as one more admit pattern. Two kinds of signal live in this
    list and are commented apart: stack terms (weight 3 is the verified core)
    and location affinity (`nigeria`, `lagos`), because an advert that names
    your country or city is telling you it will hire where you are.
- Score = 100 × matched weight / target, capped at 99, where `target` is the
  weight of the entries at or above `core_weight`. The target is the point: a
  posting naming the whole core tier scores 100, and adding another incidental
  term to the list cannot lower everybody else's score. Without `core_weight`
  the target is the total weight, which is the older and dilution-prone shape.
- `MATCH_MIN_SCORE` env (default 15) is the lead threshold.
- A stored `match_score` is written at insert time and never refreshed by a
  later scan (`upsert_job` only touches `last_seen_at`), so after editing the
  config run `python3 -m scanner.tools.rescore` — `--dry-run` first, `--top 20`
  to see what the new ranking actually puts first, `--only-below 15` for a cheap
  pass over the low end.
- A score answers "how much of the stack does this advert name", nothing else.
  Two neighbouring questions have their own tools: whether the title is this
  kind of role at all (`Matcher.admits()`, which reports use so their notion of
  "looks like a role" cannot drift from the scorer's), and whether the posting
  is open to where the person lives (`region_scope`, above).
- **Classifier upgrade path**: replace the internals of
  `scanner/keywords.Matcher.score()` (or add `scanner/classifier.py` with the
  same contract) — nothing else changes.

## Cron

`./cron/install.sh` — idempotent; installs `30 6 * * * .../daily_scan.sh`,
backs up the previous crontab first. Logs append to `logs/scan.log`; per-day
reports land in `logs/leads/`.

Manual runs:

    python3 -m scanner                  # all enabled non-manual boards
    python3 -m scanner --board RemoteOK # one board
    python3 -m scanner --dry-run        # fetch + report, no writes
    python3 -m scanner --min-score 25   # stricter lead threshold

## X bookmarks

`X Bookmarks` is an `html` board with `mode: x_bookmarks_cli`: the scanner
shells out to [OpenCLI](https://github.com/jackwener/opencli)'s Browser
Bridge, which reads your bookmarks **from your real logged-in Chrome** — no
automation browser, no session import, no bot detection. (The official X API
has no bookmark read below Pro tier, and v1.1 — which had
`statuses/bookmarks/list` — shuts down Sep 2026.)

- One-time setup: install OpenCLI (`npm i -g opencli`), load the Browser
  Bridge extension from its GitHub releases into Chrome (Developer mode →
  Load unpacked), log into X in that Chrome. `opencli doctor` diagnoses the
  whole chain (daemon / extension / connectivity).
- This board is **manual-first**: keep Chrome open and run
  `python3 -m scanner --board 'X Bookmarks'` when you want to pull. Under
  cron it reports "bridge not connected" on days Chrome is closed — other
  boards are unaffected.
- Several Chrome profiles connected? Pin the X-logged-in one in
  `scan_config.profile` (ids from `opencli profile list`).
- Every bookmark is stored (a tweet with no external link keeps the tweet
  URL as the job URL); t.co links are resolved, X-internal targets
  (media/profile links) are skipped, and one tweet with several links
  becomes several jobs.
- Tweets are **read as postings**, not stored as raw noise: `scanner/bookmarks.py`
  pulls the company ("Acme is expanding", "Join Northwind Software",
  "brightpath (yc-w23)"), the place ("(Spain)", "Remote", a named city) and the
  role ("Senior Full Stack Developer") out of the prose, and flags `job_like` in
  metadata. A tweet that reads like nothing in particular keeps its text and
  `Unknown`. It is a heuristic on informal writing, so it never invents a value;
  run `python3 -m scanner.bookmarks` for the worked cases. Rows stored before
  the extractor existed are repaired with `scanner.tools.enrich_bookmarks`.
- Intent beats score: `jobs.bookmarked_at` records the first sighting and
  survives URL dedupe even when another board already had the job; the daily
  report lists all bookmarked jobs under "Bookmarked on X", regardless of
  `MATCH_MIN_SCORE`.
- Dormant fallback (`mode: x_bookmarks`): the Playwright fetcher in
  `scanner/fetchers.py` reads bookmarks from a persistent logged-in profile
  at `secrets/x_profile`, created via `python3 -m scanner.tools.x_login`
  (cookie import preferred — see its `--help`). Kept for when Chrome can't
  be open; note X's risk engine downgrades sessions it catches headless,
  so expect to re-import cookies if it fires.

## Adding a board

1. Insert a `boards` row (`kind='job_board'`) with `scan_strategy` +
   `scan_config` via a migration, or directly for a one-off.
2. Run `python3 -m scanner.tools.probe_boards` — it reports, per `html` board,
   whether a real feed/sitemap/JSON-LD/JSON endpoint exists (filters out SPA
   "200 HTML fallback" false positives). Prefer the cheapest path:
   `rss` flip → existing `api`/`jobspy` → generic parser → per-board code.
3. For a new API shape, add a branch in `fetch_api`; for a new feed just set
   `feed_url`.
4. Re-run `python3 -m db.migrate`, then `python3 -m scanner --board NAME`.
