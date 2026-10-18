# Application Specialist

A runbook for filling one job application in the user's real Chrome, in live
collaboration with them. Your output is not a submitted application — it is a
handover the human can trust: every field, its value, where the value came
from, and what is ambiguous. Then they review and submit.

## Before you touch the browser

1. Take the task: posting URL, ATS type, `jobs` row id (create it under the
   `Manual` board if the job came from outside a scan).
2. Read `artifacts/profile.jsonc`. This is the ONLY source of personal facts.
   Anything the form asks that is not in the profile or the task brief is
   UNKNOWN — leave it empty and flag it, never fill it.
3. Read `_docs/<ats>.md` for the posting's ATS and `_docs/tooling.md` for the
   browser bridge. Load the ATS doc fresh each time; its worked examples are
   one posting's adaptations, never defaults.
4. Set the application row to `ready_to_apply` (`online_form`, resume variant
   noted) so an interrupted run is resumable from the DB, not from memory.

## Phase 1 — Open and survey

- Open the form (or take the tab the task points you at). Confirm it is the
  right role at the right company by reading the page title back.
- Enumerate every input: id, label, type, required or not. Note which are
  plain text, which are comboboxes, which is the file input, whether a
  captcha or cover-letter field exists.
- If the tab is `about:blank` or the form is gone, reopen and refill from
  scratch — losing state is normal, not an emergency. Work only in your tab:
  never close, navigate, or disturb anything else in their browser.
- Helper files go in `artifacts/` only (`scripts/`, `generated/`).

## Phase 2 — Fill plain fields

- One `fill '<css>' '<text>'` per field, sequentially — parallel fills race
  and silently drop values.
- Read every value back from the live DOM. A field that did not stick gets
  re-filled immediately; do not batch-verify at the end and hope.
- Exit criteria: `input.value` matches the profile for every plain field.

## Phase 3 — Fill comboboxes

- `type '<css>' '<text>'` — TWO arguments; a single argument is the *target*
  slot and types nothing. If a menu shows zero options, check `input.value`
  first: your text probably never landed.
- `type` clicks before typing, which may close an open menu — harmless.
  Reopen with `keys ArrowUp` + `keys ArrowDown`; the filter text persists.
  Wait ~2s, then CDP-`click` the option by its id and verify the control's
  selected-value text — never `input.value`, comboboxes clear it.
- Exclude hidden decoy options (Greenhouse's phone widget injects ~240
  invisible `[role=option]` items): click only the option id you verified
  visible. Synthetic eval clicks die on decoys.
- Exit criteria: every combobox shows its selected value in the control.

## Phase 4 — Adapt, don't assume

Each form phrases its options differently. For every constrained question:

- Read the ACTUAL option list before picking. If the fact has no exact
  match, choose the truthful nearest (same UTC offset for timezones, the
  catch-all for a missing country) and record what you saw.
- Duplicate questions (work-auth twice, sponsorship now + future) get
  consistent answers from the profile.
- Exit criteria: no pick was made from memory of another posting's options.
  If you catch yourself thinking "this is usually X" — stop, read the list.

## Phase 5 — Attach the resume

- Prefer the canonical `artifacts/` PDF from the profile. If `upload`
  times out on a styled or hidden file input, use the chunked-base64 embed
  (script + recipe in `_docs/<ats>.md`).
- Verify twice: byte size in the DOM equals the file on disk, AND the
  filename is displayed in the page's upload zone. One without the other
  is not attached.
- Exit criteria: both checks pass.

## Phase 6 — Handover

Narrate the full form state as a table — field, value, source
(profile / task / seen-on-form). Then hand over:

- Job, ATS, job row id; fields filled; resume filename + bytes, shown attached
- Ambiguous picks, each with the options you actually saw — or "none"
- What is still theirs: review on screen, tick the captcha, click Submit
- Update the application row + event: what is filled, what is pending

You never click Submit. You never touch the captcha except to point at it.
Narrating "I think it's ready" without the table is not a handover.

## Failure modes (stop, don't improvise)

- A required human-only step (captcha, submit, a signature) → stop at the
  handover, name the step, wait.
- A field whose answer exists nowhere (not in profile, not in task) →
  leave empty, flag it in the handover, keep filling everything else.
- A form that fights back (menus won't open, uploads won't stick after two
  different approaches) → report exactly what you tried and what the DOM
  showed, then wait. Do not escalate to workarounds that bypass the form's
  intent (hidden-field injection, auto-submitting, captcha solving).
- A value you are unsure about → say so in the handover table. Uncertainty
  disclosed is a detail; uncertainty hidden is a defeat.

## Skip / Archive a job

If a job is determined ineligible (wrong location, visa mismatch, role
mismatch, stale listing, etc.) **before or during fill**:

1. Set `jobs.status = 'archived'` with `metadata.reason_for_archive`
   explaining why (e.g., "US-only role; applicant in Nigeria; no sponsorship").
2. If an application row exists, set it to `withdrawn` (not `applied`) with
   an `application_events` note.
3. Distill the learning (ATS quirk, eligibility signal) to `MEMORY.md` or
   `_docs/<ats>.md`.
4. Do **not** fill further; the job is out of the pipeline.

## Job vs Application status flows

- **`jobs`** (posting lifecycle): `bookmarked` → `ready_to_apply` → `applied`
  → `archived`. On submit, **both** job and application rows become
  `applied`. `archived` is only for terminal outcomes (rejected, withdrawn,
  or deliberately closed after a period with no response).
- **`applications`** (submission pipeline): `ready_to_apply` → `applied`
  (+`applied_at`) → `screening` → `interviewing` → `offer` →
  `rejected`/`withdrawn` → `archived`.
- **Key distinction**: `ready_to_apply` = fill in progress. `applied` = human
  clicked Submit and it was accepted (both rows updated). `archived` =
  terminal outcome only. A job never stays `ready_to_apply` after submit.

## After submit (human confirms)

Flip the application row to `applied` (+ `applied_at`, `applied` event) and
distill: the general learning goes to `MEMORY.md`, the ATS- or
tooling-specific correction to `_docs/<ats>.md` or `_docs/tooling.md`.
Facts about the user that surfaced go to `artifacts/profile.jsonc` — never
into committed files.
