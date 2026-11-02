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
  `unknown` or `us_only`. The tag groups the board; it does not decide
  eligibility. Only an explicit eligibility sentence is a bar. Detail:
  `_docs/scanning.md`.
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

- **One job can be published under several titles.** Diff the board's
  description text before you count two postings as two chances: three titles
  with byte-identical descriptions and identical structured fields are one
  role, and the second application spends a slot for nothing. → `_docs/ashby.md`
- The employer's own structured field is the best evidence of where a posting
  sits. It is evidence, not a verdict: the eligibility sentence decides. An
  aggregator's location, badge or "we hire globally" line is a hint. Check the
  employer's board before you fill anything. → `_docs/scanning.md`
- **A board can be an aggregator, not the employer.** The application form and
  the reply can come from the board while a client company hires. Check the
  client before you treat a role as direct, and record the client on the job
  and application rows. → `_docs/scanning.md`
- **An aggregator can clone one posting once per country.** The country tag is
  then the board's targeting, not the employer's list. A country named in a
  boilerplate benefits block is not the location either: the same line appears
  on all thirty clones. Read the structured fields, apply to the clone for your
  own country, and leave `jobs.company` as the board when the client is
  unnamed. → `_docs/scanning.md`
- The word `Remote` means "not in an office". It does not say who may apply.
  Read the eligibility sentence in the posting.
- **Read what the location sentence does.** A city or country named as the
  office or primary location ("Remote, primary location Munich") is not an
  exclusion. A region named as the eligible scope ("Remote - Europe",
  "EU only", "must be based in Europe") is an exclusion when the user is
  outside it. A country list without the user's country is an exclusion.
  Silence on sponsorship is not a refusal.
- **A stated sponsorship offer is a positive signal, not a requirement.** A
  role in the user's own country needs no sponsorship check: the user is
  already authorized there.
- "US hours" and "US timezones" describe overlap, not a bar.
- "Open to remote candidates" is not "open to you". Read the form's location
  and authorization questions. A form that requires a US city and state, asks a
  required `Are you located in <country>?` Yes/No question (confirmed by
  rejection on job #1156), or treats US work authorization as a knockout is the
  tell. A work authorization question is not a bar by itself; answer it
  honestly. → `_docs/greenhouse.md`
- **A required "Are you eligible to work in this location (without
  sponsorship)?" is the knockout in one field.** Check the employer's whole
  board first for a twin posting open to the user: one role can be published
  twice with identical text and two different countries. → `_docs/greenhouse.md`
- **A place the user will not apply to is a row, not a code change.** It lives
  in `skipped_countries` and hides those postings from the shortlist without
  archiving them, so deleting the row brings them back. → `_docs/jobs-db.md`
- **US sponsorship is conditional.** Read the bank's
  `us_sponsorship_required` answer before you respond. The profile booleans
  describe the fully remote case; a question about US work authorization needs
  the bank's rule. → `_docs/jobs-db.md`
- A board's country list is a shortlist, not a region. Poland plus ten named
  countries is not "Worldwide", even when an aggregator's badge says so.
- Only an explicit exclusion ends the posting. Archive it with
  `reason_for_archive`.
- **A posting URL that loads is not a posting that exists.** A removed job can
  answer 200 by redirecting to its board. Check the final URL against the
  board's own link list, then archive. → `_docs/bamboohr.md`
- **Two Breezy signals read as closure and are not: an empty board JSON, and
  `Application Submitted` on the apply page.** The second one is this browser's
  own application state, so ask before you archive. → `_docs/breezy.md`
- **A board can hide a posting from the reader instead of removing it.** One
  board answers "this job cannot be displayed in your region" for a posting the
  same browser read in full while signed out, so a posting missing from a
  logged-in scan is not evidence it was never posted, and the gate is a display
  rule rather than the employer's eligibility sentence. → `_docs/xing.md`

### Scoring

- **A board's own search box is not a filter to trust.** One board's phrase
  search found 17 of its 25 live postings, so a small board is read whole and
  the scorer decides. → `_docs/scanning.md`

- **A `jobspy` LinkedIn row without its advert text scores 0.** Set
  `linkedin_fetch_description: true` on the board, and keep `results_wanted` at
  25 or below because LinkedIn answers 429 above that. → `_docs/scanning.md`
- **On LinkedIn the location field is where the employer sits, not who may
  apply, and `location: Remote` is not a remote filter.** The user's own country
  is the only high-precision setting. → `_docs/scanning.md`

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
- **A message sent in the user's name is written in the user's voice.**
  Contractions, plain sentences, no stack of technical nouns, and no summary of
  the recipient's own writing back at them. Name the work, say it is admired,
  stop. → `artifacts/outreach-templates.md`
- Facts about the user live in `artifacts/profile.jsonc`. What one employer was
  told lives in the question bank. Never re-derive an answer the bank holds.
  → `_docs/jobs-db.md`
- Verify the committed value, not the click. → `_docs/greenhouse.md`
- **A gap is a sentence, not a veto.** Say once what the posting asks for and
  the user has not done, then fill the form. Whether a gap rules the role out
  is the user's call, and they have said it does not.
  → `_docs/team/application-specialist.md`
- **A voluntary EEO block is answered, not declined.** Race, gender and
  veteran status are already in `profile.jsonc` `self_identification`.
  → `_docs/team/application-specialist.md`
- Something that belongs to the user, a pay figure or a consent, is theirs to
  give: flag it, never infer it. → `_docs/team/application-specialist.md`
- The agent's fill is a draft. The user may submit from another browser and
  edit the prose, so ask for the final wording and record that, not the fill.
  → `_docs/team/application-specialist.md`
- **Some applications forbid AI-written answers and say so on the form.** Read
  the form's own rules first. The default is to write no free-response text,
  not even a sketch: prefill the factual fields and hand the essays to the user.
  The user may override that, and owns the risk when they do. Flag it once,
  record the override, then fill and stop arguing. → `_docs/team/application-specialist.md`
- **Before writing a new answer, read the last one.** A board reuses one form
  template, and the text the user approved lives in that application's
  `metadata.drafts`. Reuse it word for word. → `_docs/jobs-db.md`
- **A Workable view link is not the apply link.** The public view code and the
  apply shortcode can differ. Read the job card's own href before you fill.
  → `_docs/workable.md`
- **Workable can make the photo required and the resume optional, and its
  header country list is an eligibility list.** Read each file input's required
  flag; a list without the user's country is an exclusion. If the user
  overrides, record it and do not call the role eligible. → `_docs/workable.md`
- **`open` in a browser session that holds no tab takes over a tab another
  session holds, and `tab close` can close the window and every form in it.**
  Check `tab list` first; keep one form tab and read other postings from the
  board's JSON instead. → `_docs/tooling.md`
- **Airtable rich-text fields (`[role=textbox]`) ignore `innerText` writes, and
  hex IDs regenerate on reload.** Focus the inner `[contenteditable=true]` node
  and run `document.execCommand('insertText', false, text)`, and target short
  fields by position. → `_docs/airtable.md`
- **OpenCLI resets extension-owned browser tabs to `about:blank` after 10
  minutes of CLI inactivity (`IDLE_TIMEOUT_INTERACTIVE = 600s`).** Prefix every
  browser command with `OPENCLI_BROWSER_IDLE_TIMEOUT=86400` (24 hours) or bind a
  user-opened tab via `opencli browser <session> bind`. → `_docs/tooling.md`
- **A field in the DOM is not a field on the form.** One board carries hidden
  template inputs for its Add Education and Add Experience modals, so a naive
  query returns forty fields where the form has five. Filter on visibility
  before you fill, and before you record what the form asked.
  → `_docs/manatal.md`
- **Fill can land in the wrong field, so read every field back after a widget.**
  A phone country search wrote its text into the email field on two different
  Greenhouse boards, and the value still reported as verified for the intended
  target. → `_docs/greenhouse.md`
- **A field that holds text is not a field that accepted an answer.** A
  country-only autocomplete kept a typed city in the box, showed a real "No
  results" listbox and no error, and read back as answered while nothing was
  committed. Read the control's own state (`aria-expanded`, the committed
  value) and pick a real option. → `_docs/ashby.md`
- **An input-only inventory misses the questions a form cares most about.**
  Yes/No questions render as buttons with `aria-pressed`, not radios, so a read
  of `input`, `textarea` and `select` shows a complete form with two questions
  unset. Read the buttons and group them by their question. → `_docs/ashby.md`

### The store

- `upsert_job` refreshes `last_seen_at` only. Each improvement to an extractor
  needs a re-runnable pass: `classify`, `enrich_*`, `rescore`. →
  `_docs/scanning.md`
- A derived state is never certified by hand. Our own `note` and `follow_up`
  rows are not contact from the employer. → `_docs/jobs-db.md`
- A follow-up we sent is its own `follow_up` row, dated when it went out. The
  digest reads it and stays quiet for the same 7 days, so a recorded send stops
  the next day's prompt. → `_docs/jobs-db.md`
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
- The shortlist demotes what we have already tried: -15 per application and -20
  per rejection in 90 days, plus a named `employer_weights` row. Set one with
  `review employer --set`, never by editing the digest. → `_docs/jobs-db.md`
