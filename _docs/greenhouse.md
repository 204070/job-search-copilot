# Greenhouse (job-boards.greenhouse.io)

Lazy-load this file when applying through a Greenhouse posting. Per-posting
option values below are EXAMPLES of adapting `artifacts/profile.jsonc` facts
to one form — never canonical; each posting's lists differ.

## Finding the real form

- Custom careers sites (e.g. an Astro-based company site) embed the form as a
  cross-origin iframe. If the site's Apply button is inert (no network/console
  activity), eval `[...document.querySelectorAll("iframe")].map(f=>f.src)` and
  open the `job-boards.greenhouse.io/embed/job_app?...&token=<gh_jid>` URL
  directly in the session — the form becomes main-frame and fillable.
- Minimal working embed URL:
  `https://job-boards.greenhouse.io/embed/job_app?for=<board-slug>&token=<gh_jid>`
  (no validityToken needed).
- Stale-listing check (board mirrors keep dead gh_jids → careers proxy 404s
  "Job not found"): `boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true`
  (discover the slug by guessing).
- Success signal: submit lands on
  `embed/job_app/confirmation?...&token=<gh_jid>` (tab title
  "Thank you for applying").

## react-select recipe (OpenCLI)

- For combobox inputs use `type '<css>' '<text>'` (two args). Single-arg `type`
  treats its arg as a target → types nothing; `fill` only suits plain text
  inputs.
- **Commit with the keyboard, not a click.** `opencli click` on an option id
  returns `{clicked: true, matches_n: 1}` and still leaves the field empty
  (reproduced twice, 18/10/2026). The path that commits, in order:
  1. `type '<css>' '<full option text>'` so the filtered menu holds ONE option.
     Option indexes are per filtered list, so a wide filter leaves the
     highlight a guess.
  2. Read `aria-expanded` on the input and require `"true"` (one `keys
     ArrowDown` opens it when `type` left it closed).
  3. Walk the highlight onto the exact option by watching
     `aria-activedescendant` on the input, which is where react-select
     publishes the focused option id: press `keys ArrowDown` until it equals
     the wanted `#react-select-<inputid>-option-<n>`. Do not count keystrokes;
     one extra ArrowDown landed the form on the wrong city.
  4. `keys Enter`, and **only while the menu is open**: react-select
     preventDefaults it there, but a closed menu lets Enter submit the form.
- Verify through `[class*=single-value]` inside
  `el.closest('[class*=select__value-container]')`, never `input.value`. Watch
  the trap: `closest('[class*=select]')` matches the input itself, so the
  lookup silently finds nothing.
- City-style comboboxes lazy-load: no options render until filter text is
  entered.
- The School field is an async combobox over a partial list that also has gaps:
  the board's schools endpoint is 2466 schools at 100 per page and ignores the
  query string, so the widget filters only what it has loaded — and a scan of
  all 25 pages found no Nigerian school at all. A Nigerian applicant cannot pick
  their university at any spelling. The field is optional on these forms; report
  that rather than substituting a school that is not theirs.
- The phone widget's dial-code combobox is `#country` (react-select classes
  plus the flag), NOT a country-of-residence question. Set it through
  intl-tel-input's own dropdown: `click '.iti__selected-country'`, `fill
  '.iti__search-input' '<country>'`, then click the option id it renders
  (`#iti-0__item-ng` for Nigeria). The widget then reformats `#phone` to the
  national convention (`8032538103` → `0803 253 8103`).
- The widget injects ~240 hidden `[role=option]` items (`li`, ids `iti-*`) →
  when hunting options for OTHER selects, exclude `!/^iti/`. A synthetic
  eval mousedown+click dies on those decoys.
- **Filling the hidden iti search leaks.** `.iti__search-input` is off-screen and
  the dropdown's `li` items sit in a fixed-position container (so `offsetParent`
  is null and they read as invisible when they are fine). More importantly,
  `fill` on the hidden search input delivers its keystrokes to whatever still
  has focus: on 18/10 the text `Nigeria` was appended to the LinkedIn field,
  which had been filled moments earlier (`...-ng` became `...-ngNigeria`), while
  the search box received it too. Click a neutral element or fill a plain field
  first, and read the previously filled field back afterwards.
- "Toggle flyout" button clicks do nothing; focus/type/keys opens the menu.

## The newer board version: `Country*` is the phone dial code (19/10/2026)

Validated on gh_jid 5389088004 (Alpaca). This board renders in a "remix" build
where two field names mislead:

- **`#country`, labelled `Country*`, is the PHONE dial-code select**, not a
  country-of-residence question. Its options carry the dial code
  (`Nigeria +234`, option id `react-select-country-option-158`), and once
  committed the select displays just `+234`. Read the *option text* before
  answering, and never read `input.value` (the react-select search box stays
  empty): read `[class*=single-value]` inside
  `closest("[class*=select__value-container]")`, as usual.
- **`#candidate-location`, labelled `Location (City)*`, is the location
  question.** The board's `location_questions` carry `Location`, `Latitude` and
  `Longitude`, and the widget fills the coordinates itself on submit, so no
  lat/long input has to be written by hand. Typing `Lagos` returned exactly one
  wanted option (`Lagos, Nigeria`, first in a list otherwise full of Lagos in
  Chile, Mexico, Portugal and Greece), and `aria-activedescendant` was already
  on it, so one `keys Enter` committed it. Press `keys Escape` afterwards: the
  menu stayed `aria-expanded="true"` after the commit.
- Field ids here are the advertised ones (`#first_name`, `#email`,
  `#question_12229452004`), so a selector can be taken straight from the board
  API's `questions` list (`?questions=true`) before the page is even open.
- An `#iti-0__search-input` exists in the DOM even when no visible intl-tel
  dropdown does, so a probe for `.iti__selected-country` can report zero while
  the widget is present. Check for the search input instead.
- **After the base64 embed, Greenhouse consumes the input.** `#resume` is gone
  from the DOM afterwards (React keeps the file in its own state) and the
  `Resume/CV` zone shows the filename. That display is the success signal
  documented above; do not read the missing element as a lost upload.
- The board ends in a `Voluntary Self-Identification` block (`#gender`,
  `#hispanic_ethnicity`, `#race`, `#veteran_status`, plus a disability select on
  some employers). Answer it from `artifacts/profile.jsonc`
  (`self_identification`) rather than leaving it blank; the runbook explains
  why. Read the committed options back off the page, since the wording differs
  between employers ("I don't wish to answer" against "Decline To Self
  Identify").

## Adapting profile facts (worked example: gh_jid 6188234004, 17/10/2026)

- Country of legal residence was a curated 16-country list +
  `OTHER / NOT LISTED`; Nigeria absent → truthful pick OTHER / NOT LISTED.
  Another posting may list Nigeria plainly — always read the actual list.
- Timezone list had no WAT entry and exactly one UTC+1 option
  ("UTC+1 (Central Europe)") → picked it as the truthful GMT+1 match.
- Duplicate questions happen (work-auth asked twice; US sponsorship now +
  future) — answer consistently with the profile.

## Resume upload

- `opencli upload` fails: the real `input[type=file]` (`#resume`, accept
  .pdf/.doc/.docx/.txt/.rtf) hides behind a styled Attach UI that swallows
  clicks → CDP file-chooser interception times out
  ("Page.fileChooserOpened not received"). fetch() from the https page to a
  localhost CORS server also fails (CSP/PNA).
- Working fallback (validated 17/10): chunk the PDF as base64 into
  `window.__b64` via repeated `eval` (zero-pad chunk filenames — lexical glob
  order scrambles base64 and atob fails), then
  `atob → Uint8Array → File → DataTransfer → input.files = dt.files` +
  dispatch `change` (+`input`). Script: `artifacts/scripts/embed_resume.sh
  <pdf>`. The page then displays the filename in the upload zone.

## Human-only

- reCAPTCHA, final review, Submit.
