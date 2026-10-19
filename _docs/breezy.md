# Breezy HR (breezy.hr)

Lazy-load this file when a posting lives on a Breezy board.

## The board answers eligibility as JSON

`https://<board>.breezy.hr/json` returns every open posting with the employer's
own structured fields. No page render, no browser session, one request:

| field | what it settles |
|---|---|
| `location.is_remote` | whether the role is offered away from the office at all |
| `location.remote_details.value` | `remote`, or `hybrid` when part of the week is on site |
| `location.remote_details.label` | the same fact in the board's own language |
| `location.streetAddress.custom` | the office the person would attend |
| `location.city` / `location.country` | the base |
| `type` | full time or contract |

- **Read `remote_details` before anything else.** `is_remote: true` alone reads
  as "remote"; with `remote_details.value = hybrid` it means part of the week is
  on site, and the street address says where. That combination is a real bar for
  someone who lives in another country, and it is the employer's own field, not
  an aggregator's label.
- The posting page's raw HTML does not resolve this. It renders template
  placeholders such as `%LABEL_POSITION_TYPE_REMOTE_HYBRID%` instead of the
  value (seen 19/10/2026), so the page text reads `Remote/Hybrid` at best. Use
  the board JSON.
- Worked case (19/10/2026, job #1236): the ad was a strong must-have match
  (senior backend, people management, the candidate's stack) and the aggregator
  recorded `Hybrid` with the base country. The board JSON showed
  `is_remote: true` with `remote_details.value = hybrid` and a named office, so
  the role needs weekly presence in a city the candidate does not live in. Out
  on location, and the row carries that as `reason_for_archive`.
- The inverse also holds: `remote_details.value = remote` with no street address
  is a role that can be taken from here, whatever the base country says.
