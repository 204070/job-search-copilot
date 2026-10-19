# Daily job-board scanning

`python3 -m scanner` fetches every enabled board according to its
`boards.scan_strategy` / `boards.scan_config`, dedupes, scores each new job
against `scanner/keywords.jsonc`, and appends new matches to
`logs/leads/YYYY-MM-DD.md`.

## Strategies

| strategy | handler | config keys | notes |
|---|---|---|---|
| `rss`     | `scanner/fetchers.fetch_rss`     | `feed_url`, or `feed_urls` for several | RSS 2.0, namespace-tolerant; repairs bare `&`/double-encoded entities; reads `content:encoded` when `description` is empty; recovers an employer embedded in the title (WWR, Himalayas, Real Work From Anywhere); a posting listed in two of a board's category feeds is stored once |
| `api`     | `scanner/fetchers.fetch_api`     | `source` (`remotive`/`remoteok`/`mapped`), `endpoint` | public JSON APIs; `mapped` needs no code — see below |
| `jobspy`  | `scanner/fetchers.fetch_jobspy`  | `source`, `search_term`, `location`, `results_wanted`, `hours_old` | needs `pip install python-jobspy` |
| `html`    | `scanner/fetchers.fetch_html` (mode-dispatched) | `mode` (+ mode keys: `pages`, `details`, `delay_ms` for the list parsers; `profile_dir`, `scrolls`, `cap` for `x_bookmarks`; `url`, `profile`, `session`, `js_file`, `tries`, `wait_ms` for `opencli_eval`; `on_demand` for any of them) | browser-scraped and server-rendered boards; unknown `mode` = "not scanned yet" |
| `manual`  | never auto-scanned | — | e.g. saved Google searches, dead boards |

Two config keys cut work out of a run without changing what a board is:

- **`on_demand`** keeps a board out of a full run (`python3 -m scanner`): it
  scans only when named, `python3 -m scanner --board NAME`. X Bookmarks is set
  this way, because it reads your own logged-in Chrome and you want to decide
  when that happens. The run report names it and says so rather than staying
  silent. (`scan_strategy: manual` is the stronger form: never scanned at all,
  even when named, which is right for a board with nothing to fetch.)
- **`details`** asks for one extra request per *new* posting, described under
  [Server-rendered list boards](#server-rendered-list-boards-jsgurujobs-javascript_jobs).

The `html` modes, cheapest first:

| mode | what it reads | code |
|---|---|---|
| `jsgurujobs`, `javascript_jobs` | plain server-rendered listing pages, fetched with `_http_get` and parsed by anchored patterns | `scanner/html_boards.py` (pure parsers + selftest) |
| `opencli_eval` | a page whose data only a browser can reach (Cloudflare 403, client-side rendering): read from your own Chrome through OpenCLI's bridge | fetcher in `scanner/fetchers.py`, site adapter in `scanner/js/<js_file>` |
| `x_bookmarks_cli` | your X bookmarks, same bridge | `scanner/fetchers.py` |
| `x_bookmarks` | your X bookmarks from a persistent Playwright profile (dormant fallback) | `scanner/fetchers.py` |


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

Active sources: WWR (three category feeds: programming, full-stack, devops),
Himalayas (RSS), Real Work From Anywhere (RSS), Jobspresso (dev-category RSS),
JS Guru Jobs and JavaScript Jobs (server-rendered HTML lists, with the posting's
own page read for new rows), Jobicy (mapped API), Remotive + RemoteOK (APIs),
Indeed/LinkedIn/ZipRecruiter (JobSpy), HiringCafe and Work at a Startup
(browser-read searches, need Chrome), X Bookmarks (OpenCLI/Playwright, your own
session — `on_demand`). ZipRecruiter currently returns 403 from this network;
LinkedIn rate-limits. 6 `html` boards stay pending — reconnaissance status for
each lives in `boards.notes` (migration 0009); paywalled/dormant boards
(Remote4Africa, RemoteAfrica, Crossover) are `manual`, Cleverjobs is disabled.

## Server-rendered list boards (`jsgurujobs`, `javascript_jobs`)

Both boards publish no feed and no JSON, but their listing pages arrive fully
rendered, so no browser is involved: `fetch_html_list` walks `pages` listing
pages and hands each to the parser named by `mode`. The parsers live in
`scanner/html_boards.py`, are pure (HTML in, store-shaped rows out) and are
checked against trimmed real card markup by `python3 -m scanner.html_boards`,
which is the point: a board's markup change should fail a selftest, not a scan.

Two rules those parsers follow, because both boards mix the two ideas:

- **The card's country span is the employer's place, not the eligibility.**
  JS Guru Jobs prints `Location: Armenia` next to `Work Format: Remote /
  Worldwide`, and the posting's own text says "100% remote | Global team": the
  badge is what the region classifier must read, so a Worldwide badge becomes
  `jobs.location` and the raw place stays in `metadata.employer_location`.
- **The card is stored first, the advert second.** These boards keep the
  description on the posting's own page, so `details: true` reads it, one
  request per posting (`delay_ms`, default 250, spaces them out) — but only for
  postings the store holds no text for. On a normal run that is the handful of
  postings new since last time; a posting already stored with text is skipped,
  and a page that failed is left without text, which is exactly what asks for
  it again next run. Measured on 19/10: first fill of both boards 244 s (66
  postings, javascript.jobs taking most of it at ~2.7 s a page), then 5 s and
  4 s per run.

A row stored before it had text adopts the advert through `upsert_job`'s one
exception (see [Dedupe](#dedupe)), and the score comes with it, so nothing has
to be repaired by hand afterwards. The date on the detail page replaces the
card's relative age ("20 hours ago"), which is why `posted_at` on these rows is
an exact day.

javascript.jobs serves a `JobPosting` JSON-LD block on its posting pages, but
not always valid JSON: members run together with no comma, strings carry raw
newlines, the last member is followed by a trailing comma. About one posting in
ten failed a document parse over damage in an unrelated member, so the fields
are matched one by one and unescaped individually (`_ld_string`) — the parser's
selftest feeds it the broken shape on purpose.

## HiringCafe (`mode: opencli_eval`)

HiringCafe answers plain HTTP with a Cloudflare 403, but its search results
arrive server-rendered into `window.__NEXT_DATA__.props.pageProps.ssrHits`
(120 rows for one search page), and each row carries the employer's own
`apply_url`. So the board is read the way X Bookmarks is: through OpenCLI's
Browser Bridge, out of your own logged-in Chrome.

The scanner opens `scan_config.url` in a new background tab, evaluates
`scanner/js/<js_file>` in the page, closes the tab, and normalises what came
back. The adapter is the site's whole adapter, and the fetcher's contract with
it is three lines: one expression, returning a JSON string of store-shaped
rows, or `null` while the page is still loading (that `null` is what makes the
fetcher retry instead of accepting an empty page). Mechanism and command
shapes: `_docs/tooling.md`.

- Needs Chrome open; the run reports the bridge error on days it is not (like
  X Bookmarks, and other boards are unaffected).
- Rows carry the employer's own posting URL, so dedupe lands on the real ad
  (a row already stored from another board counts as "already known").
- The search is yours, verbatim, in `scan_config.url`: query `software`,
  workplace types Remote/Hybrid/Field, newest first. Worth knowing what that
  returns: of a 120-row page, 79 came back `hybrid`, 30 `remote` and 10 with no
  type at all, and the region tag split 66 `region_gated` / 42 `us_only` /
  11 `unknown`. Tighten the URL (drop `Hybrid`/`Field`, or add a country) if the
  volume is not worth it.


## Work at a Startup (`mode: opencli_eval`, no detail fetch)

Y Combinator's own board has no feed and no list worth parsing. Checked
19/10/2026, cheapest path first: `/jobs.rss` and `/jobs.json` answer 406 (the
Rails route has no rss or json format), `/feed`, `/rss.xml` and `/sitemap.xml`
answer 404, `robots.txt` is empty, and the alternate link on
`ycombinator.com/jobs` is the blog feed. The pages that do render a list serve a
28-row sample into their Inertia payload and ignore the query string completely
(the same 28 ids with the filters, and again for `page=2`).

What the search actually is: Algolia, index `WaaSPublicCompanyJob_production`.
Each page load mints a search credential into `window.AlgoliaOpts` (renewed from
`/jobs_algolia_credential.json` when it lapses, `valid_until` about a day out),
so it cannot be stored, and plain HTTP cannot do this at all: the credential the
public pages mint is tag filtered to `(none)` and answers 0 hits to every query,
while the signed-in one is tagged `jobs_applicant`. So this board is read the way
HiringCafe and X Bookmarks are, through the Bridge, out of your logged-in
Chrome: `scanner/js/workatastartup_search.js` opens `scan_config.url`, asks the
page for that credential, queries the index itself and returns the rows.

- The search is the site's own filter bar (engineering, full time, no US visa
  required) plus two clauses the bar has no control for, both in the adapter and
  both measured on 19/10/2026: **remote-capable ads only** (228 of the 759) and
  **posted within about 18 months** (116 of the 228; the remote set is 76 ads
  from 2026, 53 from 2025, and 105 older). An ad that says the work is on site in
  Bengaluru or San Francisco is not a job someone in Lagos can take, and WaS
  serves ads from 2018 onwards with no closed or expired field (its own
  "archived" wording is applicant vocabulary, identical on every ad), so age is
  the only liveness signal there is. 116 rows in 3 requests, 10 s warm.
- The index stores the whole advert inline (2-4 KB), so this board needs no
  `details` fetch and every row scores on its description.
- `url` is the public posting on `ycombinator.com` (Algolia's `search_path`);
  the WaS page `/jobs/<id>` rides in metadata.
- **An expired session is an error, not an empty board.** Signed out, the page
  carries either no credentials or the public `(none)` ones, and the adapter
  throws saying which, so the run's `### Errors` section and `logs/leads/` name
  it instead of reporting "0 fetched". Sign in at workatastartup.com, rescan.


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

Boards also write a place as "City, Region, CC" ("San Francisco, CA, US",
"Bengaluru, KA, IN", "London, England, GB"). A trailing two-letter code is read
as a country and spelled out to the name the patterns know, but only where the
string says which it means: with three parts ("Berlin, Berlin, DE") the code is
a country, and a code that is not also a US postal code is one wherever it
appears ("Remote, ZM", "TW"). "Chesapeake, DE" is left alone, because that
string is Delaware exactly as easily as Germany, and a bare "CA" is left alone
for the same reason. Until 19/10/2026 no code was read at all, which filed 649
of the 759 Work at a Startup rows as `unknown`: they now split 406 `us_only` /
260 `region_gated` / 92 `unknown`, and the re-tag moved 570 rows across the
whole pool (`python3 -m scanner.tools.classify`).

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

`upsert_job` refreshes `last_seen_at` for a job it already has, and adds a
description it never had (with the score that description earns) — nothing else.
So an improved extractor never reaches rows stored earlier, and three idempotent
tools re-derive those in place:

```bash
python3 -m scanner.tools.enrich_bookmarks   # pull company/location/role out of bookmarked tweets
python3 -m scanner.tools.enrich_companies   # recover an employer left inside an RSS title
python3 -m scanner.tools.rescore            # re-derive match_score after the scoring config changed
```

## Dedupe

- `ux_jobs_url` (global, on `lower(url)`): the same posting URL = one job,
  even when two boards link to the same ATS page.
- `ux_jobs_board_source_ref`: a board's own id/guid is stored once per board.
- Re-discovered jobs are never duplicated, and only get `last_seen_at`
  refreshed — plus, when they were stored without a description and this scan
  has one, that text and the score it earns. Text already stored is never
  replaced. That exception is what lets a board whose advert lives on the
  posting's own page (see above) fill a row in on a later run; the rule has its
  own selftest, `python3 -m scanner.store`.
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
- A stored `match_score` is written at insert time and refreshed only when the
  row gains a description it never had; a later scan of an unchanged row does
  not rescore it. So after editing the config run `python3 -m scanner.tools.rescore`
  — `--dry-run` first, `--top 20` to see what the new ranking actually puts
  first, `--only-below 15` for a cheap pass over the low end.
- A score answers "how much of the stack does this advert name", nothing else.
  Two neighbouring questions have their own tools: whether the title is this
  kind of role at all (`Matcher.admits()`, which reports use so their notion of
  "looks like a role" cannot drift from the scorer's), and whether the posting
  is open to where the person lives (`region_scope`, above).
- **Classifier upgrade path**: replace the internals of
  `scanner/keywords.Matcher.score()` (or add `scanner/classifier.py` with the
  same contract) — nothing else changes.

## Cron

**The schedule is off (19/10).** Runs are hand-triggered:

    python3 -m scanner                  # all enabled boards except on-demand ones
    python3 -m scanner --board RemoteOK # one board
    python3 -m scanner --dry-run        # fetch + report, no writes
    python3 -m scanner --min-score 25   # stricter lead threshold

To put the daily 06:30 run back: `./cron/install.sh` (idempotent — it replaces
the line it manages and backs up the crontab first). `./cron/install.sh
--remove` takes it back out; that is what turned it off. Installed, it logs to
`logs/scan.log` and per-day reports land in `logs/leads/` either way. If it is
re-installed: cron's `PATH` is minimal, so `daily_scan.sh` exports the OpenCLI
bin directory itself, and Cron's `python3` is `/usr/bin/python3`, which is not
the interpreter that has `jobspy` (`jobspy` boards report
`No module named 'jobspy'` from cron while working from a shell).

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
- This board is **on demand** (`scan_config.on_demand`): a full
  `python3 -m scanner` reports it and skips it, and it scans only when named —
  `python3 -m scanner --board 'X Bookmarks'`. So Chrome-open timing is yours to
  choose, and a run with Chrome closed is not an error on the other boards.
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

1. Add the board to `db/seeds/boards.jsonc` (`kind`, `url`, `scan_strategy`,
   `scan_config`, `notes`) and run `python3 -m db.seed` — it upserts by `name`,
   prints `+n ~n`, and `--dry-run` shows the same without writing. `--prune`
   disables boards missing from the file; rows are never deleted.
2. Before writing any parser, run `python3 -m scanner.tools.probe_boards` — it
   reports, per `html` board, whether a real feed/sitemap/JSON-LD/JSON endpoint
   exists (filters out SPA "200 HTML fallback" false positives). Prefer the
   cheapest path: `rss` flip → existing `api`/`jobspy` → `mapped` config →
   listing-page parser → browser read.
3. Then, per shape:
   - a feed: set `feed_url`, or `feed_urls` for a board's several categories;
   - a JSON API: add a branch in `fetch_api`, or just `fields` for `mapped`;
   - a server-rendered listing page: add a parser to `scanner/html_boards.py`
     and register it in `LIST_MODES`, with selftest cases cut from the real
     card (`python3 -m scanner.html_boards` runs them). If the card carries no
     advert, add a `parse_*_detail` and register it in `DETAIL_MODES`, then set
     `details: true` on the board — the fetcher then reads the posting page for
     postings whose text the store does not have yet, and nothing else;
   - a page only a browser can reach: add a site adapter under `scanner/js/`
     and point `scan_config.js_file` at it (`mode: opencli_eval`).
4. Scan it alone first: `python3 -m scanner --board NAME --dry-run`, then
   without `--dry-run`. `logs/leads/YYYY-MM-DD.md` gets the report either way.

