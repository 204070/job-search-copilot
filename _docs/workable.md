# Workable (apply.workable.com)

Lazy-load this file when applying through a Workable posting. Per-posting
values below are EXAMPLES of adapting `artifacts/profile.jsonc` facts to one
form, never canonical.

## Finding the form

- The employer's careers page links to `apply.workable.com/j/<shortcode>`, which
  resolves to `apply.workable.com/<slug>/j/<shortcode>`. The posting is one page
  with an **Overview** and an **Application** tab; the form sits at
  `.../<shortcode>/apply/`, and the tab control is enough to reach it.
- The posting header carries the employer's own three facts in one line:
  the work type (`Remote`), the department, then the location. Read them before
  filling. The employer's board index at `apply.workable.com/<slug>` lists every
  open posting with the same three facts, so one page screens the whole company.
- The location line names the employer's base, not the people who may apply. In
  the worked case (19/10/2026, job #2063) the header read `Remote` beside the
  studio's base country while the ad said "100% remote, global team". The base
  country is not a residence bar, and the absence of a listed country list means
  nothing closes the role. Check the ad's own eligibility sentence, then apply.

## Field inventory (worked example: job #2063, 19/10/2026)

An optional **Autofill application** panel sits at the top with an
`Import resume from` button. The form does not need it. It is not inert,
though: run against the resume it fills the optional blocks itself (headline,
summary, education, experience), so a form handed over with those blank can be
submitted with text the agent never wrote. Either fill them from the resume, or
read them back before hand-over, and put what they hold into the ledger. Worked
case: application #10, 19/10/2026.

| field | control | value used |
|---|---|---|
| First name | `input[name=firstname]` | profile `name.first` |
| Last name | `input[name=lastname]` | profile `name.last` |
| Email | `input[name=email]` | profile `email`, matching the attached resume |
| Headline | `input[name=headline]` | left blank, as with the cover letter |
| Phone | `input[name=phone]` plus a dial-code select | the national number only; the select already stood at the applicant's dial code (`profile.jsonc` `phone.dial_code`) and formatted the value with spaces |
| Address | `input#address` (`data-ui="address"`) | city and country, one line |
| City, postcode, country | plain text | filled, then cleared by the address widget; harmless, they are optional |
| Photo | optional `input[type=file]`, `accept` images | left empty |
| Education, Experience | `+ Add` repeaters | left empty |
| Summary | `textarea[name=summary]` | left blank |
| Resume | the **required** `input[type=file]` | the profile's `resumes.canonical_pdf`, as it is |
| Cover letter | `textarea[name=cover_letter]` | left blank, as on every application so far |
| Salary ($, Gross) | `input[name=QA_<n>]`, required | the top of the `compensation` default |
| English level | radio group, `QA_<n>`, required | `languages.english` from the profile |
| How did you learn about us? | checkbox group, numeric names | `Other`, plus the specify field |
| If other, please specify | `QA_<n>`, required | the job board that actually surfaced the posting |

## Traps

- **A numeric `name` needs a quoted selector.** The hear-about checkboxes are
  named `6370558` and up, so `input[name=6370564]` throws
  `not a valid selector` and kills the whole eval, including the fields already
  set in it. Write `input[name="6370564"]`, and put every fill in one eval only
  after checking the selectors run.
- **The pay field takes one number and reformats as it goes.** Setting
  A range produced one huge number, because the dash is dropped and the digits
  are grouped. A single number is the only valid input. The figure is the
  user's, so the top of the `compensation` default is what goes in, and the
  handover names it.
- **The Address field resolves the place itself.** It is Workable's own widget
  (`id=address`, `data-ui="address"`), and setting it twice in one session
  duplicated the string into `<city>, <country>, <city>, <country>`. Set it
  once, last, then read it back. It survives a blur when it is set once.
- **Group questions hide their legend.** The field list reads `A1 A2 B1 B2 C1
  C2` with no question above it; the legend one level up says
  `* English level`. The checkbox group's legend is `* How did you learn about
  us?`, and its options are partly regional boards. Walk up the parents for the
  legend before you answer.
- **Two file inputs exist.** The first accepts images and is optional (the
  photo); the second is required and accepts pdf/doc/docx (the resume).
  `[...document.querySelectorAll("input[type=file]")].find(el => el.required)`
  picks the right one without depending on the random `input_files_input_<id>`
  names.
- The base64/DataTransfer recipe uploads fine here. Read the size back: the
  byte count matched the file on disk (`resumes.canonical_pdf`), and the zone
  then showed the filename with a `Replace file` link.
- **No third-party captcha and no self-identification block** on this form, so
  the standing `self_identification` answers do not come up. Say so at handover
  rather than implying they were answered.
- The cookies banner sits at the bottom and needs no action. Do not click it on
  the user's behalf.

## Human-only

- Final review, Submit. Never click Submit.
