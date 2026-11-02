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

## One job, several titles

A board can publish the same role under three names. Compare the descriptions
before you treat them as separate postings: on 31/10/2026 one employer listed
Full Stack Engineer, Founding Engineer and AI Product Engineer, and the three
`descriptionHtml` values were byte-identical at 4,528 characters, with the same
Location, Location Type and Employment Type. Applying to more than one is
applying to the same job twice, which the two-applications-in-thirty-days notice
turns into a waste of the second slot.

- Hash or diff the description text across the board JSON. Equal text plus equal
  structured fields means one posting.
- A posting id that is absent from the board JSON and answers 404 is removed, not
  duplicated. Archive it with that reason.

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

- **Yes/No questions are buttons, and an input-only inventory misses them.**
  Measured 1/11/2026 on the Hex form: two required US questions ("Are you
  legally authorized to work in the US?" and "Will you now or at any time in the
  future require visa sponsorship?") rendered as `<button>Yes</button>` /
  `<button>No</button>` inside `[data-field-path="question_<id>"]`, with
  `aria-pressed` as the only state. A field read that collects `input`,
  `textarea` and `select` returns nothing for them, so the form looks complete
  while two questions are unset. Read the buttons too, and group them by the
  nearest `[data-field-path]`: the question text is the previous sibling of the
  button row.
- **A real CDP click toggles an Ashby radio; a synthetic one does not.** A JS
  `.click()` on the label plus a dispatched `change` reported `checked: true`
  and then read back empty. `opencli click 'label[for="<the full id>"]'` stuck.
  The ids carry a UUID prefix that changes per render, so read the exact `for`
  value first rather than guessing a suffix.
- **"Anything else you want to add?" is a single-line input.** Newlines are
  stripped and `fill` answers `{"code":"value_mismatch"}` with the paragraphs
  joined. Write one paragraph.
- The question set varies by posting: a pay, sponsorship, notice-period or
  start-date field may or may not appear. Read the form, and do not import an
  answer from another posting because the employer is the same.
- Plain `input type=text` / `textarea`, placeholder `Type here...`. Most
  fields are this shape. Yes/No are buttons, not a checkbox.
- **A type-ahead combobox can appear** (seen 20/10/2026 on a "How did you
  hear about this role?" question): `role=combobox`, placeholder
  `Start typing...`, a closed option list. It is strict: a typed value that
  matches no option is cleared on blur, so the free-text answer dies and the
  Greenhouse-style "name the board" pattern does not survive. Read the real
  option list, take the form's catch-all when the fact has no exact match,
  and prove the picked value survives a blur. The popup can read
  `aria-expanded=true` with nothing rendered; typing filter text is the
  deterministic way to reopen it. Click only a verified visible
  `[role=option]` id (react-aria ids work through `[id="<the-id>"]`).
- **A location autocomplete can be country-level only.** Measured 2/11/2026 on
  a `Where are you located?` field: `role=combobox`, `aria-haspopup=listbox`,
  placeholder `Start typing...`. Typing a city (`Lagos`) rendered a real
  listbox with the text `No results`, and the input still held the typed city
  with `aria-expanded=true`. Read back, it looks answered; nothing is
  committed, and there is no option to commit. Typing the country name
  (`Nigeria`) produced one `[role=option]` with `aria-selected=true`, and a
  CDP click on it closed the listbox and left `Nigeria` in the field. When a
  city name returns no options, try the country before assuming the control is
  broken, and treat `aria-expanded=true` after a fill as "uncommitted".
- **A radio click can report success and not stick.** The same pass clicked
  four labels; all four answered `{"clicked":true,...,"hit":"target"}`, and
  three read back checked. The first one (`LinkedIn`) read back unchecked
  while the other three held. Click the label again and re-read the whole
  `input[type=radio]:checked` set, rather than trusting one click.
- **Radio clicks can blank a text field filled earlier.** After the radio pass
  the location input was empty again. Read every field back after the radios,
  not only after the text pass.
- **Visible text is not proof of a commit.** A single-select keeps typed text
  in the box whether or not the choice was accepted, so read the control after
  a blur, not after the click. The cheap test: type a string that matches no
  option, blur, and read the field again. When the control shows the chosen
  value, the choice was committed; when the garbage text stays, nothing was
  picked and the field is still empty (20/10/2026, country and location
  autocompletes on one form). Typing the exact option name and tabbing away
  committed both; a plain click on the option did not.
- **Read the notice under the form title before a second attempt.** Some
  postings limit applications per job (two in 30 days, no reapply within 60
  days unless an offer follows). A fill that goes wrong is not always
  repeatable, which is one more reason to fill the whole form in one pass.
- A free-text compensation field can carry the employer's published band as
  a range; a numeric single-value field takes one number
  (`_docs/workable.md`). The band is a draft, not a floor: on 20/10/2026 the
  user replaced a posted band with a lower range at review, so hand the figure
  over as theirs to change.
- **Consent radios belong to the user.** Text-message updates and
  interview-integrity analysis are choices, not facts. Leave them unset, name
  them in the handover, and expect the interview-integrity one to be marked
  required, so the user has to click before submit. The data-retention
  acknowledgement at the foot of the form is a consent too, so leave it unset
  and name it. `AGENTS.md` forbids ticking a consent on the user's behalf, and
  a ticked box cannot be defended at review; one click from the user costs
  less than that. Background-check acceptance is the same shape and is also
  theirs.
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
  an optional technical writing sample, and a "how did you hear about us"
  question (free text or the combobox above) that takes the board which
  actually surfaced the posting. Optional Pronouns and a free-text Timezone
  (hint: "To help with scheduling") have also appeared.
- **When the ad itself asks for a note** ("include a note ... tell us why you
  are excited"), the optional "Anything else you think we should know?"
  textarea IS that note: fill it. Draft it from the profile, name the
  employer's product only when intake confirmed the user runs it, and say in
  the handover when the posting is evergreen (no specific pod requisition).

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

- **A captcha can be visible even when the form carries no consent checkbox.**
  On 31/10/2026 the form had no checkbox at all, but a reCAPTCHA Enterprise
  anchor iframe was rendered at the foot of the page and stayed unsolved while
  Submit was enabled. Read for it before the handover
  (`document.querySelector("iframe[src*=recaptcha]")`) so the user is not left
  guessing why Submit does nothing.
- Final review, Submit. Never click Submit.
