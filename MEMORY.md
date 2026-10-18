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
- **Target:** senior remote full-stack (React/TS, Node, Python); scored via
  `scanner/keywords.jsonc`. Resume reality (gitignored detail in
  `artifacts/profile.jsonc`): 7+ yrs fullstack, TS/Node + Postgres, Django/
  Python, AWS→Azure, PCI DSS, fintech. **Resume is a floor, not a ceiling:**
  also Cassandra, ClickHouse, Heroku/Vercel/Netlify/Cloudflare, bare-metal and
  VPS deployments with Dokploy/Coolify/Kamal, Terraform/Ansible/GitHub
  Actions/Jenkins. Go is real but at side-project and exploration level, not
  enterprise production — keep it general when writing answers.
- **Eligibility:** `jobs.region_scope` (worldwide / us_only / region_gated /
  unknown) tags where a posting says it will hire; `us_only` is the only real
  bar. Detail: `_docs/scanning.md` → "Region scope".
- **Identity facts:** `artifacts/profile.jsonc` — read before drafting/filling.
- **Question bank:** `db/jobs.db` (`questions` + `question_instances`) behind
  `python3 -m db.tools.questions` — `lookup` before filling, `record` at
  handover; `artifacts/faqs/*.md` are generated from it (`digest`).
- **Review digest:** `python3 -m db.tools.review` writes
  `logs/reviews/<date>.md` (private, gitignored): follow-ups due, applications,
  next roles, pipeline health, question-bank drafts. Detail:
  `_docs/jobs-db.md`.
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
- **The score is a title gate, and the gate is a fixed list of phrasings
  (18/10).** `scanner/keywords.py` scores 0 unless the TITLE matches one of nine
  configured phrasings (`software engineer`, `full[- ]?stack`, `back[- ]?end`,
  `platform engineer`, `devops|site reliability`, ...), then scores weighted
  coverage of a 20-term `any` list. Measured on the live DB: 383 of 455
  bookmarked postings score 0, the maximum anywhere is 45, and 104 score-0 rows
  have titles that plainly name one of our roles (`Senior Frontend Engineer,
  React/Typescript`, `SDK Engineer - Python`, `Cloud Security Engineer`,
  `Senior Staff Software Engineer`). So the shortlist must be read by title, and
  any "best fit" claim resting on `match_score` is not yet trustworthy. The `any`
  list also predates the verified skills surface (no NestJS, Bun, ClickHouse,
  Supabase, Azure/GCP, Ansible, Pulumi, Jenkins). Fixing the gate needs a
  re-scoring pass, because `upsert_job` only refreshes `last_seen_at`.
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
- **`upsert_job` refreshes only `last_seen_at`** for a job it already has, so
  any improvement to an extractor reaches nothing stored earlier. Derivation
  must be a re-runnable pass: `classify` (region), `enrich_companies` (RSS
  title), `enrich_bookmarks` (tweets).
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
- **`opencli` must be on PATH for the scanner's X-bookmarks mode.** Under cron
  it reports "not installed"; in-shell it works once
  `~/.local/share/vite-plus/bin` is on PATH.
- Always check location + sponsorship before filling; archive early with `reason_for_archive` in job metadata.
- Full semi-auto loop validated 17/10 (application #1, applied) and again on
  18/10 through Ashby (application #3, applied): the runbook in
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
