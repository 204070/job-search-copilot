# Xing (job board)

`boards` row `Xing` (id 32), `scan_strategy: html`, `scan_config.mode:
opencli_eval`. Added 22/10/2026 at the user's request. Board URL is
`https://www.xing.com/jobs/find`, and that page is only an AI-search landing
page, so the board scans three keyword searches instead (see `scan_config.urls`).

**On demand since 22/10/2026.** A full run (`python3 -m scanner`) reports this
board as `on demand only` and skips it; it scans when named, with `python3 -m
scanner --board Xing`. The switch is one key, `scan_config.on_demand`, and
nothing else changed: the adapter, the detail parser, the searches and the
board's own notes are all still there. To put it back on every run, delete that
key. Setting `scan_strategy` to `manual` is the stronger switch (never scanned,
even when named), and it is not what this board uses.

## What a run does

1. For each search URL: open a background tab in the logged-in Chrome
   (`profile: g3pxjge8`, session `xingscan`), evaluate
   `scanner/js/xing_search.js` in the page, close the tab. The adapter clicks
   "Show more" four times so a query yields about 30 cards rather than the 5-12
   the page renders first.
2. Rows are deduped across the three queries by URL (the same posting found by
   two queries is stored once).
3. `details: true` fetches each *new* posting's own page with plain HTTP and
   fills the advert through `parse_xing_detail` (mode `xing`, registered in
   `DETAIL_MODES`).

Measured: first fill 130 rows in 8 min 26 s (130 detail fetches at `delay_ms`
400 plus three searches), then 130 fetched / 14 new in 1 min 33 s. A row with
no advert is re-fetched next run, which is the design.

## The search page

- `https://www.xing.com/jobs/search?keywords=...` redirects to
  `https://www.xing.com/jobs/search/ki?keywords=...&id=<hash>` — an AI search,
  client-rendered.
- The result count line ("955 jobs found") is the readiness marker. It is what
  the adapter waits for, and it is absent on a login wall or a redirect, so an
  expired session reads as "no rows after N tries" (an error) and never as an
  empty board.
- Cards are `article[data-testid=job-search-result]`, title in
  `[data-testid=job-teaser-list-title]`, employer in `img[title]`, and text
  lines for place / type / salary / age. Class names are hashed CSS-in-JS and
  change, so the adapter reads `data-testid` and text lines, not classes.
- "Show more" is a plain `button` whose text is exactly that; each click adds
  about 5-9 cards (5 -> 14 -> 19 measured).

### Card parsing rules (and the traps in them)

| field | where it comes from |
|---|---|
| `title` | `[data-testid=job-teaser-list-title]` |
| `company` | `img[title]`; on a partner card (no logo) the first text line after the title |
| `location` | the remaining text line, after type, salary and age lines leave |
| `salary_*` | the card's own band, recognised by its currency mark |
| `description` | the card text; the detail pass overwrites it with the advert |
| `metadata` | `via`, `employment_type` (the card badge), `search_keywords` |

Three traps, each of which stored wrong data on the first run and is now in the
adapter:

- **The title line must leave before the type is read.** A posting called
  "Full Stack Engineer" matches a `/^full/` type test, so the title was taken
  as the type and the card's own "Full-time" badge was left in `location`
  ("Köln, Full-time"). The type pattern now requires the word `time`
  (`full-time`, `part-time`, plus German `Vollzeit`/`Teilzeit`/`Werkstudent`).
- **The age line is not the place.** 47 rows came back as
  "Berlin, Full-time, 2 days ago, Posted 2 days ago". Those lines match
  `AGE` and leave with the type; the card's age is never `posted_at` anyway,
  because the detail page states an exact day.
- **The salary band needs its currency mark to be recognised.** A stricter
  "digit, dash, digit" test fails on `€66,000 – €83,500` (a `€` sits between
  the dash and the second number), which pushed the band into `location`.

Partner cards (`External job ad`, links off-site to jobware.de, it-jobs.de,
click.appcast.io, meinestadt.de, de.moovijob.com, apply.j-vers.com) carry no
logo and no Xing URL. They are stored like any other row: the detail parser
reads *any* page's `JobPosting` JSON-LD, so a jobware advert lands in
`raw_text` the same way. Four of those hosts refuse plain HTTP (`HTTPError`),
so those rows keep the card text, have no date, and are asked for again on
every run by design.

## The detail page

Xing renders posting pages server-side: one `_http_get` returns about 300 KB
with a single valid `application/ld+json` block (a `JobPosting`). What it
carries, and what it does not:

- **carries**: the full advert HTML (becomes `raw_text` after `_text()`),
  `datePosted`, `employmentType`, `jobLocation` (list or one place, address
  with locality / region / country), `validThrough`, and on some postings
  `jobLocationType: TELECOMMUTE` plus `applicantLocationRequirements`.
- **does not carry**: the salary band. The `€66,000 – €83,500` on a card comes
  from Xing's own search data and is never repeated in the block, so the card's
  band is what the store keeps.

`_apply_detail` merges the two new kinds of value: `workplace_type` only fills a
row that had `unknown` (a card that says "Remote" is the employer's wording and
wins), and detail metadata (`applicant_location_requirement`, `valid_through`)
fills a key that is empty and never overwrites one the card set.

### `datePosted` comes in four shapes

Taking the first ten characters stored `"Fri Aug 07"` in `posted_at`, which has
no age a lead digest can read. `_xing_day` handles all four:

| shape | example |
|---|---|
| ISO timestamp | `2026-09-18T00:26:18Z` |
| JavaScript Date | `Fri Aug 07 2026 00:26:18 GMT+0200` |
| RFC 2822 | `Fri, 07 Aug 2026 00:26:18 GMT` |
| a partner's own, year last | `Fri Oct 09 11:12:25 CEST 2026` (jobware) |

Six rows were repaired by re-reading their pages after the normaliser landed.

## The region gate (standing fact about this board)

Xing decides *by the reader* what a posting shows. On 22/10/2026 the Tracium
posting (#2779) read in full while logged out; the moment the same Chrome was
logged in, the same URL answered:

> **Job can't be displayed.** This job cannot be displayed in your region.

and `/jobs/custom-apply/<slug>` answered "Sorry... Something went wrong." The
employer's own posting for the same role (join.com) said "Remote (worldwide)"
while its JSON-LD said `applicantLocationRequirements: Germany`, and the third
source (Meridian Remote) listed it under Germany. Two independent signals
pointed at Germany and the board itself hid the posting from this profile.

Consequences for the scan:

- The scan reads through the **logged-in** Chrome, so a posting Xing hides from
  this profile never reaches the store at all. A posting missing from a run is
  therefore not evidence that it was never posted; and a posting found logged
  out may be absent from the scan.
- The gate is a **display** rule, not the employer's eligibility sentence. It
  is a strong hint (Xing gates by profile region, and the profile sits in
  Nigeria), but the sentence that decides is the one on the employer's own
  posting. Read it before treating a gated posting as closed, and before
  applying to one the gate lets through.
- Card `location` is a place, not a scope: `region_scope` for these rows comes
  from the advert's own text via `classify`, and `unknown` there means "states
  no restriction", which is not the same as "open to you".

## Commands

```bash
python3 -m scanner --board Xing              # scan this board alone
python3 -m scanner --board Xing --dry-run    # fetch and report, write nothing
python3 -m scanner.html_boards               # selftest: detail parser + dates
python3 -m scanner.tools.classify --board Xing
```

To change what the board searches, edit `scan_config.urls` (three keyword
searches). Adding a fourth costs one more tab per run.

## References

- Strategy and the `opencli_eval` contract: `_docs/scanning.md`
- Bridge commands, tabs and sessions: `_docs/tooling.md`
- Region scope vocabulary: `_docs/scanning.md` ("Region scope") and
  `scanner/eligibility.py`
