# Ashby (jobs.ashbyhq.com)

Lazy-load this file when applying through an Ashby posting. It describes the
method only. A posting's own form decides its fields, and a worked case for one
posting lives in `artifacts/`, never here: no employer, board or personal value
is written into a committed file.

## Finding the real form

- The job page is `jobs.ashbyhq.com/<org>/<job-uuid>`, with two tabs:
  **Overview** and **Application**. The form lives at
  `jobs.ashbyhq.com/<org>/<job-uuid>/application` — open that directly in the
  session; no iframe hunting needed.
- The Overview tab is where the employer's machine-readable facts sit:
  `Location`, `Employment Type`, `Location Type`, `Department`.
- `[N]<a id=job-overview …>` / `id=job-application-form …` in `opencli state`
  are the tab controls if a direct open is ever not enough.

## ELIGIBILITY: the structured Location field is authoritative

**Read the Overview tab's `Location` before filling anything.**

- Ashby's `Location` is a structured employer field, not marketing copy, and it
  is what the ATS shows recruiters. Where it disagrees with the posting text,
  the field wins.
- **Screen a whole employer from its board index, before opening anything.**
  `jobs.ashbyhq.com/<org>` lists every open posting as
  `Department • Location • Employment type`, so one page read gives the
  structured location for all of them (`Remote, Global` vs `Remote, AMER` vs
  `Remote, EMEA`). Screening then costs one page instead of one posting at a
  time, which makes the check cheap enough to run even when a role looks
  obvious.
- Compare that list with the applicant's own country in `profile.jsonc`
  (`location.country`). A UTC band in the ad's prose, a "work from anywhere"
  sentence or an aggregator's remote badge is a hint about overlap, not proof
  of eligibility.
- Never fill six fields before checking the one that decides it. When the check
  fails, archive the posting with `reason_for_archive` and stop.

## Field inventory: what an Ashby form carries

An optional **"Autofill from resume"** panel sits above the form (its own file
input plus an `Upload file` button) and can populate the system fields. It runs
after the agent has filled, so read the blocks back at handover: Phase 1 of
`_docs/team/application-specialist.md` covers what that means.

**A second posting at the same employer is not a copy of the first.** A
follow-up form can drop a textarea, add a required async/remote textarea, add a
`Twitter / X profile` field, and turn a "where did you hear" radio set into a
free-text input. Same employer, same ATS, different form: enumerate the fields
every time.

| field | control | value |
|---|---|---|
| Name | `#_systemfield_name` text | profile `name` |
| Email | `#_systemfield_email` email | profile `email`, the address the attached CV prints |
| Resume | `#_systemfield_resume` file | `resumes.canonical_pdf`, as it is |
| Passport Country, Country of Residence | text | profile `location.country` |
| Are you over the age of 18? | Yes / No buttons | a profile fact if it holds one, otherwise ask |
| Experience with most relevant tech | textarea | question bank first, else the prose rules below |
| Github Profile, Linkedin, Twitter / X | text | profile `github`, `linkedin`, `x` |
| Open source contributions | textarea | truthful: own public repos only |
| Where did you hear about this vacancy? | radio set or free text | the board that actually surfaced the posting |
| Referrer name | text | blank unless the user names one |

- The question set varies by posting: a pay, sponsorship, notice-period or
  start-date field may or may not appear. Read the form, and do not import an
  answer from another posting because the employer is the same.
- Plain `input type=text` / `textarea`, placeholder `Type here...`. No
  react-select comboboxes, so the Greenhouse combobox recipe does not apply.
  Yes/No are buttons, not a checkbox.
- The resume input is `input[type=file]`; see Phase 5 for the attach method.

## Filling it in one pass

- Enumerate the fields first, then stamp each input and textarea with a
  `data-fill="<key>"` attribute chosen by matching its visible label, and do
  every subsequent `fill` through `[data-fill="<key>"]`. Ashby regenerates the
  UUID prefix on each render, so a selector captured from one read can be dead
  by the time the fifth field is filled; the stamped attribute survives, and the
  whole pass runs without re-reading ids between fields.
- `opencli upload '<selector>' <path>` answers
  `{"code":-32000,"message":"Not allowed"}` (the styled attach UI swallows the
  chooser), so use `artifacts/scripts/embed_resume.sh <path>
  '#_systemfield_resume'` — note the Ashby selector, since the script defaults
  to Greenhouse's `#resume`. Confirm afterwards by reading `input.files[0].size`
  back and comparing it to the file on disk: a filename in the drop zone alone
  is not proof the bytes arrived.
- Read the page back before handing over: every required field non-empty, no
  `[aria-invalid=true]` or error nodes, submit enabled, and
  `textarea[name=g-recaptcha-response]` still empty (that one is the human's).
- Questions to expect: a link to a code sample the person is proud of plus why,
  an optional technical writing sample, and a free-text "how did you hear about
  us" that takes the board which actually surfaced the posting.

## Free-text answers

- Take the facts from `profile.jsonc` and the attached CV. Ashby custom
  questions are read by engineers, so name concrete systems, not adjectives.
- **Respect the honesty notes in `profile.jsonc` `skills`.** A technology the
  profile records as side-project or exploratory is not written up as
  production experience, and a project it records as small is not offered as
  depth. Those notes exist so the strongest claim in the answer stays true.
- **Name the employer's own product when the user has run it**, in the
  paragraph where it belongs. Ask at intake which of their products the user
  knows, because the CV will not say. Written plainly it reads as use of their
  system; written vaguely it is one more claim in a stack of them.
- **Do not pad.** A trivial public repository weakens a claim about
  contribution. Name only what stands on its own, and keep an intent to
  contribute to one sentence.
- Field ids change per page load (see `_docs/tooling.md`): prefer stable suffix
  selectors such as `label[for$="-labeled-radio-5"]`.

## Session fragility

The tab can come back as `about:blank` between turns, and Ashby keeps no
server-side draft, so a lost tab loses the entire fill. Fill in one pass, then
hand over for immediate review and submission. Re-read `tab list` before
resuming. Details and guards: `_docs/tooling.md`.

## Human-only

- Final review, Submit. Never click Submit.
