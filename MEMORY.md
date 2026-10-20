# Job Search Memory

This file is an index, not a store.

- Read it before any agent acts on the user's behalf.
- It holds rules that cross agents and outlive one role. An agent's craft
  belongs in that agent's playbook, never here, so one agent's context does
  not leak into another's.
- Add one short rule after a meaningful event, and point at the file that owns
  the detail. Follow the pointer; do not copy the detail in.

**This repository is public.** Never write a name, an email address, a phone
number, a salary figure, a city, an employer name or a board slug here. Write
`job #<id>` or a placeholder (`Northwind`, `Acme`). Employer names live in
`db/jobs.db`, `artifacts/` and `logs/`, which are gitignored.

## Agents and playbooks

Each agent has a playbook in `_docs/team/`. Load your own only. A new agent
adds its row and its file, and keeps its mechanics there.

| Agent | Playbook | Covers |
|---|---|---|
| Application specialist | `_docs/team/application-specialist.md` | forms, drafts, application email, handovers |

## Where the records live

| What | Where | Detail |
|---|---|---|
| Postings, applications, events, question bank | `db/jobs.db` | `_docs/jobs-db.md` |
| The user's facts | `artifacts/profile.jsonc` | read before you draft or fill |
| The canonical CV | `artifacts/` (path in `profile.jsonc`) | the CV that is attached |
| The digest | `artifacts/review.md` | derived; `_docs/jobs-db.md` |
| Scan reports | `logs/leads/YYYY-MM-DD.md` | `_docs/scanning.md` |
| Recipes and worked cases | `_docs/` | scanning, tooling, per-ATS files, playbooks |

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
- **Design:** an agent prepares and hands over, the user reviews and sends. No
  agent clicks Submit or touches a captcha for them. Playbooks: `_docs/team/`.
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
- "Open to remote candidates" is not "open to you". A form that asks for a US
  city and state, or for US work authorization, is the tell. → `_docs/greenhouse.md`
- A board's country list is a shortlist, not a region. Poland plus ten named
  countries is not "Worldwide", even when an aggregator's badge says so.
- A failed check ends the posting. Archive it with `reason_for_archive`.

### Scoring

- A `match_score` counts the words a posting uses. It does not measure the
  must-haves of the role. Read the must-haves on the employer's own board
  before you trust a high score or drop a low one.
- A target that lives in a chat thread does not score. Put the title names in
  `scanner/keywords.jsonc`.
- A wider gate buys volume. Read what comes back before you trust it.
- After a scoring change, run `rescore` and read the top of the new list.
- A banned employer is a config entry (`company_exclude`), not a dismissal per
  row: the scan then stores nothing for it. → `_docs/scanning.md`

### Acting for the user

- An agent prepares and hands over; the user sends. → `_docs/team/`
- Facts about the user live in `artifacts/profile.jsonc`. What one employer was
  told lives in the question bank. Never re-derive an answer the bank holds.
  → `_docs/jobs-db.md`
- Verify the committed value, not the click. → `_docs/greenhouse.md`
- Something that belongs to the user, a pay figure or a consent, is theirs to
  give: flag it, never infer it. → `_docs/team/application-specialist.md`
- The agent's fill is a draft. The user may submit from another browser and
  edit the prose, so ask for the final wording and record that, not the fill.
  → `_docs/team/application-specialist.md`

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
