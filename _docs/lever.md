# Lever (jobs.lever.co)

Lazy-load this file when applying through a Lever posting. Per-posting values
below are EXAMPLES of adapting `artifacts/profile.jsonc` facts to one form,
never canonical.

## Finding the form, and screening the employer

One fetch, no browser session:

```bash
curl -s 'https://api.lever.co/v0/postings/<slug>?mode=json'          # whole board
curl -s 'https://api.lever.co/v0/postings/<slug>/<posting-uuid>?mode=json'  # one posting
```

- `categories` carries the employer's own fields: `commitment` (work type),
  `location`, `team` and `allLocations`. A posting with
  `allLocations: ['Global Remote']` and no country list is open to the user.
  Worked case (19/10/2026, job #2064): `Global Remote`, and no time-zone band
  in the text either.
- `descriptionPlain` and `lists` hold the advert text and the requirement
  bullets as clean text, so the must-haves are readable without the page.
- **The board JSON lists sibling roles that the aggregator never carried.** The
  same read on 19/10/2026 surfaced an Engineering Manager posting beside the
  backend one the pool had (job #1138), which is how the better fit was found.
  Read the whole board, not the one posting you came for.
- The apply page is **server-rendered**. One fetch of `<posting-url>/apply` and
  a grep for `name="([^"]+)"` gives the complete control list, including the
  employer's custom questions, before a tab is opened.

## Field inventory (worked example: job #2064, 19/10/2026)

| field | control | value to use |
|---|---|---|
| Resume/CV | `input[type=file][name=resume]` | `artifacts/resume.pdf`; the legend marks the block `✱` |
| Full name | `input[name=name]`, required | profile `name.first` + `name.last` |
| Email | `input[name=email]`, required | profile `email`, matching the attached resume |
| Phone | `input[name=phone]` | the national number |
| Current location | `input#location-input`, required, plus a hidden `selectedLocation` | the employer's own autocomplete; it resolves the place itself |
| Current company | `input[name=org]` | profile `current_employer` |
| LinkedIn URL | `input[name="urls[LinkedIn]"]`, required | profile `linkedin` |
| Twitter, GitHub, Other | `input[name="urls[...]"]` | profile `x`, `github`, `website` |
| Where are you based? | `input[name="cards[<uuid>][field0]"]`, required | city and country, one line |
| Additional Information | `textarea[name="cards[<uuid>][field0]"]` | the employer's own optional prose box |

- The two `cards[...]` controls are the employer's **custom questions**, and
  their UUIDs differ per posting. Enumerate every posting. The card prompts sit
  above each control (`Where are you based?`, `Additional Information` with
  "We are real humans looking at applications").
- `urls[LinkedIn]` has a bracket in the name, so the selector needs quotes:
  `input[name="urls[LinkedIn]"]`.
- The `Additional Information` box is where an employer invites prose. On a
  role whose gate the CV does not carry, this is the place that has to hold the
  evidence, so fill it rather than leaving it blank.

## Traps

- **The resume block auto-reads the attached file.** Its legend reads
  `Couldn't auto-read resume.` / `Analyzing resume...` / `Success!`, so Lever
  parses the upload and can write fields from it. That is the same loss mode as
  Workable's autofill panel: values can change after the resume is attached.
  Read every field back **after** the upload, and put what the form holds into
  the ledger. → `_docs/workable.md`
- **The location field is an autocomplete, not a text box.** `input#location-input`
  resolves the place and writes the hidden `selectedLocation`. Type, wait for
  the list, pick the entry, then read `input#location-input` back.
- **hCaptcha ships on every Lever form** (two `newassets.hcaptcha.com` iframes).
  Never touch it. It is the reason the page is handed over, and the reason a
  part-filled form is worse here than elsewhere.
- **Submit** is `button` with the text `Submit application`. Never click it.
- No self-identification block on the worked form. Check per posting; when one
  is there, answer it from `profile.jsonc` (`self_identification`).

## Human-only

- The hCaptcha, the final review, Submit.
