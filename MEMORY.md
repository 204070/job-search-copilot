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
  `scanner/keywords.jsonc`.
- **Identity facts:** `artifacts/profile.jsonc` — read before drafting/filling.
- **Question bank:** `db/jobs.db` (`questions` + `question_instances`) behind
  `python3 -m db.tools.questions` — `lookup` before filling, `record` at
  handover; `artifacts/faqs/*.md` are generated from it (`digest`).
- **Current phase:** semi-automatic applications — agent drafts/fills, human
  reviews & submits. Runbook: `_docs/team/application-specialist.md`.
- **Tool:** OpenCLI Browser Bridge drives my real Chrome (always
  `--profile <name>`; `jobfit` session). Detail: `_docs/tooling.md`.
- **Logs & private docs:** `logs/leads/`; `artifacts/`.

## Application tracking

- Per-application records (job row, application row, events) live in
  `db/jobs.db` (`jobs` → `applications` → `application_events`; rows are
  gitignored). This file keeps only distilled learnings, never the log itself.
- Question bank: `questions` + `question_instances` in the same DB, behind
  `python3 -m db.tools.questions`. `lookup` before filling a form, `record` at
  handover, `frequency` to see what recurs; `digest` regenerates
  `artifacts/faqs/*.md`. Schema and commands: `_docs/jobs-db.md`.

## Reference docs

- Per-ATS playbooks: `_docs/<ats>.md` (have: `greenhouse.md`) — load the
  one matching the posting; adapt `profile.jsonc` facts to that form's
  options case by case, never treat worked examples as canonical.
- Team playbooks: `_docs/team/<role>.md` (have: `application-specialist.md`)
  — the full runbook for a collaborative application fill.
- Also in `_docs/`: `tooling.md` (browser bridge), `jobs-db.md`, `scanning.md`.

## Learnings (conversion, content, what works)

- Always check location + sponsorship before filling; archive early with `reason_for_archive` in job metadata.
- Full semi-auto loop validated 17/10 (Fingerprint, applied): the runbook in
  `_docs/team/application-specialist.md` is proven — form bypass → agent
  fill → base64 resume embed → human review + reCAPTCHA + Submit →
  confirmation page is the success signal. DB chain:
  jobs → applications (`ready_to_apply` → `applied` + `applied_at`) →
  application_events.
- Dedupe gap: same job from multiple boards lands as separate rows (Lemon.io #31/#32/#48) — dedupe by company+title when applying.
- X-bookmark jobs (50) are mostly un-enriched tweets: company/title often "Unknown", score low — enrich before considering.
- Question bank added 18/10 (`0002_question_bank.sql`): 8 prior FAQ entries
  imported via `import-faq`. Lesson that motivated it: the FAQ's
  `Action: Add to profile as compensation_expectation` never landed in
  `profile.jsonc`, so the promotion loop was lossy — `questions promotions`
  now lists those. Known limit: `lookup` matches on shared words, so a form
  wording with no word in common misses until the phrasing is added as an alias.
