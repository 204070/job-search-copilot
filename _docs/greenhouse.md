# Greenhouse (job-boards.greenhouse.io)

Lazy-load this file when applying through a Greenhouse posting. Per-posting
option values below are EXAMPLES of adapting `artifacts/profile.jsonc` facts
to one form — never canonical; each posting's lists differ.

## Finding the real form

- Custom careers sites (e.g. Fingerprint's Astro site) embed the form as a
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
- `type` clicks first (may toggle an open menu closed — harmless), then
  `keys ArrowUp` + `keys ArrowDown` to reopen the FILTERED menu (filter text
  persists), wait ~2s, then CDP-`click` the visible option by its react-select
  id (`#react-select-<inputid>-option-<n>`). Verify via
  `[class*=single-value]` text, NOT `input.value` (react-select clears it).
- City-style comboboxes lazy-load: no options render until filter text is
  entered.
- The phone widget (intl-tel-input) injects ~240 hidden `[role=option]` items
  (`li`, ids `iti-*`) → when hunting options for OTHER selects, exclude
  `!/^iti/`. Trusted CDP `click` on options works; synthetic eval
  mousedown+click dies on the hidden decoys.
- The dial-code combobox's own options are `#react-select-country-option-*`
  entries; the national number goes into `#phone` via `fill`.
- "Toggle flyout" button clicks do nothing; focus/type/keys opens the menu.

## Adapting profile facts (example: Fingerprint gh_jid 6188234004, 17/10/2026)

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
