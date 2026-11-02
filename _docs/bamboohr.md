# BambooHR (bamboohr.com/careers)

Lazy-load this file when a posting lives on a BambooHR careers board:
`https://<company>.bamboohr.com/careers/<job id>`.

## The board is one rendered page

The careers page is client-rendered, so `curl` returns an empty shell and no
list of links. Read the links from the live DOM:

```bash
opencli browser --session <session> eval 'Array.from(document.querySelectorAll("a[href*=\"/careers/\"]")).map(a=>a.getAttribute("href")+" :: "+(a.innerText||"").trim()).join(" | ")'
```

That one line gives every open posting with its id and title, which is the
eligibility and closure check for this ATS.

## A removed posting redirects to the board, not to an error

A posting id that no longer exists answers HTTP 200 at `/careers`, the same URL
as the board itself. So "the URL loads" says nothing: check that the final URL
still carries the id.

Worked case (22/10/2026, job #2771): the portal had been down on 21/10/2026
with a security outage, and the posting text had been recovered from a search
cache. When the portal returned, `curl -L` on `/careers/148` reported
`code=200` with `final=.../careers`, and the board listed only `/careers/146`
and `/careers/147`. The AI Engineer posting was gone, so the row was archived
with `reason_for_archive` and the retry todo closed.

- Confirm closure two ways before you archive: the final URL of the posting
  (it collapses to `/careers`), and the board's own link list (the id is not
  in it).
- A posting id is not stable across a re-post. If the same role comes back
  under a new id, that is a new job row, not a recovery of the old one.
