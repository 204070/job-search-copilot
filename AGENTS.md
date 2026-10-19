# Mission

Help me find suitable roles, prepare truthful and competitive applications, manage professional relationships, prepare for interviews, and improve my probability of receiving suitable offers.

Optimize for quality of opportunities, interview conversion, offer quality, and sustainable effort—not raw application volume.

## Memory & learning loop

- Read `MEMORY.md` before any application-related work; **record every learning
  after a meaningful event** (application sent, ATS observation, recruiter
  reply, rejection, tooling discovery). Put the detail and the worked case in
  the file that owns it (`_docs/<ats>.md` per posting type, `_docs/tooling.md`
  for browser work, `_docs/scanning.md`, `_docs/jobs-db.md`, the runbook in
  `_docs/team/`), and add **one short rule with a pointer** to `MEMORY.md`.
  MEMORY.md is an index: it must stay short enough to read in full. No secrets,
  private contacts or employer names in it, because the repo is public.
- Application answers are not re-derived each time: query the question bank
  (`python3 -m db.tools.questions lookup "<field label>"`) before filling, and
  record what the form asked at handover. `artifacts/faqs/*.md` are generated
  from that bank, not hand-written. Detail: `_docs/jobs-db.md`.
- Private documents live in `artifacts/` (see `artifacts/README.md`); daily
  lead reports in `logs/leads/`.

## Application workflow (semi-automatic)

- Agent drives my real browser via OpenCLI (`--profile <name>`; session pattern:
  `opencli browser <session> <cmd>` — state/fill/upload/screenshot/extract),
  drafts forms, emails and documents; **I review and submit**. Full automation
  comes later, once the learning loop is stable. The application runbook is
  `_docs/team/application-specialist.md`.