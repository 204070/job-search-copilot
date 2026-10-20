# Job Search Memory

This file is an index, not a store.

- Read it before application work.
- Add one learning after each meaningful event: an application sent, an ATS
  observation, a reply, a rejection, a tooling discovery.
- Follow the pointer for the detail. Do not copy the detail into this file.

**This repository is public.** Never write a name, an email address, a phone
number, a salary figure, a city, an employer name or a board slug here. Write
`job #<id>` or a placeholder (`Northwind`, `Acme`). Employer names live in
`db/jobs.db`, `artifacts/` and `logs/`, which are gitignored.

## Where the records live

| What | Where | Detail |
|---|---|---|
| Postings, applications, events, question bank | `db/jobs.db` | `_docs/jobs-db.md` |
| The user's facts | `artifacts/profile.jsonc` | read before you draft or fill |
| The canonical CV | `artifacts/` (path in `profile.jsonc`) | the CV that is attached |
| The digest | `artifacts/review.md` | derived; `_docs/jobs-db.md` |
| Scan reports | `logs/leads/YYYY-MM-DD.md` | `_docs/scanning.md` |
| Recipes and worked cases | `_docs/` | scanning, tooling, per-ATS files, runbook |

## Standing context

- **Targets live in config, not here.** Title rules and weights:
  `scanner/keywords.jsonc`. What to apply to: `profile.jsonc` `targeting`.
- **The CV shows less than the user has done.** Read the profile for the full
  surface, and the attached CV for what a form actually received. The
  application row records which CV went out.
- **Eligibility:** `jobs.region_scope` is `worldwide`, `region_gated`,
  `unknown` or `us_only`. Only `us_only` is a bar, and no row is filtered out on
  this basis. Detail: `_docs/scanning.md`.
- **Scanning is hand-triggered** (`python3 -m scanner`). The cron schedule is
  off. Some boards need Chrome open. Detail: `_docs/scanning.md`.
- **Design:** the agent drafts and fills, the user reviews and submits. The
  agent never clicks Submit and never touches a captcha. Runbook:
  `_docs/team/application-specialist.md`.
- **Browser:** the OpenCLI Browser Bridge drives the user's own Chrome
  (`--profile <name>`, `jobfit` session). Detail: `_docs/tooling.md`.
- **A commit message carries no employer name, no country and no board slug.**
  Rewriting history with a force push is allowed to fix one. The older bodies
  that break this stand as they are, by the user's decision of 19/10. Do not
  raise them again.

## Learnings

Short rules only. The worked cases live in the file each group points to.

### Eligibility

- The employer's own structured field says where a posting hires. An
  aggregator's location, badge or "we hire globally" line is a hint. Check the
  employer's board before you fill anything. → `_docs/scanning.md`
- The word `Remote` means "not in an office". It does not say who may apply.
  Read the eligibility sentence in the posting.
- A `region_gated` list can include the user or exclude the user. Read the
  list. EMEA and Africa include the user; Europe alone, AMER, APAC and the Gulf
  do not.
- "US hours" and "US timezones" describe overlap, not a bar.
- A failed check ends the posting. Archive it with `reason_for_archive`.

### Scoring

- A `match_score` counts the words a posting uses. It does not measure the
  must-haves of the role. Read the must-haves on the employer's own board
  before you trust a high score or drop a low one.
- A target that lives in a chat thread does not score. Put the title names in
  `scanner/keywords.jsonc`.
- A wider gate buys volume. Read what comes back before you trust it.
- After a scoring change, run `rescore` and read the top of the new list.

### Filling an application

- Fill the whole form in one pass, then hand it over at once. An ATS form keeps
  no draft. → `_docs/team/application-specialist.md`
- The form can rewrite what you filled, and the page can go stale: read every
  field back after the upload, and hand a captcha form over within minutes.
  → `_docs/team/application-specialist.md`
- Verify the committed value, not the click. → `_docs/greenhouse.md`
- Answer the voluntary self-identification block from the profile. Never blank,
  never guessed. → `_docs/team/application-specialist.md`
- A pay figure is the user's: flag it at handover, and send the top of a range
  to a numeric field. → `_docs/workable.md`
- A group of fields can hide its own question; read the legend first.
  → `_docs/workable.md`
- Attach the CV file as it is. Its name is already the upload name.
  → `_docs/team/application-specialist.md`
- A fact about the user goes to `profile.jsonc`. The wording sent to one
  employer goes to the question bank. → `_docs/jobs-db.md`
- Do not pad an answer with a weak public repository. → `_docs/ashby.md`
- Name the employer's own product when the user has run it.
- Some postings take email, not a form. Only `review reply` clears the
  follow-up. → `_docs/team/application-specialist.md`

### The store

- `upsert_job` refreshes `last_seen_at` only. Each improvement to an extractor
  needs a re-runnable pass: `classify`, `enrich_*`, `rescore`. →
  `_docs/scanning.md`
- A derived state is never certified by hand. Our own `note` and `follow_up`
  rows are not contact from the employer. → `_docs/jobs-db.md`
- A change to what a query returns needs a run against a real database. A pure
  selftest cannot see it. → `_docs/jobs-db.md`
- Do not assume that a long run converges. Run the same board twice and read
  the times.
- Dedupe is by posting URL and by board plus source id. The same role on two
  boards with two URLs can stay two rows.
- An application row takes its job out of the lead list. To promote a pool row
  to the employer's own posting, add the new row, point the application at it,
  and archive the pool row with a reason that says so. → `_docs/jobs-db.md`
- Two applications to one employer in seven days is the limit. The digest
  derives it and prints the date it clears. → `_docs/jobs-db.md`
