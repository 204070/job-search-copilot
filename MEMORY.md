# Job Search Memory

> Living memory for the job-search workflow. **Read this file before working
> on applications; append learnings after every meaningful event** (application
> sent, ATS observation, recruiter reply, rejection, tooling discovery).
> Newest entries at the top of each section. This file is committed — never
> put secrets or private contact details here. Keep it an INDEX: per-ATS and
> tooling detail live in `_docs/`; per-application records in `db/jobs.db`;
> identity facts in `artifacts/profile.jsonc` (gitignored).

## Snapshot / standing context

- **Resumes:** uploadables in `artifacts/` (canonical `resume.pdf`;
  generated fallback `generated/resume-generated.pdf`).
- **Target:** senior remote full-stack (React/TS, Node, Python), plus
  Engineering Manager, Product Engineer, Forward Deployed Engineer, Solutions
  Architect and AI/LLM Engineer roles (18/10, when they went into the gate);
  scored via `scanner/keywords.jsonc`. **Leading teams is real, not a stretch
  (stated 18/10):** Engineering Manager is therefore a live target rather than a
  hopeful one, and the specifics (which team, how many engineers, over what
  period) still have to be recorded in `artifacts/profile.jsonc` — no
  application may state a figure until they are. Resume reality (gitignored
  detail in
  `artifacts/profile.jsonc`): 7+ yrs fullstack, TS/Node + Postgres, Django/
  Python, AWS→Azure, PCI DSS, fintech. **Resume is a floor, not a ceiling:**
  also Cassandra, ClickHouse, Heroku/Vercel/Netlify/Cloudflare, bare-metal and
  VPS deployments with Dokploy/Coolify/Kamal, Terraform/Ansible/GitHub
  Actions/Jenkins. Go is real but at side-project and exploration level, not
  enterprise production — keep it general when writing answers. The years figure
  is stated per application, not fixed: prose says "over 8", the current PDF
  prints "7+", and the user updates the CV for some roles, so check which CV is
  actually attached instead of assuming either number.
- **Eligibility:** `jobs.region_scope` (worldwide / us_only / region_gated /
  unknown) tags where a posting says it will hire; `us_only` is the only real
  bar. A `region_gated` list can *include* you (EMEA, MEA, Africa) or exclude
  you (Europe alone, AMER, APAC, the Gulf), so triage order reads the evidence,
  not just the tag: worldwide → covering region → unknown → excluding list →
  us_only. Detail: `_docs/scanning.md` → "Region scope".
- **Identity facts:** `artifacts/profile.jsonc` — read before drafting/filling.
- **Question bank:** `db/jobs.db` (`questions` + `question_instances`) behind
  `python3 -m db.tools.questions` — `lookup` before filling, `record` at
  handover, `retire` to set an answer aside; an answer's state (`unsent` /
  `sent` / `revised`, derived from the instance ledger, never approved by hand);
  `artifacts/faqs/*.md` are generated from it (`digest`).
- **Review digest:** `python3 -m db.tools.review` rewrites the one living file
  `artifacts/review.md` (private, gitignored): your own open actions, what
  changed since last time, follow-ups due, applications, next roles, pipeline
  health, the bank's state. Every line is derived from a row except the `todos`
  store, which exists for the actions that have no row behind them
  (`todo --add` / `--close`). Detail: `_docs/jobs-db.md`.
- **Current phase:** semi-automatic applications — agent drafts/fills, human
  reviews & submits. Runbook: `_docs/team/application-specialist.md`.
- **Tool:** OpenCLI Browser Bridge drives my real Chrome (always
  `--profile <name>`; `jobfit` session). Detail: `_docs/tooling.md`.
- **Logs & private docs:** `logs/leads/`; `artifacts/`.

## Application tracking

- Per-application records (job row, application row, events) live in
  `db/jobs.db` (`jobs` → `applications` → `application_events`; rows are
  gitignored). This file keeps only distilled learnings, never the log itself.
- **Employer names never enter this repo.** These docs are public and name the
  ATS vendors and job boards (Ashby, Greenhouse, Jobicy, WWR) because that is
  what the playbooks are about; the companies being applied to are referred to
  as `job #<id>` and their names stay in the gitignored DB. Same for the
  candidate's own past employers and any board slug or `gh_jid` that identifies
  an application. Worked examples use placeholders (`<org>`, `Northwind`) or a
  job id, never a real name.
- Question bank: `questions` + `question_instances` in the same DB, behind
  `python3 -m db.tools.questions`. `lookup` before filling a form, `record` at
  handover, `frequency` to see what recurs; `digest` regenerates
  `artifacts/faqs/*.md`. Schema and commands: `_docs/jobs-db.md`.

## Reference docs

- Per-ATS playbooks: `_docs/<ats>.md` (have: `greenhouse.md`, `ashby.md`) —
  load the one matching the posting; adapt `profile.jsonc` facts to that
  form's options case by case, never treat worked examples as canonical.
  **Ashby:** read the Overview tab's structured `Location` field first; it is
  authoritative over the posting text (see the eligibility case below).
- Team playbooks: `_docs/team/<role>.md` (have: `application-specialist.md`)
  — the full runbook for a collaborative application fill.
- Also in `_docs/`: `tooling.md` (browser bridge), `jobs-db.md`, `scanning.md`.

## Learnings (conversion, content, what works)

- **A detail page is worth one request per posting, but only where the store
  has no text (19/10).** The two server-rendered boards keep the advert on the
  posting's own page, so `details: true` reads it. The first version read it for
  every posting on every run: 66 pages, 2:04 of the run spent on the slower host
  alone, and the same again next time. One predicate fixed it — read the page
  when the store holds no text for that URL — and that gave three things at
  once: first fill 244 s, then 5 s and 4 s a run; a page whose fetch failed
  stays textless, which is exactly what asks for it again (self-healing, no
  repair tool); and a posting new today is described on the run that finds it.
  It also exposed the bug that had made the cost permanent: `upsert_job` had no
  way to write a description into a row it already held, so a run could fetch 30
  adverts and store none of them, and the next run fetched them again. Two
  rules: **a board's `details` spends its request on new postings only**, and
  **the steady state is measured, not assumed** — running the same board twice
  (44 s, then 5 s) is what showed the first version was not converging; reading
  the code had made it look like it would.
- **One posting page in ten ships JSON-LD that is not JSON (19/10).** The
  publisher's `JobPosting` block runs members together with no comma between
  them, carries raw newlines inside strings, and closes with a trailing comma.
  A strict parse failed on 3 of 36 postings, and every repair that kept the
  document in one piece (strip trailing commas, `strict=False`) still lost those
  three, because the damage sat in an unrelated member. Reading each field on
  its own — match the quoted value, unescape it as the JSON string it is —
  recovered all 36 and stopped being a JSON parser at all. Same instinct as the
  feed XML repair: tolerate what the publisher actually emits, and keep the
  selftest fed the broken shape so a later "simplification" cannot quietly
  reintroduce the failure.
- **A board's badge is the eligibility; its place field is the employer's
  location (19/10).** JS Guru Jobs prints `Location: Armenia` beside
  `Work Format: Remote / Worldwide` for a posting whose own text says "100%
  remote | Global team", so reading the place span as the restriction would have
  tagged a worldwide role `region_gated` and buried it: the badge is the
  eligibility sentence, the place is where the employer sits, and the place goes
  to `jobs.metadata.employer_location` (10 of the first 30 rows carried a
  Worldwide badge). HiringCafe's derived `is_workplace_worldwide_ok` earned no
  such promotion: it was true for 0 of 120 rows, so it rides in metadata and the
  row keeps the posting's own place string. Same rule as always, one step
  earlier: a flag a board derives has to be checked against a sample before it is
  allowed to speak for the ad.
- **A Cloudflare-walled board is readable through the bridge, at the price of a
  tab (19/10).** HiringCafe answers 403 to every plain request, but its search
  results arrive server-rendered in `__NEXT_DATA__` and 120 rows per page carry
  the employer's own `apply_url`, which is the URL dedupe wants. The read is the
  same bridge the forms use (`tab new <url> --window background` →
  `eval '<js>' --tab <id>` → `tab close <id>`), so it became `mode:
  opencli_eval` with the site's adapter in `scanner/js/`, and it needs Chrome
  open under cron like X Bookmarks. The adapter's whole contract: return `null`
  while the page is still loading and `[]` only when it has loaded and found
  nothing, because that `null` is what makes the caller retry instead of
  believing an empty page. Mechanism and command shapes: `_docs/tooling.md`.
- **A board's `Remote` is not a location: read the eligibility sentence (19/10).**
  Three employers read off their own ATS this sitting all publish the structured
  value `Remote`, and the ad text then narrowed it three different ways: one
  stated its own country list ("we're only open to candidates based in the US, EU
  and UK"), one was really gated to two countries in central Europe once its
  board was read, and one sat beside a third party's `USA Only` tag while its own
  board said nothing at all. The rule already learned for aggregator rows applies
  to ATS fields too: `Remote` means "not in an office", not "open to you". Read
  the ad's own eligibility sentence before ranking a row, and prefer a field that
  carries a region (`Home based - Worldwide`, `Remote - Global`) over one that
  carries none. Same sitting, the well-known employers in the high-score band
  resolved to US-only or a named short list, so a widened net is still mostly a
  net of US roles; say so rather than implying otherwise.
- **A pure-function selftest cannot see a broken query (18/10).** Section 1 of
  the digest was rewritten to compare an event's `from_status` with its
  `to_status`, and it crashed the entire build the first time a status event
  landed in the window: the column was never added to the query's SELECT list,
  so `row["from_status"]` raised `IndexError` inside the renderer. All 40
  selftest cases passed the whole time, because they exercise the pure helpers
  and never build a digest from rows. The lesson is not "write more tests": a
  change to what a query RETURNS has to be exercised against a database, and the
  cheapest proof is running the real command on real rows before believing it.
  It surfaced only because the work was done, which is the argument for doing the
  work in the tool rather than reasoning about the tool.

- **An aggregator row is not evidence of where a posting hires (18/10).** Three
  of the six best-looking leads in one sitting had an empty `location` and were
  gated in fact: the employer's own posting said USA/Canada, a single country,
  or "you are based in the US, travel within a day". Two others were genuinely
  worldwide, and both said so in a structured field the aggregator never
  carried (`Anywhere`; "based elsewhere, you'll be hired via our global employer
  partner"). Ashby and Greenhouse both publish the whole board as JSON
  (`api.ashbyhq.com/posting-api/job-board/<slug>`,
  `boards-api.greenhouse.io/v1/boards/<slug>/jobs`), so verifying an employer
  costs one fetch, not a browser session, and the board also reveals when the
  role we hold has been replaced by a different one. Write the employer's own
  value into `jobs.location` and let `classify` derive the tag from it; keep the
  provenance in `jobs.metadata.employer_ad`.
- **Widening the gate revealed gating, not options (18/10).** Of 40 postings
  matching the newly-added role families, the AI and forward-deployed ones were
  almost all US-resident, single-country or region-list-only, and the eligible
  remainder were leadership roles asking for prior people management — a fact
  the profile does not carry at all. The honest answer was a senior IC role
  outside the new families. Buying a wider net is only half a decision; the
  other half is what the net comes back with, and that is worth reporting to the
  person rather than working around.
- **A derived view must not hold state (18/10).** The digest could remind but
  never clear: what the person had already dealt with lived in nobody's records,
  so the same items reappeared. A lead read and rejected had no command at all,
  only a SQL statement, which is why `dismiss --job N --reason` exists, and the
  digest became one living file whose section 1 is what changed since the
  previous rewrite, read from the `Refreshed:` line it carries.
  The bank's `status` column was the same defect wearing a command: `approve
  --from-app N` was added to record that a sent answer had been read back, and
  what it actually recorded was that the command had been run — all 18 rows
  read `approved` after one call, and only 10 had ever been on a submitted
  application. Submission already IS the review, so the state is now derived
  from the instance ledger (`unsent` / `sent` / `revised` / `retired`) and
  nothing approves anything. Two rules: if an action has no command, the action
  never gets recorded; and a state that can be derived must never be certified
  by hand, because the certificate outlives the truth it stood for. The one
  exception proves the rule: an action with no row behind it at all ("create the
  resume variant") has nothing to be derived from, so it needed a store of its
  own (`todos`, `review todo --add` / `--close`) rather than a line in the file.
  The page still holds nothing; the row does, and closing it is the lifecycle.
- **The scorer's blind spot was role families, twice (18/10).** First a fixed
  nine-phrase title gate that zeroed whole engineering families, then a blanket
  `\bmanager\b` veto that swept Engineering Manager out along with the marketing
  and sales managers it was aimed at, and a keyword list with no AI vocabulary
  at all while the titles arriving were AI Engineer and LLM Engineer. The gate
  is a pair of readable lists now: the vetoes name kinds rather than a whole
  word, and `ai`, `llm`, `rag`, `nigeria` and `lagos` score. The promoted
  families are the check: the re-score moved 106 rows and put four
  Engineering Manager roles that had scored 0 into the lead band. Anything the
  person names as a target belongs in `keywords.jsonc`, not in a chat thread.
- **The resume is a floor, not a ceiling (18/10).** A technical answer drafted
  from `resume.pdf` alone seriously undersold the candidate: the resume omits
  Cassandra, ClickHouse, Heroku/Vercel/Netlify/Cloudflare, bare-metal with
  Dokploy/Coolify/Kamal, and most of the AWS/Azure/GCP surface. Ask for the
  real tech surface before writing any technical or infrastructure answer, then
  keep claims calibrated the other way too (Go: general side-project and
  exploration experience, not enterprise production).
- **Name the employer's own product when the person has run it (18/10).** The
  strongest thing in a technical answer is not the longest stack list, it is
  "I have set this up in production" about the exact system the company sells.
  For the database platform applied to (#539): Auth, Row Level Security and
  Realtime websockets wired into NestJS. Ask at intake which of the employer's
  products the person has used before drafting, because it will not be in the
  resume.
- **The score was a fixed title gate, and it hid whole role families
  (18/10, fixed the same day).** `scanner/keywords.py` scored 0 unless the TITLE
  matched one of nine configured phrasings, then took weighted coverage of a
  20-term `any` list that predated the verified skills surface. Measured on the
  live DB: 383 of 455 bookmarked postings scored 0, the maximum anywhere was 45,
  and 104 score-0 rows had titles that plainly named one of our roles
  (`Senior Frontend Engineer, React/Typescript`, `SDK Engineer`, `Cloud
  Security Engineer`). Now
  the gate is a rule with an admit half and an exclude half, the vocabulary is
  the verified surface in three weight tiers, and the denominator is the core
  tier rather than everything, so the tail extends the scale instead of
  compressing it. Re-scored: 50 postings at 50+, 114 at or above the threshold.
  Two learnings worth keeping: **a scoring change needs a re-scoring pass**,
  because `upsert_job` only refreshes `last_seen_at` and the stored score is
  therefore historical (hence `scanner/tools/rescore.py`); and **check what a
  score promotion actually promotes** (`rescore --top 20`) before trusting it,
  which is how the `engineering`-vs-`engineer` false negative and the
  `react native` leak showed up.
- **Do not pad an open source answer with a trivial public repo (18/10).** The
  person struck a small public Pulumi repository out of this answer: next to the
  rest of their experience it read as padding, and the question is a claim about
  contribution, so a weak repo weakens it. Say plainly that upstream patches are
  absent and name only what stands on its own. The general rule: their own
  standard for what represents them beats a "something is better than nothing"
  reflex.
- **An Ashby employer screens from its board index (18/10).** The board page
  lists every posting with its structured location, so eligibility for a whole
  company is one page read and the Location check becomes cheap enough to do
  even when a role looks obvious. A second posting at the same employer is not a
  copy of the first (the follow-up form dropped one required textarea and added
  two other fields), so fields get enumerated every time.
- **An ATS form has no draft.** A session tab that returns to `about:blank`
  loses every field. Fill in one pass and hand over for submission at once.
  Ids also regenerate per load on Ashby. Details: `_docs/tooling.md`.
- **Verify eligibility on the EMPLOYER's page, not the board's copy (18/10).**
  A Senior Full Stack role read "anywhere in the world (UTC-4..UTC+4)" on a
  remote board and the scanner tagged it `worldwide`, but the employer's own
  Ashby page listed `Serbia; Croatia; France; Poland; Portugal; Spain` (job
  #485). Aggregator text is a hint; the employer's structured ATS field is the
  fact. Check it before filling anything, and archive with `reason_for_archive`
  when it fails. Playbook: `_docs/ashby.md`.
- **Funnel was mis-shaped, not the scanner (18/10).** Of 195 real postings, 77
  named the US and only ~6 stated worldwide; Indeed/LinkedIn (JobSpy) supply
  mostly "Remote, USA". The fix is a *tag*, not a filter: `region_scope` +
  `region_evidence`, report sorted by scope first, nothing hidden. Africa-only
  filtering would be the wrong lesson — a US company posting worldwide is a
  first-class lead. Recovery after the reset: 399 → 459 jobs.
- **Eligibility is about the stated restriction, not the company's country.**
  "USA timezones"/"US hours"/"US clients" are overlap wording, NOT bars
  (profile accepts ET afternoons). A list mixing regions ("Europe, USA, Canada,
  APAC") is `region_gated`, not `us_only`. Bare US state names ("Kansas") DO
  count; two-letter codes are skipped (DE/IN/CA collide with countries).
- **A `region_gated` list can include you or exclude you (18/10).** The tag
  alone cannot say which, so triage reads the evidence phrase: EMEA, MEA and
  Africa name a region that includes West Africa and sort *above* `unknown`;
  Europe alone, AMER, APAC and the Gulf sort below it. Board abbreviations
  (AMER, EMEA, APAC, MEA) are location strings in their own right and were
  missing, so rows like "Remote, AMER" read as "no restriction stated".
  `covers_home()` + `scope_rank()` are the single home for that vocabulary; the
  scanner report and the digest both call them, so they cannot drift.
- **A bookmark stub can make a real job unscorable (18/10).** One X bookmark
  carried three role titles, an address and a close date and nothing else: score
  0, scope `unknown`, while the employer's own ad named the stack, the level and
  the location. Recover the ad and store it under `jobs.metadata.employer_ad`,
  leaving `raw_text` as scraped (a re-scan overwrites `raw_text`), so the row
  keeps its provenance and can be re-read. This is why the digest's score-0
  table orders newest first, and why it drops any row that already has an
  application: a close date rides on a new posting, and a score of 0 carries no
  ordering information at all.
- **Email applications are a second channel (18/10).** Some postings name an
  address instead of a form ("send your CV to ..."), which skips the whole fill
  runbook: the work is the draft plus the checks around it (address on the
  employer's own domain, real ad recovered, From address recorded, the ad's own
  subject-line instruction followed). Draft lives in
  `artifacts/applications/<date>-<company>-<role>.md`, application row
  `method='email'`. The reply lands in the mailbox, so the 7-day follow-up
  reminder points at the mailbox: nothing reaches the database by itself, and
  `review reply` is what records it. Section in
  `_docs/team/application-specialist.md`.
- **Emphasis is tailored; the FACTS are not (18/10).** Deliberately leading with
  PCI DSS for a regulated payments employer is not a commitment to lead with it
  on a dev-tools one, so the two belong in different stores: atomic facets and
  the user's own preferences in `profile.jsonc` (`experience.facets` is a list of
  true statements, never one chosen emphasis), and the wording actually sent for
  a role in the question bank (`kind = application`). The bank is what makes the
  next application faster instead of merely different. Record what went out as
  the answer, not a skeleton: the derived state compares the answer against the
  instance ledger, so a placeholder canonical reads `revised` forever and raises
  a warning that can never clear. The reusable rule goes in `--reasoning`.
- **An aggregator's "we hire globally" is not the employer's region tag (18/10).**
  One employer tags its own board Global / AMER / EMEA / APAC; the aggregator row
  for an AMER role said "We hire globally", which flattened that tag and let the
  role rank as `worldwide` and eligible. Triage order now reads the region word,
  but the tag itself still comes from stored text: check the employer's own page
  before treating such a row as open, exactly as with the structured Ashby
  Location field. Two occurrences now, so treat a board copy as a hint by default.
- **`upsert_job` refreshes only `last_seen_at`** for a job it already has (plus
  a description it never had and the score that earns, which is how the
  detail-page boards land their adverts), so any other improvement to an
  extractor reaches nothing stored earlier. Derivation must be a re-runnable
  pass: `classify` (region), `enrich_companies` (RSS title), `enrich_bookmarks`
  (tweets).
- **Feeds hide the employer in the title.** Real Work From Anywhere ("Role at
  Acme") and WWR ("acme: Role") shipped 152 rows as `Unknown`; 113 recovered
  named employers. `Unknown` rows are invisible to any by-company lookup, so
  they silently vanish from a shortlist.
- **X bookmarks DO hold real jobs** — the user was right to push back. 18/50
  read as postings once parsed (a Nigerian fintech hiring backend devs with a
  stated close date, a couple of YC-stage startups, several well-known remote
  companies); before this they were all score-0 `Unknown` rows. Some false
  positives (a startup fellowship, a "reverse engineer" musing) — the flag is
  advisory, and a bookmark's contents stay in the gitignored DB.
- **New verified sources (18/10):** Jobicy (mapped API; `jobGeo` is a direct
  region signal: "Anywhere"/"USA"/country lists) and Jobspresso (dev-category
  WP feed; namespaced `job_listing:company`/`:location` + body in
  `content:encoded`). Arbeitnow verified but NOT added: German on-site roles,
  no remote filter, would flood the board.
- **Sources added 19/10, cheapest path first:** WWR's full-stack and
  devops/sysadmin categories (now three feeds under one board row, 95 items
  deduped from 116), JS Guru Jobs and JavaScript Jobs (server-rendered lists,
  no feed and no JSON, parsed by pattern; the posting's own page is read for
  rows the store has no text for, so they score on the advert: best rows 99,
  previously title-only), and HiringCafe (browser-read, above). All four are
  listed in `db/seeds/boards.jsonc`; a fresh clone gets them from
  `python3 -m db.seed`.
- **`opencli` must be on PATH for the scanner's bridge modes (HiringCafe, X
  Bookmarks).** Under cron it reported "not installed" for months: cron's PATH
  is minimal, so the X-bookmark board was attempted daily and never ran.
  `cron/daily_scan.sh` exports `~/.local/share/vite-plus/bin` (opencli and node
  live there; no interpreter, so prepending it changes nothing else). Off cron,
  in-shell, that dir must be on PATH too. **The schedule itself is off (19/10):**
  runs are hand-triggered (`python3 -m scanner`), and X Bookmarks carries
  `on_demand` so a full run reports it and skips it — `--board 'X Bookmarks'` is
  how it runs, when Chrome is open and the user says so. `./cron/install.sh`
  puts the 06:30 line back; `--remove` takes it out.
- **Two interpreters, and cron's was the one without JobSpy (19/10).** Cron ran
  `/usr/bin/python3`; an interactive shell runs anaconda's python3, which is the
  one with `jobspy` installed — so Indeed, LinkedIn and ZipRecruiter reported
  `No module named 'jobspy'` every night and were only ever scanned by hand.
  With the schedule off this surfaces only if cron is re-installed; in-shell
  runs have JobSpy. Deliberately left alone (changing the interpreter is the
  user's call), and the fix is one line in `cron/daily_scan.sh`.
- Always check location + sponsorship before filling; archive early with `reason_for_archive` in job metadata.
- Full semi-auto loop validated 17/10 (application #1, applied) and twice more
  on 18/10 through Ashby (applications #3 and #4, applied): the runbook in
  `_docs/team/application-specialist.md` is proven — form bypass → agent
  fill → base64 resume embed → human review + reCAPTCHA + Submit →
  confirmation page is the success signal. DB chain:
  jobs → applications (`ready_to_apply` → `applied` + `applied_at`) →
  application_events.
- Dedupe gap: same job from multiple boards lands as separate rows (one
  employer appeared as #31/#32/#48) — dedupe by company+title when applying.
- X-bookmark jobs (50) are mostly un-enriched tweets: company/title often "Unknown", score low — enrich before considering.
- Question bank added 18/10 (`0002_question_bank.sql`): 8 prior FAQ entries
  imported via `import-faq`. Lesson that motivated it: the FAQ's
  `Action: Add to profile as compensation_expectation` never landed in
  `profile.jsonc`, so the promotion loop was lossy — `questions promotions`
  now lists those. Known limit: `lookup` matches on shared words, so a form
  wording with no word in common misses until the phrasing is added as an alias.
- **A control that says the click succeeded can still have committed nothing
  (18/10).** Two react-select fills on the same Greenhouse form came back
  `{clicked: true, matches_n: 1}` and left the field empty; the same option
  went in immediately once its highlight was walked onto with the arrow keys and
  Enter was pressed while the menu was open. Verify the committed value, never
  the click, and mind the trap that made the first check meaningless:
  `closest('[class*=select]')` matches the input itself, so the single-value
  lookup finds nothing and every field reads as uncommitted, including ones that
  are set. Recipe and guards: `_docs/greenhouse.md`. Same sitting, same shape of
  problem: one board's school picker is backed by a list of 2466 schools, and all
  25 pages of it contain no Nigerian school at all, so the person's university
  cannot be picked at any spelling. The field was optional, the resume carried
  the education, and saying so was better than substituting a school that is not
  theirs.
- **Our own bookkeeping must never silence a reminder (18/10).** The 7-day
  follow-up reminder is derived, not stored: `applications.applied_at` plus a
  contact check. That check counted any `interview`, `offer`, `rejection`,
  `note` or `follow_up` event, and two of those are OURS rather than theirs: a
  `note` ("recon done", "form filled in one pass") and our own follow-up. So
  recording our own work cleared the reminder. The signature is worth
  remembering, because it failed exactly where the work was best: the better an
  application was documented, the more reliably the reminder disappeared, and a
  freshly submitted one read "no action (a reply is on record)" with nobody
  having replied. One list now defines contact (`SIGNAL_EVENT_TYPES` in
  `db/tools/review.py`), `reply` carries contact that moves no status, and
  `review reply` is the command that writes it, because an action with no
  command is an action that never gets recorded. The mechanism, stated
  concretely: `_docs/jobs-db.md`, "The follow-up reminder".
- **A salary figure belongs to the person and can move an order of magnitude at
  submit time (18/10).** The prepared form carried the bank's
  $180,000-$220,000; they replaced it with $35,000-$50,000 on their own reading
  that the role is remote, and submitted. The process worked (the figure was
  handed over as theirs to confirm), and the lesson is what to keep: the sent
  figure goes into the instance ledger, the canonical stays a *stance*, and the
  row then reads `revised`, which is honest rather than broken. Still open, and
  worth asking again: whether remote roles are priced against the local market
  or against the employer's own published band, because a US employer's band for
  comparable work sat an order of magnitude above what went out.
