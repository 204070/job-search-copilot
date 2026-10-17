# Daily job-board scanning

`python3 -m scanner` fetches every enabled board according to its
`boards.scan_strategy` / `boards.scan_config`, dedupes, scores each new job
against `scanner/keywords.jsonc`, and appends new matches to
`logs/leads/YYYY-MM-DD.md`.

## Strategies

| strategy | handler | config keys | notes |
|---|---|---|---|
| `rss`     | `scanner/fetchers.fetch_rss`     | `feed_url` | RSS 2.0, namespace-tolerant; repairs bare `&`/double-encoded entities (WWR, Himalayas, Real Work From Anywhere) |
| `api`     | `scanner/fetchers.fetch_api`     | `source` (`remotive`/`remoteok`), `endpoint` | public JSON APIs |
| `jobspy`  | `scanner/fetchers.fetch_jobspy`  | `source`, `search_term`, `location`, `results_wanted`, `hours_old` | needs `pip install python-jobspy` |
| `html`    | `scanner/fetchers.fetch_html` (mode-dispatched) | `mode` (+ mode keys: `profile_dir`, `scrolls`, `cap` for `x_bookmarks`) | browser-scraped boards; unknown `mode` = "not scanned yet" |
| `manual`  | never auto-scanned | — | e.g. saved Google searches |

Active sources: WWR (programming RSS), Himalayas (RSS), Real Work From
Anywhere (RSS), Remotive + RemoteOK (APIs), Indeed/LinkedIn/ZipRecruiter
(JobSpy), X Bookmarks (Playwright, your own session). ZipRecruiter currently
returns 403 from this network; LinkedIn rate-limits. 6 `html` boards stay
pending — reconnaissance status for each lives in `boards.notes` (migration
0009); paywalled/dormant boards (Remote4Africa, RemoteAfrica, Crossover) are
`manual`, Cleverjobs is disabled.

## Dedupe

- `ux_jobs_url` (global, on `lower(url)`): the same posting URL = one job,
  even when two boards link to the same ATS page.
- `ux_jobs_board_source_ref`: a board's own id/guid is stored once per board.
- Re-discovered jobs only get `last_seen_at` refreshed, never duplicated.
- Known limit: identical roles at the same company posted to two boards with
  *different* URLs (e.g. "Copy of ..." on Indeed) can appear twice.

## Matching

- Keywords come from `scanner/keywords.jsonc` (committed example — replace
  terms with your own resume's; edits apply on the next run, no migrate).
  Entries: `term`, `field` (`title` = OR-gate, `any` = weighted coverage),
  `weight`, `enabled`; optional hand-written `pattern` regex override for
  alternations/optional words plain terms can't express (invalid patterns
  raise at load). Plain terms compile to case-insensitive `\bterm\b`.
- Score = 100 × matched `any` weight / total weight; `MATCH_MIN_SCORE`
  env (default 15). After editing entries, scores change on the next run;
  old stored `match_score` values are historical, rescore by re-running.
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
