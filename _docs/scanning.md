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
| `jobspy`  | `scanner/fetchers.fetch_jobspy`  | `source`, `search_term`, `location`, `results_wanted`, `hours_old`, `linkedin_fetch_description`, `is_remote` | needs `pip install python-jobspy`; see [LinkedIn](#linkedin-jobspy-what-the-search-actually-does) |
| `html`    | `scanner/fetchers.fetch_html` (mode-dispatched) | `mode` (+ mode keys: `pages`, `details`, `delay_ms` for the list parsers; `profile_dir`, `scrolls`, `cap` for `x_bookmarks`; `url` or `urls`, `profile`, `session`, `js_file`, `tries`, `wait_ms`, `detail_mode` for `opencli_eval`; `on_demand` for any of them) | browser-scraped and server-rendered boards; unknown `mode` = "not scanned yet" |
| `manual`  | never auto-scanned | — | e.g. saved Google searches, dead boards |

Two config keys cut work out of a run without changing what a board is:

- **`on_demand`** keeps a board out of a full run (`python3 -m scanner`): it
  scans only when named, `python3 -m scanner --board NAME`, and the run report
  names it and says so rather than staying silent. X Bookmarks is set this way,
  because it reads your own logged-in Chrome and you want to decide when that
  happens; Xing joined it on 22/10 at the user's request. (`scan_strategy:
  manual` is the stronger form: never scanned at all, even when named, which is
  right for a board with nothing to fetch. The board's own config stays in
  `scan_config` either way, so switching back is one key.)
- **`details`** asks for one extra request per *new* posting, described under
  [Server-rendered list boards](#server-rendered-list-boards-jsgurujobs-javascript_jobs).
  For a board read through the browser, name its detail parser with
  `detail_mode` (the list `mode` there is `opencli_eval`, which is not a
  parser), and see [Xing](#xing-mode-opencli_eval-with-a-detail-pass).

The `html` modes, cheapest first:

| mode | what it reads | code |
|---|---|---|
| `jsgurujobs`, `javascript_jobs`, `relocate_me` | plain server-rendered listing pages, fetched with `_http_get` and parsed by anchored patterns | `scanner/html_boards.py` (pure parsers + selftest) |
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
JS Guru Jobs, JavaScript Jobs and Relocate.me (server-rendered HTML lists, with
the posting's own page read for new rows), Jobicy (mapped API), Remotive +
RemoteOK (APIs), Indeed/LinkedIn/ZipRecruiter (JobSpy), HiringCafe, Work at a
Startup and Xing (browser-read searches, need Chrome), X Bookmarks
(OpenCLI/Playwright, your own session — `on_demand`). ZipRecruiter currently
returns 403 from this network; LinkedIn rate-limits. 5 `html` boards stay
pending — reconnaissance status for each lives in `boards.notes` (migration
0009); paywalled/dormant boards (Remote4Africa, RemoteAfrica, Crossover) are
`manual`, Cleverjobs is disabled.

## Aggregator boards

A board can be an aggregator. The posting, the application form and the reply
can all come from the board, while a client company is the employer. The board
brand is not the employer. Before you treat a role as a direct application,
read the posting for the client name, and record the client on the job and
application rows when the reply names it. A rejection from the board can be the
client's decision; record it against the client employer, not the board.

A board's matching system is a separate source to evaluate. It can surface
roles, but it does not replace the employer's own board. Check the client and
the eligibility sentence before you fill anything.

### One posting cloned across countries

Some aggregators publish one role once per country, so a single advert becomes
twenty or thirty board rows with the same body and a different country tag.
Measured 1/11/2026 on the Jobgether Lever board: `Software Engineer - Storage`
appeared 30 times, one per country from Argentina to the United Arab Emirates.
Two consequences.

- **The country tag is the aggregator's targeting, not the employer's list.**
  Do not read a clone set as evidence that the employer hires in each of those
  countries, and do not read it as a bar either. Treat the clone for the
  applicant's own country as the row to apply to, and treat the others as
  duplicates of it.
- **A country named in the boilerplate is not the location.** The same benefits
  block said "Work remotely from Slovenia" on the Nigeria, Norway, Finland,
  Kenya and US clones alike, because the block is copied unchanged. The
  structured fields are the ones that move: `country`, `categories.location`
  and `categories.allLocations`. When a benefit bullet names a country the
  headline does not, compare the clones before believing either. A line that is
  identical on all thirty rows carries no signal at all.

An aggregator that runs an AI shortlist names its client only as "a partner
company". Record the board as the company, put the inference and its evidence
in the application metadata, and say plainly that the employer is unconfirmed.
Do not write a guessed employer into `jobs.company`.

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

### Relocate.me (`mode: relocate_me`)

Read whole, not by query. The site's search box is a narrow phrase match: one
common job title returned 17 of the 25 live postings, and the whole board is 24
postings over 2 pages of 20, so reading everything and letting the scorer rank
beats guessing a phrase. `pages: 4` leaves room for the board to grow.

- **The card** carries a country (`Netherlands`, `Japan`, or `Remote`), the
  employer, the title and a truncated preview. The country and city also sit in
  the URL (`/netherlands/amsterdam/picnic/slug-10256`), which is where
  `metadata.country_slug` / `city_slug` come from, and the trailing number is
  `source_ref`.
- **A `job_featured` card is dropped.** That is a paid advert for another job
  board ("1700+ curated jobs"), not a posting here.
- **The place is the useful statement.** A relocation board's premise is a visa,
  but a role in Japan or the Netherlands is `region_gated` for a candidate in
  West Africa, which is the honest tag. The classifier handles it; the parser
  does not guess.
- **The posting page** is a broken `JobPosting` JSON-LD block: every string
  carries raw newlines, so a document parse fails, and the advert inside it is
  escaped HTML (`&lt;p&gt;`). One unescape before `_text` is what turns it into
  readable text. The block also gives `datePosted`, `validThrough` (kept as
  `metadata.expires_at`) and `hiringOrganization`.
- **Cost:** first fill 85 s for 23 postings (one detail request each, paced at
  400 ms), then 14 s with every row already described. Some postings are years
  old by `datePosted` and still listed, so a row's age is not evidence it closed;
  `last_seen_at` is.

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
  one named city is not a job the applicant can take without relocating, and WaS
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
- The filter narrows the fetch, never the store. Rows already stored keep their
  status, so a narrower search deletes nothing, and `classify` still tags them
  if they are read again.


## Xing (`mode: opencli_eval` with a detail pass)

Xing's own search, added 22/10/2026. `/jobs/find` is an AI-search landing page
with no list to parse, so the board opens three keyword searches from
`scan_config.urls`, expands each with "Show more", and reads the cards out of
your logged-in Chrome. Unlike HiringCafe and Work at a Startup, the card alone
is not enough: it carries title, employer, place, type and a salary band but no
advert, so `details: true` reads each *new* posting's own server-rendered
JSON-LD block through `detail_mode: xing` (`parse_xing_detail`). That is the
first browser board with a detail pass.

- **On demand since 22/10** (the user's call): a full run reports the board as
  `on demand only` and skips it, and the board scans only when named. Nothing
  was removed to do it: one key, `scan_config.on_demand`, was added. Going back
  to every run is deleting that key, and the parser, adapter and searches are
  untouched.
- Two new keys in the fetcher, both general: **`urls`** (several pages per
  run instead of one `url`, rows seen twice kept once — a search-driven board
  returns 10-30 rows per query) and **`detail_mode`** (which parser reads the
  posting page, when the list `mode` is not one).
- An evaluation that *throws* now waits and retries like a `null` answer rather
  than failing the run: the common cause is the tab's own load racing the first
  eval, which is a page not ready, not a broken adapter.
- Steady state 33-93 s for three searches; first fill 8 min 26 s because every
  row needed its advert. Fetched count moves between 95 and 127 a run: the
  search pages rotate which partner cards they show, and a card carries no
  date, so some come back every time.
- The board's own reconnaissance, card traps, the four `datePosted` shapes and
  the standing fact that **Xing hides a posting from a reader whose profile
  region it does not match** are in `_docs/xing.md`. That last one matters to
  scanning: the scan reads logged in, so a posting the gate hides never enters
  the store.


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
worldwide. A tag is not a verdict: `us_only` is a bar when the posting demands
US residence or US work authorisation, and a `region_gated` row is a bar only
when its eligibility sentence excludes the user. "US timezones"/"US hours"
describe overlap and are NOT bars. Nothing is ever filtered out on this basis:
the tag groups the board; the daily report sorts matches by scope first, so a
role you can't take no longer buries one you can. `jobs.region_evidence` keeps
the phrase that produced the tag.

The word `Remote` means "not in an office". It does not say who may apply. Three
employers whose own ATS field reads `Remote` narrowed it three ways: one stated
"we're only open to candidates based in the US, EU and UK", one was really two
countries in central Europe once its board was read, and one sat beside a third
party's `USA Only` tag while its own board said nothing. Read the eligibility
sentence, and prefer a field that carries a region (`Home based - Worldwide`,
`Remote - Global`) over one that carries none. Expect a mostly US net: in the
high-score band the well-known employers resolved to a US-only or a named short
list.

**A job-board badge is the board's claim, never the employer's list.** On
22/10/2026 one aggregator badge read `Worldwide` on a role that then printed
"countries we can hire in" covering four continents and naming nine African
countries, none of them the user's. The classifier had taken the badge as the
verdict. When a posting's own text carries a hire list, that list wins over the
badge, and the row goes to `region_gated` with the list in `region_evidence`.

### What the location sentence does

The word `Remote` says "not in an office". The location sentence says what the
employer means by it. Read the sentence, not the tag:

| the sentence | what it does | eligible? |
|---|---|---|
| "Remote, with the primary location in Munich" | names an office or primary location | yes, unless another sentence excludes the user |
| `Location: Munich`, `Location Type: On-site` | a structured office field | yes, same test |
| "Remote - Europe", "EU only", "must be based in Europe" | names the eligible scope | no, when the user is outside that scope |
| "We can only hire in the US, UK and Canada" | a country list | no, when the user's country is not on it |
| "We do not offer visa sponsorship" | an explicit refusal | no, for an onsite role outside the user's own country; a remote role from home is still in play |
| no location sentence | silence | yes; silence is not a refusal |

A city or country named as an office is evidence of where the role sits, not a
statement that the employer will hire only there. A region named as the scope of
a remote role is an eligibility limit. "Europe" by itself is ambiguous until you
read the sentence: "primary location in Europe" is an office; "Remote - Europe"
or "Europe only" is a scope.

Silence on visa sponsorship is not a refusal. A stated sponsorship offer is a
positive signal, not a requirement. For a role in the user's own country, skip
the sponsorship question: the user is already authorized there.

### Verify on the employer's own board

An aggregator's row is not evidence of where a posting hires. Three of the six
best-looking leads in one sitting carried an empty location and were gated in
fact (USA/Canada, a single country, "you are based in the US"). Two others were
genuinely worldwide, and both said so in a structured field the aggregator never
carried (`Anywhere`, "based elsewhere, you'll be hired via our global employer
partner").

A high score does not fix this. Job #4279 on 29/10/2026 scored 96 with no
location field, and its body said "Build from anywhere in LATAM". The classifier
treats the location field as authoritative and reads the body only for strong
obligation wording, so a region named only inside the body leaves the row
`unknown`. Read the body of a high-scoring `unknown` row before spending an hour
on it, and treat the first eligibility sentence as the verdict.

Ashby, Greenhouse and Lever publish a whole board as JSON, so the check costs
one fetch and no browser session:

```bash
# Ashby (carries each posting's structured location)
curl -s 'https://api.ashbyhq.com/posting-api/job-board/<slug>?includeCompensation=true'
# Greenhouse (jobs + full advert text)
curl -s 'https://boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true'
# Lever (the whole board; append /<posting-uuid> for one posting)
curl -s 'https://api.lever.co/v0/postings/<slug>?mode=json'
```

Lever also renders the apply page server-side, so its whole field list comes out
of one fetch of `<posting-url>/apply`. Detail: `_docs/lever.md`.

Worked case (24/10): a scraped lead arrived with no location and a Cloudflare
403 on its aggregator page. The employer's Greenhouse board answered in one
fetch and the sibling rows told the story: the role read `Remote (West Coast)`
while two others on the same board read `Remote (U.S.)`, so the tag became
`us_only`. A second lead that looked equally empty turned out worldwide, with
the posting offering "any location worldwide" inside a UTC-5 to UTC+8 band that
contains the user's UTC+1.

- Write the employer's own value into `jobs.location` and let `classify` derive
  the tag. Keep the provenance in `jobs.metadata.employer_ad`.
- The same read shows when the role held has been replaced by a different one.
- When the check finds an explicit exclusion, archive the posting with
  `reason_for_archive` (the runbook says how).

### Not every `region_gated` list excludes you

`region_gated` covers two opposite situations, and the tag alone cannot tell
them apart, so the sort reads the evidence phrase as well
(`eligibility.scope_rank`, shared by the scanner report and the digest). The
table orders evidence in the digest; it does not decide eligibility. The
section above does.

| order | scope | why |
|---|---|---|
| 1 | `worldwide` | open to anyone |
| 2 | `region_gated` naming the applicant's own region | EMEA, MEA, Africa, or the country itself: officially open to you |
| 3 | `unknown` | states nothing, so not a bar, but not a promise either |
| 4 | `region_gated` naming only other regions | Europe, the Americas, APAC, the Gulf: read the sentence. A location tag is not a bar; an eligibility scope is. |
| 5 | `us_only` | a bar when the posting demands US residence or authorization |

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
  - `company_exclude` — regexes for employers the user never wants to see
    again. A match on the company name is a veto above both title rules: the
    scanner stores no row for the posting, and `rescore` writes 0 to a row that
    already exists. Banning is a config edit, not a per-row dismissal, so a
    re-scan cannot bring the employer back. Existing rows stay in the database:
    archive them once (`review dismiss --job <id> --reason "company banned"`)
    and withdraw any open application for them. The list holds employer names,
    so it lives in the gitignored copy, never in the example.
  - `keywords[]` — `term`, `weight`, `enabled`; optional hand-written `pattern`
    regex override for alternations/optional words plain terms can't express
    (invalid patterns raise at load). Plain terms compile to case-insensitive
    `\bterm\b`, so `rust` never hits `robust`. A legacy `field: "title"` entry
    still loads, as one more admit pattern. Two kinds of signal live in this
    list and are commented apart: stack terms (weight 3 is the verified core)
    and location affinity (the applicant's own country and city, from
    `profile.jsonc` `location`), because an advert that names your country or
    city is telling you it will hire where you are.
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
- **A score is not a decision, in either direction.** An advert can name the
  stack in passing while its must-haves ask for experience the CV does not show,
  and a posting outside the user's strongest languages can score low while its
  gates are clear. Measured 19/10: two roles at one employer scored 88 and 17,
  and the gates ran the other way (the 88 wanted a year of a language the user
  does not have in production, plus Kubernetes beyond the basics with proof).
  Read the must-haves on the employer's own board before trusting a high score
  or dropping a low one.
- **Anything the user names as a target belongs in this file, not in a chat
  thread.** A family that is only mentioned in conversation never scores; the
  engineering-manager family and the AI vocabulary were both added that way. A
  wider gate buys volume, so check what it returns (`rescore --top 20`) before
  trusting it: the added families came back mostly US-resident or gated, and the
  eligible remainder asked for people-management experience.
- **Classifier upgrade path**: replace the internals of
  `scanner/keywords.Matcher.score()` (or add `scanner/classifier.py` with the
  same contract) — nothing else changes.

## LinkedIn (JobSpy): what the search actually does

Measured 24/10 on board 19, three runs:

| setting | result |
|---|---|
| `location: <home country>`, descriptions on, 72h window | 12 to 17 rows, every one based in the user's country, best scores 99 and 96 |
| `location: European Union`, descriptions on | 25 rows, almost all Berlin, Paris, Milan, Bucharest; a handful say "worldwide" in the advert |
| `location: Remote` (the old default) | a global mix with Vietnam, France, Australia and Canada, mostly roles that need a local permit |

Four things follow, and each one changed the config:

- **The location field is where the employer sits, not who may apply.
  `location: Remote` is not a remote filter.** It reads as a place name and
  returns a global list. The only high-precision setting here is the user's own
  country.
- **`linkedin_fetch_description: true` is what makes the board useful.** Without
  it JobSpy returns a title, a company and a URL, so `match_score` lands at 0 to
  4 and the Bayesian gate has nothing to read. With it, 15 of 17 rows carried
  advert text and the same postings scored 99 and 96. The cost is one request per
  posting: 12 rows go from 11 s to 32 s.
- **`is_remote` in JobSpy 1.3.0 is a label, not a filter.** The library sets it
  from the title and location (`is_job_remote`), and never sends LinkedIn's
  `f_WT=2`. A remote-only LinkedIn search needs the UI or the saved-search URL,
  not this board.
- **LinkedIn answers 429 above roughly 25 results**, and JobSpy logs one warning
  per blocked description while still returning the row. Keep `results_wanted`
  at 25 or below with descriptions on, and expect a run to take half a minute.

The boolean syntax works in the search term: `AND`, `OR`, `NOT` in capitals,
`"quoted phrases"` and parentheses are all passed through to LinkedIn. A 72-hour
window costs nothing extra because dedupe absorbs the overlap between runs.

The worldwide-remote question is still better served by the feeds that publish
it (`We Work Remotely`, `Real Work From Anywhere`, `Himalayas`, `Jobicy`) than
by LinkedIn, which mixes an eligible role into two dozen country-locked ones.

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

