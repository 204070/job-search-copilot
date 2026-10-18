# Ashby (jobs.ashbyhq.com)

Lazy-load this file when applying through an Ashby posting. Per-posting values
below are EXAMPLES of adapting `artifacts/profile.jsonc` facts to one form —
never canonical; each posting's lists differ.

## Finding the real form

- The job page is `jobs.ashbyhq.com/<org>/<job-uuid>`, with two tabs:
  **Overview** and **Application**. The form lives at
  `jobs.ashbyhq.com/<org>/<job-uuid>/application` — open that directly in the
  session; no iframe hunting needed (validated 18/10/2026).
- The Overview tab is where the employer's machine-readable facts sit:
  `Location`, `Employment Type`, `Location Type`, `Department`.
- `[N]<a id=job-overview …>` / `id=job-application-form …` in `opencli state`
  are the tab controls if a direct open is ever not enough.

## ELIGIBILITY: the structured Location field is authoritative

**Read the Overview tab's `Location` before filling anything.**

- Ashby's `Location` is a structured employer field, not marketing copy, and
  it is what the ATS shows recruiters. Where it disagrees with the posting
  text, the field wins.
- Worked case (18/10/2026): the Toggl Senior Full Stack listing on We Work
  Remotely said "work from anywhere in the world as long as your main location
  is between UTC-4 and UTC+4" (Lagos is UTC+1, so it read as eligible, and the
  scanner tagged it `worldwide` from that sentence). Toggl's own Ashby page
  listed `Serbia; Croatia; France; Poland; Portugal; Spain`. Nigeria is not in
  that list → **not eligible**, caught only because the form was opened. The
  job was archived with `reason_for_archive` in `jobs.metadata`.
- The inverse also holds: Supabase's `Location` read `Remote, Global`, which
  matches its "We hire globally" copy → apply.
- Rule of thumb: an aggregator's (WWR, Real Work From Anywhere, RemoteOK,
  Jobicy) location text is a HINT; the employer's Ashby/Greenhouse field is the
  fact. Never fill six fields before checking the one that decides it.

## Field inventory (worked example: Supabase, job #539, 18/10/2026)

An optional **"Autofill from resume"** panel sits above the form (its own file
input + `Upload file` button) and can populate the system fields.

| field | control | value used |
|---|---|---|
| Name | `#_systemfield_name` text | profile `name` |
| Email | `#_systemfield_email` email | profile `email` |
| Resume | `#_systemfield_resume` file | `artifacts/resume.pdf` |
| Passport Country | text | profile `location.country` |
| Country of Residence | text | profile `location.country` |
| Are you over the age of 18? | Yes / No buttons | Yes |
| Experience with most relevant tech | textarea | resume-grounded, see below |
| Github Profile | text | repo `github.com/204070` |
| Open source contributions | textarea | truthful: own public repos |
| Linkedin | text | profile `linkedin` |
| Where did you hear about this vacancy? | radio set | `Other online job boards` (came via Real Work From Anywhere) |
| Referrer name (if relevant) | text | blank |

- No compensation, sponsorship, notice-period or start-date questions on this
  one. Do not import US-specific answers (`us_sponsorship_required`,
  green-card acknowledgement) into a globally-hired EU-adjacent employer.
- Plain `input type=text` / `textarea`, placeholder `Type here...`. No
  react-select comboboxes, so the Greenhouse combobox recipe does not apply
  here. Buttons, not a checkbox, for Yes/No.
- `<input type=file>` for the resume: if `opencli upload` fails as it does on
  Greenhouse (styled input swallowing the click), reuse the base64/DataTransfer
  recipe in `_docs/greenhouse.md` → `artifacts/scripts/embed_resume.sh`.

## Free-text answers

- Answer from `artifacts/resume.pdf` facts and the user's real public repos.
  Ashby custom questions are read by engineers, so name concrete systems, not
  adjectives.
- The tech textarea here asked specifically about **Go, Typescript, Databases,
  IaC** — address each of the four in order and lead with the strongest.
- **The resume is a floor, not a ceiling. Ask the person for their real tech
  surface before writing this one.** Drafting from `resume.pdf` alone once
  undersold badly: the resume omits Cassandra, ClickHouse,
  Heroku/Vercel/Netlify/Cloudflare, bare-metal deployments with
  Dokploy/Coolify/Kamal, and most of the AWS/Azure/GCP surface. The candidate
  knows what they have done; the resume does not.
- **Go: keep it deliberately general.** Side projects and exploration
  (microservices, observability tooling), not enterprise production. Do not
  write a list of concurrency primitives as though they were production
  experience; say TypeScript is the strongest language and that Go is welcome.
- Open source: check `https://api.github.com/users/<handle>/repos` before
  answering. Point at real public repos; a fork is not a contribution. Do not
  offer a small public repo as evidence of infrastructure depth — say what it
  actually is (e.g. a small Pulumi example) and let it stand only where the
  tooling itself is the point.
- Field ids change per page load (see `_docs/tooling.md`): prefer stable suffix
  selectors such as `label[for$="-labeled-radio-5"]`.

## Session fragility

The tab can come back as `about:blank` between turns, and Ashby keeps no
server-side draft, so a lost tab loses the entire fill. Fill in one pass, then
hand over for immediate review and submission. Re-read `tab list` before
resuming. Details and guards: `_docs/tooling.md`.

## Human-only

- Final review, Submit. Never click Submit.
