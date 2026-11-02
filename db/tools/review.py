"""Review digest: the decisions waiting on a human, in one page.

The scanner writes leads, the application runbook files applications, and the
question bank accumulates answers. None of that tells you what needs a decision
this week. This tool reads the database and produces that page:

    python3 -m db.tools.review                    # rewrite artifacts/review.md
    python3 -m db.tools.review follow-up --app 3 --in-days 7
    python3 -m db.tools.review resolve --event 4
    python3 -m db.tools.review dismiss --job 616 --reason "posting closed"
    python3 -m db.tools.review todo --add "create the resume variant"

One living file, rewritten in place, not a dated log. There is nothing to
accumulate: the digest holds no state, and a stale item leaves the page by
being resolved in the database (a follow-up closed, a lead archived, an answer
retired), not by being edited out of the text. Hand edits would be lost on
the next rewrite, which is why every actionable line carries the command that
closes it. The database is the memory; this page is a view.

Almost everything the page asks for is derived from a row, so it cannot drift.
One thing is not: an action with no job, application or question behind it
("create the resume variant") has nothing to be derived from, and would live in
a chat scrollback without a home. That is what `todos` is for. A todo renders
in section 2 with the command that closes it and disappears when that runs, so
the no-state rule survives: the row is the state, the page is still a view.

The file is private (gitignored, via `artifacts/`): it names employers, and
this repo is public.

Sections are ordered by what is most likely to be expensive to miss:

1. Since you last looked   what changed since the previous rewrite
2. Needs you now           your own open actions, follow-ups due, unsent forms
3. Applications            every application with its age and next action
4. Next roles              bookmarked postings, best-ranked first
5. Pipeline health         counts that say whether the ranking can be trusted
6. Question bank           what the bank knows, and what changed since it went out

Section 1 is the one that makes reading this "from time to time" cheap: it is
computed against the `Refreshed:` line this file carried last time, so it needs
no extra bookkeeping and cannot drift.

The follow-up reminder is a derivation, not a timer: with no employer-contact
event on record (`SIGNAL_EVENT_TYPES`), the digest compares
`applications.applied_at` with today and, once `FOLLOW_UP_AFTER_DAYS` days have
passed, changes that application's next action from waiting to suggesting a
follow-up. Scheduling one is an explicit command, so the signal stays yours.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from db.connection import connect

#: Days between `applications.applied_at` and the digest suggesting a follow-up,
#: when no employer-contact event is on record.
FOLLOW_UP_AFTER_DAYS = 7

#: The one living digest file (gitignored, via the `artifacts/` rule).
DEFAULT_OUT = Path("artifacts/review.md")

#: The line the next run reads to know when this file was last refreshed.
REFRESHED_RE = re.compile(r"^Refreshed: (?P<stamp>\S+)", re.M)

#: Sort key for where a posting hires, used only when the classifier cannot be
#: imported: `unknown` stays visible on purpose, `us_only` sinks.
_FALLBACK_SCOPE_RANK = {"worldwide": 0, "unknown": 1, "region_gated": 2,
                        "us_only": 3}

#: Fallback for "this title reads like one of our roles", used only when the
#: scanner's own gate cannot be loaded. The real answer comes from
#: `Matcher.admits()`, so the report and the scorer cannot disagree.
ENGINEERING_TITLE = re.compile(
    r"(?i)\b(engineer|developer|programmer|sre|devops|architect)\b")

#: Stand-in for a row with no usable timestamp at all, so it sorts last.
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)

#: Statuses that mean the application is over.
CLOSED_STATUSES = ("rejected", "withdrawn", "archived")

#: Event types that mean the OTHER side made contact. These, and only these,
#: clear the follow-up reminder (see `follow_up_action`). A `note` is our own
#: bookkeeping ("recon done", "form filled in one pass") and a `follow_up` is
#: our own follow-up action, so neither belongs here: letting them count cleared
#: the
#: reminder on exactly the applications that were documented well enough to have
#: notes, which is how a freshly submitted one came to read "no action (a reply
#: is on record)" with nobody having replied. Contact that moves no status goes
#: in as a `reply` (`review reply`). Kept as one list so the SQL and the docs
#: cannot disagree about what contact is.
SIGNAL_EVENT_TYPES = ("interview", "offer", "rejection", "reply")
_SIGNAL_IN = ", ".join(f"'{event_type}'" for event_type in SIGNAL_EVENT_TYPES)

#: Below this score a posting is only listed when its title plainly names one of
#: our roles. Matches the scanner's own MATCH_MIN_SCORE default; a literal
#: rather than a read, because this module only needs the scanner's gate
#: (`_matcher`) and must still render when that import fails.
RELEVANT_FLOOR = 15

#: How many postings one employer may contribute to the shortlist.
MAX_PER_EMPLOYER = 2

#: After this many applications to one employer inside `COOLDOWN_DAYS`, the
#: rest of that employer's board leaves the shortlist until the window clears.
#: Two applications already say "I want to work here"; a third inside a week
#: reads as spraying, and a fresh requisition is worth more to them than our
#: impatience. Derived from `applications` on every rewrite, so nothing has to
#: be set, and nothing has to be cleared afterwards.
MAX_APPS_PER_EMPLOYER = 2
COOLDOWN_DAYS = 7

#: How far back an application still colours the shortlist. The cooldown above
#: hides the rest of an employer's board for a week; this is the longer memory,
#: so an employer we have already written to twice does not lead the page a
#: month later while nothing has come back.
APPLICATION_MEMORY_DAYS = 90

#: Points taken off every posting from an employer for each application still
#: inside `APPLICATION_MEMORY_DAYS`. Two applications to one employer should
#: read as interest already expressed, not as a reason to send a third.
APPLICATION_WEIGHT = -15

#: Extra points off an employer that has already rejected an application inside
#: the memory window. A rejection is the clearest evidence on file that another
#: posting from them is not the best use of an hour.
REJECTION_WEIGHT = -20

#: A posting older than this is not a live lead. Boards keep perpetual
#: requisitions up for a year, and a posting from last December cannot be worth
#: an hour today, so it leaves the shortlist even while the board still lists
#: it. It stays in the pool and in the blind-spot table, so nothing is lost.
STALE_DAYS = 45

#: How many postings the shortlist shows.
NEXT_ROLE_LIMIT = 12


# --- pure helpers (self-tested) --------------------------------------------


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 UTC timestamp, tolerating a trailing Z. None if blank."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def days_since(value: str | None, today: date) -> int | None:
    """Whole days from an ISO timestamp to `today`; None when unparseable."""
    moment = parse_iso(value)
    return None if moment is None else (today - moment.date()).days


def employer_cooldown(
    applied: list[tuple[str | None, int | None]],
    max_apps: int = MAX_APPS_PER_EMPLOYER,
    days: int = COOLDOWN_DAYS,
) -> dict[str, tuple[int, int]]:
    """Employers to leave alone for now, and for how much longer.

    `applied` is one `(employer, whole days since it went out)` pair per
    application; `None` days means we never sent it, so it does not count as
    saying anything. An employer with `max_apps` or more inside `days` cools
    down, and the window clears one week after the most recent of them, so the
    answer is `{employer: (applications inside the window, days left)}`.

    Derived on every call: the cooldown asks for no stored flag, which is why
    it cannot go stale, and lifting it needs no cleanup.
    """
    recent: dict[str, list[int]] = {}
    for employer, age in applied:
        if not employer or age is None or age >= days:
            continue
        recent.setdefault(employer, []).append(age)
    return {employer: (len(ages), days - min(ages))
            for employer, ages in recent.items() if len(ages) >= max_apps}


def employer_key(company: str | None) -> str:
    """The stable key for one employer: lowercased, trimmed, spaces collapsed."""
    return " ".join((company or "").lower().split())


def employer_adjustment(
    applications: int,
    manual_weight: int = 0,
    rejections: int = 0,
    per_application: int = APPLICATION_WEIGHT,
    per_rejection: int = REJECTION_WEIGHT,
) -> int:
    """The score change for an employer, from how often we have written to them.

    `applications` counts the ones sent inside `APPLICATION_MEMORY_DAYS`, and
    `manual_weight` is the named number in `employer_weights`. The default is
    negative on purpose: the point is to surface an employer we have not tried
    above one we have, not to hide the posting.
    """
    return (manual_weight + per_application * max(applications, 0)
            + per_rejection * max(rejections, 0))


def next_role_order(
    rank: int,
    adjusted: int,
    score: int,
    onsite_elsewhere: bool = False,
) -> tuple[int, int, int, int, int]:
    """Sort key for the shortlist: roles we can take first, then adjusted score.

    `rank` is `_scope_rank`, where 0 to 2 are roles we can take (worldwide, a
    region that names ours, or silence) and 3 to 4 are a named list that
    excludes us or a US work bar. Grouping the first three means a Lagos or
    unknown-scope posting at 96 is no longer buried under a worldwide posting at
    38, while a US-only posting still cannot jump the queue on score alone.
    """
    return (0 if rank <= 2 else 1, 1 if onsite_elsewhere else 0,
            -adjusted, rank, -score)


#: Words in a location field that describe a scope rather than one office, so a
#: posting that carries one is not read as a relocation role.
_SCOPE_WORDS = ("remote", "anywhere", "worldwide", "global", "emea", "mea",
                "africa", "europe", "apac", "amer", "latam", "nigeria", "lagos")


def is_relocation_role(workplace_type: str | None, location: str | None) -> bool:
    """Whether the posting is a relocation role rather than a remote one.

    An office or hybrid posting in another country is not a bar on eligibility,
    but it is not the remote work being searched for either, so it sinks below
    every remote posting. A posting in the user's own country is local work and
    stays in the main group. A workplace type of `unknown` beside a named
    foreign place counts too: an empty type is silence, a city is an office.
    """
    place = (location or "").lower()
    local = "nigeria" in place or "lagos" in place
    kind = (workplace_type or "").lower()
    if kind == "remote":
        return False
    if kind in ("onsite", "hybrid"):
        return not local
    if not place or local:
        return False
    return not any(word in place for word in _SCOPE_WORDS)


def follow_up_action(
    status: str,
    applied_days: int | None,
    has_signal: bool,
    due_on: str | None,
    today: str,
    followed_up_days: int | None = None,
) -> str:
    """What (if anything) this application needs, as a short phrase.

    `due_on` is an explicit scheduled follow-up date, and it outranks the day
    count, because a scheduled date is a decision already made. `followed_up_days`
    is how long ago our own last follow-up went out; inside the waiting window it
    silences the "consider a follow-up" prompt, because the note is already sent
    and asking again would send a second one.
    """
    if status == "ready_to_apply":
        return "submit it"
    if status in ("screening", "interviewing", "offer"):
        return f"active, keep it warm ({status})"
    if status in CLOSED_STATUSES:
        return "closed"
    if status != "applied":
        return f"no action ({status})"
    if due_on:
        return (f"follow up now (was due {due_on})" if due_on <= today
                else f"follow up on {due_on}")
    if has_signal:
        return "no action (a reply is on record)"
    if followed_up_days is not None and followed_up_days < FOLLOW_UP_AFTER_DAYS:
        return f"followed up {followed_up_days}d ago; nudge after day {FOLLOW_UP_AFTER_DAYS}"
    if applied_days is None:
        return "no action (no submission date)"
    if applied_days >= FOLLOW_UP_AFTER_DAYS:
        return f"consider a follow-up (out {applied_days} days)"
    return f"nothing yet (follow up on day {FOLLOW_UP_AFTER_DAYS})"


# --- queries ----------------------------------------------------------------


APPLICATION_SQL = f"""
SELECT a.id AS app_id, a.job_id, a.status AS app_status, a.applied_at,
       a.method, a.resume_variant, a.updated_at,
       j.title, j.company, j.region_scope, j.url, j.status AS job_status,
       (SELECT MAX(e.occurred_at) FROM application_events e
         WHERE e.application_id = a.id
           AND e.event_type IN ({_SIGNAL_IN})) AS last_signal,
       (SELECT MIN(e.scheduled_for) FROM application_events e
         WHERE e.application_id = a.id AND e.event_type = 'follow_up'
           AND e.scheduled_for IS NOT NULL
           AND json_extract(e.metadata, '$.done') IS NULL) AS due_follow_up,
       (SELECT MAX(COALESCE(json_extract(e.metadata, '$.done_at'), e.occurred_at))
          FROM application_events e
         WHERE e.application_id = a.id AND e.event_type = 'follow_up'
           AND (e.scheduled_for IS NULL
                OR json_extract(e.metadata, '$.done') = 1)) AS last_follow_up,
       (SELECT COUNT(*) FROM application_events e
         WHERE e.application_id = a.id) AS n_events
  FROM applications a
  JOIN jobs j ON j.id = a.job_id
 ORDER BY CASE a.status
            WHEN 'offer' THEN 0 WHEN 'interviewing' THEN 1 WHEN 'screening' THEN 2
            WHEN 'ready_to_apply' THEN 3 WHEN 'applied' THEN 4 ELSE 5 END,
          a.id
"""


def _applications(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every application with the fields the digest renders."""
    return conn.execute(APPLICATION_SQL).fetchall()


def _count(conn: sqlite3.Connection, sql: str) -> int:
    return conn.execute(sql).fetchone()[0]


def _employer_weights(conn: sqlite3.Connection) -> dict[str, tuple[int, str]]:
    """The named weights, keyed by `employer_key`, as `{key: (weight, reason)}`.

    A database that has not run migration 0007 yet still renders the digest, so
    a missing table reads as "no named weights" rather than an error.
    """
    try:
        rows = conn.execute(
            "SELECT company_key, weight, reason FROM employer_weights").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row["company_key"]: (row["weight"], row["reason"]) for row in rows}


def _skipped_countries(conn: sqlite3.Connection) -> dict[str, dict]:
    """The countries the user does not apply to, keyed by country.

    Each value is `{"terms": [...], "text_terms": [...], "reason": str}`, where
    the terms are compiled regular expressions. `terms` reads the location
    fields; `text_terms` reads the ad text and holds only phrasings that declare
    where the work sits, because a description names offices and customers too.

    A database that has not run migration 0008 yet still renders the digest, so
    a missing table reads as "no skipped countries" rather than an error. A row
    whose terms parse to nothing is ignored rather than allowed to match
    everything.
    """
    try:
        rows = conn.execute(
            "SELECT country_key, terms, reason,"
            "       coalesce(terms_in_text, '[]') AS terms_in_text"
            " FROM skipped_countries").fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        patterns, text_patterns = [], []
        for column, target in (("terms", patterns),
                               ("terms_in_text", text_patterns)):
            try:
                raw = json.loads(row[column] or "[]")
            except ValueError:
                continue
            target += [re.compile(t, re.I) for t in raw
                       if isinstance(t, str) and t]
        if patterns or text_patterns:
            out[row["country_key"]] = {"terms": patterns,
                                       "text_terms": text_patterns,
                                       "reason": row["reason"]}
    return out


def _skipped_country_of(row, skipped: dict[str, dict]) -> str | None:
    """The first skipped-country key this posting matches, or None.

    `location` and `region_evidence` are read first: they are where a board puts
    the country, and a place name there almost always means the job sits there.
    Only when both are empty is the ad text read, and only with the tighter
    phrasings, because a description names a company's offices and customers.
    """
    if not skipped:
        return None
    hay = " ".join(str(row[k] or "") for k in ("location", "region_evidence"))
    if hay.strip():
        for key, spec in skipped.items():
            if any(p.search(hay) for p in spec["terms"]):
                return key
        return None
    text = row["raw_text"] if "raw_text" in row.keys() else ""
    if not text:
        return None
    for key, spec in skipped.items():
        if any(p.search(text) for p in spec["text_terms"]):
            return key
    return None


def _matcher():
    """The scanner's title gate, or None when the scanner cannot be loaded.

    This report used to carry its own copy of "what looks like a role" as a
    regex, and the copy drifted from the scorer: it kept calling titles target
    roles long after the gate had changed its mind. Reading the gate out of
    the scoring config is the only way the two stay in step, so the scanner is
    imported here, lazily and optionally, and the digest still renders if the
    import or the config is broken.
    """
    try:
        from scanner.keywords import Matcher
        return Matcher()
    except (ImportError, OSError, ValueError):
        return None


def _is_stale(row: dict, today: date, days: int = STALE_DAYS) -> bool:
    """Whether the posting date is older than the shortlist will show."""
    moment = _posted(row)
    return moment > _EPOCH and (today - moment.date()).days > days


def _admits(matcher, title: str | None) -> bool:
    """Whether the scoring gate admits this title (regex fallback if no gate)."""
    if matcher is not None:
        return matcher.admits(title)
    return bool(ENGINEERING_TITLE.search(title or ""))


def _scope_rank(scope: str | None, evidence: str | None = None) -> int:
    """Triage order for where a posting hires, from the classifier itself.

    The vocabulary that decides whether a named region includes us lives in
    `scanner.eligibility`, next to the regex that produced the tag, so the
    report and the scanner cannot disagree about it; the local dict is only a
    fallback for when that module cannot be imported.
    """
    try:
        from scanner.eligibility import scope_rank
    except (ImportError, OSError, ValueError):
        return _FALLBACK_SCOPE_RANK.get(scope, 4)
    return scope_rank(scope, evidence)


def _posted(row: sqlite3.Row) -> datetime:
    """When the posting entered the pool: posted date, else when we saved it.

    Feed timestamps arrive in two shapes ("...Z" and "...+00:00"), so they are
    parsed rather than compared as strings, and a naive one is read as UTC so
    mixed rows stay comparable.
    """
    for field in ("posted_at", "bookmarked_at", "created_at"):
        moment = parse_iso(row[field])
        if moment is not None:
            return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return _EPOCH


def _blind_spot(conn: sqlite3.Connection, exclude_ids: set[int] | None = None,
                limit: int = 12) -> tuple[int, int, list]:
    """Bookmarked postings the gate admits whose stored text matches nothing.

    Returns (total, how many have no stored text at all, samples). Since the
    gate stopped being a fixed list of nine phrasings, this is no longer a hole
    in the scorer: it is the honest remainder, either a row whose feed carried
    no description, or an advert that names none of the stack. Both need a
    human eye rather than a better keyword list, so the samples are the newest
    first: a score of 0 carries no ordering information, but recency does, and
    a closing date rides on a new posting rather than an old one.

    A posting that already has an application is not a next role, so it is
    left out here the same way the table above leaves it out.
    """
    rows = conn.execute(
        "SELECT id, title, company, region_scope, match_score, url, posted_at,"
        " bookmarked_at, created_at,"
        " length(coalesce(raw_text, '')) AS textlen FROM jobs"
        " WHERE status = 'bookmarked' AND coalesce(match_score, 0) = 0"
        "   AND id NOT IN (SELECT job_id FROM applications)"
    ).fetchall()
    matcher = _matcher()
    skip = exclude_ids or set()
    hits = [r for r in rows
            if r["id"] not in skip and _admits(matcher, r["title"])]
    hits.sort(key=lambda r: (_posted(r), r["id"]), reverse=True)
    return len(hits), sum(1 for r in hits if not r["textlen"]), hits[:limit]


def _unpushed_commits() -> int | None:
    """Commits on HEAD that are not on origin/main, or None if unknowable."""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return int(result.stdout.strip()) if result.returncode == 0 else None


# --- rendering --------------------------------------------------------------


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    """A markdown table, tolerating an empty row list."""
    if not rows:
        return ["(nothing here)"]
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out


def todo_owner_label(owner: str | None) -> str:
    """Who acts on a todo, in the words the digest uses.

    Anything that is not the user's own is the agent's: an unrecognised owner
    is a row to fix, and defaulting it to work the agent will notice is safer
    than defaulting it to work the user may not.
    """
    return "Yours to do" if owner == "user" else "Agent to do"


def section_since(conn: sqlite3.Connection, since: str | None,
                  limit: int = 8) -> list[str]:
    """Section 1: what changed since the previous rewrite.

    Everything here comes from timestamps the database already keeps (row
    creation and update times, the application event ledger), so this section
    needs no bookkeeping of its own and cannot drift from the sections below.
    It is what makes reading the page "from time to time" cheap: the standing
    picture barely moves, the delta is where the decisions are.
    """
    out = ["## 1. Since you last looked", ""]
    if not since:
        out += ["(first rewrite in this format, so there is nothing earlier to "
                "compare against)", ""]
        return out
    stamp = since.replace("T", " ").replace("Z", " UTC")

    new_leads = conn.execute(
        "SELECT id, title, company, region_scope, match_score FROM jobs"
        " WHERE status = 'bookmarked' AND coalesce(match_score, 0) >= ?"
        "   AND coalesce(bookmarked_at, created_at) > ?"
        "   AND id NOT IN (SELECT job_id FROM applications)"
        " ORDER BY match_score DESC, id LIMIT ?",
        (RELEVANT_FLOOR, since, limit),
    ).fetchall()
    events = conn.execute(
        "SELECT e.application_id, e.event_type, e.from_status, e.to_status,"
        "       e.summary, e.occurred_at, j.company, j.title"
        "  FROM application_events e"
        "  JOIN applications a ON a.id = e.application_id"
        "  JOIN jobs j ON j.id = a.job_id"
        " WHERE e.occurred_at > ? ORDER BY e.occurred_at",
        (since,),
    ).fetchall()
    left_pool = conn.execute(
        "SELECT id, title, company, status FROM jobs"
        " WHERE status <> 'bookmarked' AND updated_at > ?"
        "   AND id NOT IN (SELECT job_id FROM applications)"
        " ORDER BY updated_at LIMIT ?",
        (since, limit),
    ).fetchall()

    if not (new_leads or events or left_pool):
        out += [f"(nothing changed since {stamp})", ""]
        return out

    out += [f"Compared against {stamp}. The sections below are the standing "
            "picture, not the change.", ""]
    if new_leads:
        out += _table(["job", "role", "employer", "scope", "score"],
                      [[f"#{r['id']}", (r['title'] or '')[:42], r['company'],
                        r['region_scope'], r['match_score']] for r in new_leads])
        out.append("")
    for e in events:
        note = f": {e['summary']}" if e["summary"] else ""
        # Show the status move when there is one, and the event's own name when
        # there is not, so a note never reads as a status change.
        if e["event_type"] == "note":
            move = "note"
        elif e["from_status"] and e["from_status"] != e["to_status"]:
            move = f"{e['from_status']} -> {e['to_status']}"
        else:
            move = e["to_status"] or e["event_type"]
        out.append(f"- **Application #{e['application_id']}** ({e['company']}): "
                   f"{move}{note}")
    for r in left_pool:
        out.append(f"- **Left the pool**: {r['company']} - {r['title']} "
                   f"(`{r['status']}`)")
    out.append("")
    return out


def section_needs_you(conn, apps, today: date) -> list[str]:
    """Section 2: anything with a date attached or a decision outstanding."""
    out = ["## 2. Needs you now", ""]
    items: list[str] = []

    # The one item here that is not derived from a row elsewhere: an action with
    # no job, application or question behind it. It has nowhere else to appear,
    # so it leads, and it leaves when the closing command records a close.
    for row in conn.execute(
            "SELECT id, text, owner, created_at, context FROM open_todos"):
        added = (row["created_at"] or "")[:10]
        when = f" (added {added})" if added else ""
        why = f" {row['context']}" if row["context"] else ""
        items.append(
            f"- [ ] **{todo_owner_label(row['owner'])}**: {row['text']}{when}."
            f"{why} `python3 -m db.tools.review todo --close {row['id']}` once done.")

    for row in apps:
        status = row["app_status"]
        due = row["due_follow_up"]
        if due and due[:10] <= today.isoformat():
            items.append(
                f"- [ ] **Follow-up due**: application #{row['app_id']} "
                f"({row['company']}): {row['title']}. Scheduled for {due[:10]}. "
                f"`python3 -m db.tools.review resolve --event <id>` once done.")
        if status == "ready_to_apply":
            items.append(
                f"- [ ] **Not submitted**: application #{row['app_id']} "
                f"({row['company']}): {row['title']}. Materials are prepared.")
        elif status == "applied":
            days = days_since(row["applied_at"], today)
            followed = days_since(row["last_follow_up"], today)
            if (days is not None and days >= FOLLOW_UP_AFTER_DAYS
                    and not row["last_signal"] and not due
                    and not (followed is not None
                             and followed < FOLLOW_UP_AFTER_DAYS)):
                items.append(
                    f"- [ ] **Consider a follow-up**: application #{row['app_id']} "
                    f"({row['company']}) is {days} days out with no employer "
                    f"contact on record. Schedule it with "
                    f"`python3 -m db.tools.review follow-up --app {row['app_id']} --in-days 1`.")

    # A `revised` bank answer is deliberately NOT a task here. Wording is
    # chosen per application, so the stored text differing from what one
    # employer received is the normal state of the bank, not a decision
    # outstanding. What carries forward is the reasoning, which `lookup` prints
    # beside the sent text; section 6 reports the count and says so.
    out += items or ["(nothing needs a decision today)"]
    out.append("")
    return out


def section_applications(apps, today: date) -> list[str]:
    """Section 3: every application, oldest decision first."""
    out = ["## 3. Applications", "",
           "`age` is days since `applications.applied_at`; `last signal` is the "
           "most recent contact FROM the employer (an interview, an offer, a "
           "rejection, or a reply that moves no status). Our own notes and the "
           "submission itself are not contact, so they never clear the reminder: "
           f"at {FOLLOW_UP_AFTER_DAYS} days with none, the next action changes "
           "from waiting to suggesting a follow-up. Our own follow-up is not "
           "contact either, but a sent one quiets the suggestion until the same "
           "window passes again.", ""]
    rows = []
    for row in apps:
        age = days_since(row["applied_at"], today)
        rows.append([
            f"#{row['app_id']}",
            row["company"],
            (row["title"] or "")[:44],
            row["app_status"],
            f"{age}d" if age is not None else "-",
            (row["last_signal"] or "-")[:10],
            follow_up_action(row["app_status"], age, bool(row["last_signal"]),
                             row["due_follow_up"], today.isoformat(),
                             days_since(row["last_follow_up"], today)),
        ])
    out += _table(["app", "employer", "role", "status", "age", "last signal",
                   "next action"], rows)
    out.append("")
    return out


def section_next_roles(conn, today: date) -> list[str]:
    """Section 4: bookmarked postings worth a look, and what the gate leaves out."""
    out = ["## 4. Next roles", ""]
    ranked = [dict(r) for r in conn.execute(
        "SELECT id, title, company, region_scope, region_evidence, match_score,"
        "       location, workplace_type, posted_at, bookmarked_at, created_at,"
        "       raw_text"
        " FROM jobs WHERE status = 'bookmarked'"
        "   AND id NOT IN (SELECT job_id FROM applications)").fetchall()]
    matcher = _matcher()
    # Employers we have already applied to twice inside the cooldown window. The
    # rule lives in `employer_cooldown`, so it is one definition, tested once.
    sent = [(r["company"], days_since(r["applied_at"], today))
            for r in conn.execute(
                "SELECT j.company AS company, a.applied_at AS applied_at"
                " FROM applications a JOIN jobs j ON j.id = a.job_id"
                " WHERE a.applied_at IS NOT NULL"
                "   AND a.status NOT IN ('withdrawn', 'archived')").fetchall()]
    cooling = employer_cooldown(sent)
    # How often we have already written to each employer inside the memory
    # window, and the named weights. Both are derived or stored data, so the
    # order changes without a code edit.
    written: dict[str, int] = {}
    for row in conn.execute(
            "SELECT j.company AS company, a.applied_at AS applied_at"
            " FROM applications a JOIN jobs j ON j.id = a.job_id"
            " WHERE a.applied_at IS NOT NULL AND a.status != 'withdrawn'").fetchall():
        age = days_since(row["applied_at"], today)
        if age is not None and age <= APPLICATION_MEMORY_DAYS:
            key = employer_key(row["company"])
            written[key] = written.get(key, 0) + 1
    rejected: dict[str, int] = {}
    for row in conn.execute(
            "SELECT j.company AS company, a.applied_at AS applied_at"
            " FROM applications a JOIN jobs j ON j.id = a.job_id"
            " WHERE a.applied_at IS NOT NULL AND a.status = 'rejected'").fetchall():
        age = days_since(row["applied_at"], today)
        if age is not None and age <= APPLICATION_MEMORY_DAYS:
            key = employer_key(row["company"])
            rejected[key] = rejected.get(key, 0) + 1
    manual = _employer_weights(conn)
    # Countries the user does not apply to. They leave the shortlist without
    # leaving the pool, so deleting one row brings the postings back.
    skipped = _skipped_countries(conn)
    skipped_hits: dict[str, int] = {}
    skipped_ids: set[int] = set()
    for row in ranked:
        key = employer_key(row["company"])
        row["adjust"] = employer_adjustment(written.get(key, 0),
                                            manual.get(key, (0, ""))[0],
                                            rejected.get(key, 0))
        row["applications"] = written.get(key, 0)
    # Coverage-aware order from the classifier, with the employer adjustment
    # applied to the score first. A posting that names a region we are in
    # (EMEA, Africa) or says nothing is one we can take, so it competes with a
    # worldwide posting on merit; a US-only one sinks below both, and an office
    # or hybrid role abroad sinks below every remote one.
    ranked.sort(key=lambda r: next_role_order(
        _scope_rank(r["region_scope"], r["region_evidence"]),
        (r["match_score"] or 0) + r["adjust"],
        r["match_score"] or 0,
        is_relocation_role(r["workplace_type"], r["location"])))
    # Count the skipped-country postings over the whole list, not inside the
    # loop below: that loop stops as soon as the table is full, so a count kept
    # there would report zero whenever the first twelve rows were all takeable.
    for row in ranked:
        if (row["match_score"] or 0) < RELEVANT_FLOOR and not _admits(
                matcher, row["title"]):
            continue
        country = _skipped_country_of(row, skipped)
        if country:
            skipped_hits[country] = skipped_hits.get(country, 0) + 1
            skipped_ids.add(row["id"])
    # Drop the score-0 junk the feeds carry (writers, sales, assistants) while
    # keeping a score-0 posting whose title the gate admits, since "right kind
    # of role, nothing we recognise in the text" is a judgement for a human.
    top: list = []
    per_employer: dict[str, int] = {}
    seen_roles: set[tuple[str, str]] = set()
    stale = 0
    for row in ranked:
        if (row["match_score"] or 0) < RELEVANT_FLOOR and not _admits(
                matcher, row["title"]):
            continue
        if row["id"] in skipped_ids:
            continue
        if _is_stale(row, today):
            stale += 1
            continue
        if row["company"] in cooling:
            continue
        if per_employer.get(row["company"], 0) >= MAX_PER_EMPLOYER:
            continue
        # The same role reposted on the same board with a fresh id is one lead,
        # not two: keep the first, which is the better-ranked copy.
        role_key = (employer_key(row["company"]),
                    " ".join((row["title"] or "").lower().split()))
        if role_key in seen_roles:
            continue
        seen_roles.add(role_key)
        per_employer[row["company"]] = per_employer.get(row["company"], 0) + 1
        top.append(row)
        if len(top) >= NEXT_ROLE_LIMIT:
            break

    out += ["Ordered by score among the roles you can take (worldwide, a named "
            "region that includes you, or silence), then the rest, so a US-only "
            "posting cannot jump the queue on score alone. An office or hybrid "
            f"role abroad sits below every remote one, and a posting older than "
            f"{STALE_DAYS} days leaves the table. `where` is the posting's own "
            "location or the phrase that set its scope. `adjust` is employer "
            f"history: {APPLICATION_WEIGHT} for each application sent in the "
            f"last {APPLICATION_MEMORY_DAYS} days, {REJECTION_WEIGHT} for each "
            "rejection, plus any named weight. "
            f"At most {MAX_PER_EMPLOYER} per employer, so one company cannot "
            "fill the page:", ""]
    out += _table(["job", "role", "employer", "scope", "where", "score", "adjust"],
                  [[f"#{r['id']}", (r['title'] or '')[:34], r['company'],
                    r['region_scope'],
                    ((r["location"] or r["region_evidence"] or "-"))[:22],
                    r['match_score'],
                    f"{r['adjust']:+d}" if r["adjust"] else "-"] for r in top])

    if any(r["adjust"] for r in top):
        out += ["", "**Why the adjustment.** An employer we have already written "
                f"to loses {APPLICATION_WEIGHT} for each application sent in the "
                f"last {APPLICATION_MEMORY_DAYS} days and {REJECTION_WEIGHT} for "
                "each rejection in the same window, so a new employer surfaces "
                "above one that has already said no. A named weight adds to that. "
                "Change one with `python3 -m db.tools.review employer`:", ""]
        if manual:
            out += _table(
                ["employer", "weight", "reason"],
                [[key, f"{weight:+d}", reason]
                 for key, (weight, reason) in sorted(manual.items())])

    if stale:
        out += ["", f"**Older than {STALE_DAYS} days.** {stale} posting(s) that "
                "pass the gate are left out of the table above because the "
                "posting date is older than that. They stay in the pool, and "
                "`python3 -m db.tools.review dismiss --job N --reason \"...\"` "
                "is how one leaves for good."]

    if skipped_hits:
        out += ["", "**Skipped countries.** "
                f"{sum(skipped_hits.values())} posting(s) that pass the gate are "
                "left out of the table above because their location, or the "
                "posting text when the location is blank, names a country you do "
                "not apply to. They stay in the pool, so removing the country "
                "brings them back without a rescan:", ""]
        out += _table(["country", "left out", "why"],
                      [[key, str(n), skipped[key]["reason"]]
                       for key, n in sorted(skipped_hits.items())])

    if cooling:
        hidden = sum(
            1 for r in ranked
            if r["company"] in cooling
            and ((r["match_score"] or 0) >= RELEVANT_FLOOR
                 or _admits(matcher, r["title"])))
        out += ["", f"**Cooling down.** {len(cooling)} employer(s) have "
                f"{MAX_APPS_PER_EMPLOYER} or more applications inside "
                f"{COOLDOWN_DAYS} days, so the rest of their boards waits "
                f"({hidden} posting(s) left out of the table above). Two "
                "applications already make the case; a fresh requisition is "
                "worth more to them than our impatience:", ""]
        cool_rows = []
        for company, (n, left) in sorted(cooling.items(), key=lambda kv: -kv[1][1]):
            clears = date.fromordinal(today.toordinal() + left)
            cool_rows.append([company, str(n),
                              clears.isoformat() if left else today.isoformat(),
                              f"in {left} day(s)" if left else "today"])
        out += _table(["employer", "applications", "next look", "clears"],
                      cool_rows)

    total, empty, samples = _blind_spot(
        conn, exclude_ids={r["id"] for r in top} | skipped_ids)
    out += ["", f"**Nothing matched in {total} admitted postings.** The title "
            "gate accepts them, the ad text names none of the stack, so they "
            "score 0 and stay out of the table above. "
            f"{empty} of the {total} arrived with no description at all, which "
            "makes them unscorable from here. Newest first, because a closing "
            "date rides on a new posting rather than an old one. Judge the rest "
            "by title: a role can be a fit in a stack the list does not know "
            "yet.", ""]
    blind_rows = []
    for r in samples:
        moment = _posted(r)
        blind_rows.append([f"#{r['id']}", (r['title'] or '')[:40], r['company'],
                           r['region_scope'],
                           moment.date().isoformat() if moment > _EPOCH else "-"])
    out += _table(["job", "role", "employer", "scope", "posted"], blind_rows)
    out.append("")
    return out


def section_health(conn) -> list[str]:
    """Section 5: counts that decide whether section 3 can be trusted."""
    out = ["## 5. Pipeline health", ""]
    by_status = conn.execute(
        "SELECT status, COUNT(*) n FROM jobs GROUP BY status ORDER BY n DESC").fetchall()
    by_scope = conn.execute(
        "SELECT region_scope, COUNT(*) n FROM jobs WHERE status = 'bookmarked'"
        " GROUP BY region_scope ORDER BY n DESC").fetchall()
    scored = conn.execute(
        "SELECT CASE WHEN coalesce(match_score,0) = 0 THEN '0'"
        "        WHEN match_score < 25 THEN '1-24'"
        "        WHEN match_score < 50 THEN '25-49' ELSE '50+' END bucket,"
        "    COUNT(*) n FROM jobs WHERE status = 'bookmarked'"
        " GROUP BY bucket ORDER BY bucket").fetchall()

    out += _table(["jobs by status", "n"],
                  [[r["status"], r["n"]] for r in by_status])
    out += ["", ]
    out += _table(["bookmarked by scope", "n"],
                  [[r["region_scope"], r["n"]] for r in by_scope])
    out += ["", ]
    out += _table(["bookmarked by score", "n"],
                  [[r["bucket"], r["n"]] for r in scored])

    unknown_company = _count(
        conn, "SELECT COUNT(*) FROM jobs WHERE company IN ('Unknown', '')")
    dup = _count(conn, "SELECT COUNT(*) FROM jobs j WHERE j.status = 'bookmarked'"
                       " AND EXISTS (SELECT 1 FROM jobs k WHERE k.company = j.company"
                       "   AND k.title = j.title AND k.id <> j.id)")
    archived_with_reason = _count(
        conn, "SELECT COUNT(*) FROM jobs WHERE status = 'archived'"
              " AND json_extract(metadata, '$.reason_for_archive') IS NOT NULL")
    out += ["", "Housekeeping (`db/jobs.db` only, nothing here is urgent):", "",
            f"- {unknown_company} posting(s) with no employer resolved.",
            f"- {dup} bookmarked row(s) duplicated by company + title.",
            f"- {archived_with_reason} archived row(s) with a recorded reason."]
    pushes = _unpushed_commits()
    if pushes:
        out.append(f"- {pushes} commit(s) ahead of `origin/main` (unpushed).")
    out.append("")
    return out


def section_questions(conn) -> list[str]:
    """Section 6: what the bank knows, and what it still needs from you."""
    out = ["## 6. Question bank", ""]
    total = _count(conn, "SELECT COUNT(*) FROM questions")
    asked_twice = _count(
        conn, "SELECT COUNT(*) FROM questions_with_frequency WHERE times_asked >= 2")
    out.append(f"{total} question(s) recorded; {asked_twice} asked more than once "
               "(those are the ones worth stabilising).")
    out.append("")
    out.append("`state` is derived from the instance ledger, not kept by hand: "
               "`unsent` has never been on a submitted application, `sent` is "
               "exactly what an employer received, and `revised` went out and has "
               "changed since.")
    revised = _count(conn, "SELECT COUNT(*) FROM questions_with_frequency"
                           " WHERE state = 'revised' AND retired_at IS NULL")
    if revised:
        out.append("")
        out.append(f"{revised} row(s) read `revised`, which is the expected state "
                   "of the bank rather than a task: an answer is worded per "
                   "application, so stored text differing from what one employer "
                   "received is normal and needs no decision. What carries forward "
                   "is the reasoning, which `python3 -m db.tools.questions lookup` "
                   "prints as `WHY` beside the text that was sent.")
    out.append("")
    rows = conn.execute(
        "SELECT id, question_key, kind, times_asked, state,"
        "       substr(canonical_text, 1, 58) q"
        " FROM questions_with_frequency WHERE retired_at IS NULL"
        " ORDER BY state = 'revised' DESC, times_asked DESC, id LIMIT 20").fetchall()
    out += _table(["id", "key", "kind", "asked", "state", "question"],
                  [[r["id"], f"`{r['question_key']}`", r["kind"], r["times_asked"],
                    r["state"], r["q"]] for r in rows])
    out.append("")
    return out


def last_refreshed(path: Path | str = DEFAULT_OUT) -> str | None:
    """The `Refreshed:` stamp this file carried last time, or None.

    The marker lives in the file rather than in a table: one file, one line,
    and no schema to keep in step with something that is only a reading aid.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    match = REFRESHED_RE.search(text)
    return match.group("stamp") if match else None


def build_digest(conn: sqlite3.Connection, today: date | None = None,
                 since: str | None = None, now: datetime | None = None) -> str:
    """The whole digest as markdown."""
    today = today or datetime.now(timezone.utc).date()
    now = now or datetime.now(timezone.utc)
    apps = _applications(conn)

    lines = [
        "# Review digest",
        "",
        f"Refreshed: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        "One living file, rewritten in place. It holds no state of its own: a "
        "stale line leaves because the row behind it was resolved in "
        "`db/jobs.db`, never because it was edited out here. Closing commands:",
        "",
        "```bash",
        "python3 -m db.tools.review                                # rewrite this file",
        "python3 -m db.tools.review follow-up --app 4 --in-days 7  # schedule a follow-up",
        "python3 -m db.tools.review resolve --event 12             # close one",
        "python3 -m db.tools.review todo --add \"...\"               # remember an action",
        "python3 -m db.tools.review todo --close 3                 # close one",
        "python3 -m db.tools.review dismiss --job 616 --reason \"...\"   # drop a lead",
        "python3 -m db.tools.questions retire --key KEY            # set an answer aside",
        "```",
        "",
    ]
    lines += ([f"{len(apps)} application(s) on file.", ""] if apps
              else ["No applications on file yet.", ""])

    lines += section_since(conn, since)
    lines += section_needs_you(conn, apps, today)
    lines += section_applications(apps, today)
    lines += section_next_roles(conn, today)
    lines += section_health(conn)
    lines += section_questions(conn)
    return "\n".join(lines)


# --- commands ---------------------------------------------------------------


def cmd_digest(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    today = datetime.now(timezone.utc).date()
    path = Path(args.out)
    since = last_refreshed(path)
    text = build_digest(conn, today, since=since)
    if args.stdout:
        print(text)
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

    apps = _applications(conn)
    wait = [r for r in apps
            if follow_up_action(r["app_status"],
                                days_since(r["applied_at"], today),
                                bool(r["last_signal"]), r["due_follow_up"],
                                today.isoformat(),
                                days_since(r["last_follow_up"], today)
                                ).startswith(("submit", "consider",
                                              "follow up"))]
    moved = "since " + since.replace("T", " ").replace("Z", " UTC") if since else "first run"
    open_todos = _count(conn, "SELECT COUNT(*) FROM open_todos")
    print(f"rewrote {path}  ({len(apps)} application(s), {len(wait)} needing "
          f"action, {open_todos} todo(s) open, {moved})")
    for row in wait:
        print(f"  #{row['app_id']} {row['company']}: {row['title']}")
    for row in conn.execute("SELECT id, text, owner FROM open_todos"):
        print(f"  todo #{row['id']} [{row['owner']}] {row['text']}")
    return 0


def cmd_country(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    """Keep the list of countries the user does not apply to, with its reasons.

    A posting whose location names one of these countries leaves the shortlist
    without leaving the pool, so the decision is reversible: remove the row and
    the postings are back. The terms are regular expressions because one country
    has several spellings on these boards, including city names that never say
    the country at all.

    `--term` reads the location fields and `--text-term` reads the ad text. The
    second list exists because some boards leave the location empty and declare
    the place in the first line of the description. It is applied only when the
    location fields say nothing, so keep its patterns to phrasings that declare
    where the work sits: a company also names its offices and its customers.
    """
    if args.remove:
        key = args.remove.strip().lower()
        cur = conn.execute("DELETE FROM skipped_countries WHERE country_key = ?", (key,))
        conn.commit()
        print(f"removed {key}" if cur.rowcount else f"no skipped country {key}")
        return 0
    if args.add:
        if not args.reason:
            print("--add needs --reason")
            return 1
        if not args.term and not args.text_term:
            print("--add needs at least one --term or --text-term"
                  " (a case-insensitive regex)")
            return 1
        key = args.add.strip().lower()
        conn.execute(
            "INSERT INTO skipped_countries"
            " (country_key, terms, terms_in_text, reason, updated_at)"
            " VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
            " ON CONFLICT(country_key) DO UPDATE SET terms = excluded.terms,"
            " terms_in_text = excluded.terms_in_text, reason = excluded.reason,"
            " updated_at = excluded.updated_at",
            (key, json.dumps(args.term or []),
             json.dumps(args.text_term or []), args.reason))
        conn.commit()
        print(f"{key}: {len(args.term or [])} location term(s),"
              f" {len(args.text_term or [])} text term(s)  {args.reason}")
        return 0
    rows = conn.execute(
        "SELECT country_key, terms, reason, updated_at,"
        "       coalesce(terms_in_text, '[]') AS terms_in_text"
        " FROM skipped_countries ORDER BY country_key").fetchall()
    if not rows:
        print("no skipped countries stored")
        return 0
    for row in rows:
        terms, text_terms = [], []
        for column, target in (("terms", terms),
                               ("terms_in_text", text_terms)):
            try:
                target += json.loads(row[column] or "[]")
            except ValueError:
                pass
        print(f"{row['country_key']:<16} {len(terms)} location term(s),"
              f" {len(text_terms)} text term(s)"
              f"  {row['reason']}  (set {row['updated_at'][:10]})")
        for term in terms:
            print(f"    location  {term}")
        for term in text_terms:
            print(f"    text      {term}")
    return 0


def cmd_employer(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    """Keep a named score weight per employer, with the reason beside it.

    The shortlist already counts how often we have written to an employer. This
    is the part a count cannot know: requirements that sit outside the record,
    or a history that makes a rejection likely. The weight is data, so the
    decision is changed here rather than by editing the digest.
    """
    if args.remove:
        key = employer_key(args.remove)
        cur = conn.execute("DELETE FROM employer_weights WHERE company_key = ?", (key,))
        conn.commit()
        print(f"removed weight for {key}" if cur.rowcount
              else f"no weight stored for {key}")
        return 0
    if args.set:
        if args.weight is None or not args.reason:
            print("--set needs --weight and --reason")
            return 1
        key = employer_key(args.set)
        conn.execute(
            "INSERT INTO employer_weights (company_key, weight, reason, updated_at)"
            " VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
            " ON CONFLICT(company_key) DO UPDATE SET weight = excluded.weight,"
            " reason = excluded.reason, updated_at = excluded.updated_at",
            (key, args.weight, args.reason))
        conn.commit()
        print(f"{key}: {args.weight:+d}  {args.reason}")
        return 0
    rows = conn.execute(
        "SELECT company_key, weight, reason, updated_at FROM employer_weights"
        " ORDER BY weight, company_key").fetchall()
    if not rows:
        print("no employer weights stored")
        return 0
    for row in rows:
        print(f"{row['company_key']:<28} {row['weight']:+4d}  {row['reason']}"
              f"  (set {row['updated_at'][:10]})")
    return 0


def cmd_dismiss(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    """Take a lead out of the pool, with the reason recorded on the row.

    The counterpart to applying: a posting you have read and decided against
    should leave the shopping list, and the reason should outlive the decision
    so the same posting is not re-argued in a month.
    """
    row = conn.execute(
        "SELECT id, title, company, status FROM jobs WHERE id = ?",
        (args.job,)).fetchone()
    if row is None:
        print(f"no job #{args.job}")
        return 1
    if row["status"] == "applied":
        print(f"#{args.job} already has an application. Withdraw that instead: "
              "it is a pipeline decision, not a lead decision.")
        return 1
    conn.execute(
        "UPDATE jobs SET status = 'archived',"
        " metadata = json_set(coalesce(metadata, '{}'), '$.reason_for_archive', ?),"
        " updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
        " WHERE id = ?", (args.reason, args.job))
    conn.commit()
    print(f"archived #{args.job}  {row['company']} - {row['title']}")
    print(f"  reason: {args.reason}")
    return 0


def cmd_follow_up(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    row = conn.execute(
        "SELECT a.id, j.company, j.title FROM applications a JOIN jobs j"
        " ON j.id = a.job_id WHERE a.id = ?", (args.app,)).fetchone()
    if row is None:
        print(f"no application #{args.app}")
        return 1
    due = (datetime.now(timezone.utc).date()
           + timedelta(days=args.in_days)).isoformat()
    summary = args.note or f"Chase {row['company']} about {row['title']}"
    conn.execute(
        "INSERT INTO application_events"
        " (application_id, event_type, scheduled_for, summary, metadata)"
        " VALUES (?, 'follow_up', ?, ?, '{}')",
        (args.app, due, summary))
    conn.commit()
    print(f"scheduled follow-up for application #{args.app} ({row['company']}) on {due}")
    print(f"  {summary}")
    return 0


def cmd_reply(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    """Record that the employer made contact.

    A `reply` event is what clears this application's follow-up reminder without
    moving its status, so it has a command rather than a SQL statement: a reply
    that is never recorded leaves the digest suggesting a follow-up on an
    application the employer has already answered.
    """
    row = conn.execute(
        "SELECT a.id, a.status, j.company, j.title FROM applications a JOIN jobs j"
        " ON j.id = a.job_id WHERE a.id = ?", (args.app,)).fetchone()
    if row is None:
        print(f"no application #{args.app}")
        return 1
    conn.execute(
        "INSERT INTO application_events"
        " (application_id, event_type, from_status, to_status, occurred_at,"
        "  summary, details) VALUES (?, 'reply', ?, ?, ?, ?, ?)",
        (args.app, row["status"], row["status"],
         args.date or datetime.now(timezone.utc).strftime(
             "%Y-%m-%dT%H:%M:%SZ"), args.summary, args.details))
    conn.commit()
    print(f"recorded a reply on application #{args.app} ({row['company']}), "
          f"status {row['status']}")
    print(f"  {args.summary}")
    print("  the follow-up reminder is cleared; a status move is a separate event")
    return 0


def cmd_submitted(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    """Record that the user sent the application.

    The counterpart of `reply`: this event is OURS, so it does not clear the
    follow-up reminder, it starts the count. It sets `applications.applied_at`,
    which is what the day count is measured from, and it refuses a second
    recording, because a second `applied` event reads as a second submission and
    would move `applied_at` to today, pushing the reminder out another seven
    days.

    Every private value is an argument (confirmation link, date, method, the
    line that shows in the digest), so the code stays generic and the facts stay
    in the gitignored database.
    """
    row = conn.execute(
        "SELECT a.id, a.status, a.method, j.company, j.title FROM applications a"
        " JOIN jobs j ON j.id = a.job_id WHERE a.id = ?", (args.app,)).fetchone()
    if row is None:
        print(f"no application #{args.app}")
        return 1
    already = conn.execute(
        "SELECT occurred_at FROM application_events WHERE application_id = ?"
        " AND event_type = 'applied' ORDER BY id LIMIT 1", (args.app,)).fetchone()
    if already is not None:
        print(f"application #{args.app} ({row['company']}) is already recorded as"
              f" submitted ({already['occurred_at']}); nothing changed")
        return 1
    when = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary = args.note or (
        "Submitted by the user"
        + ("; confirmation page reached" if args.confirmation else ""))
    conn.execute(
        "UPDATE applications SET status = 'applied', applied_at = ?,"
        " method = coalesce(?, method),"
        " metadata = json_set(coalesce(metadata, '{}'), '$.form_state',"
        " 'submitted'), updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')"
        " WHERE id = ?", (when, args.method, args.app))
    # The posting moves too: the runbook's status flows say a submitted
    # application is `applied` on both rows, and a job left at `bookmarked`
    # after its application went out is a lead the digest will offer again.
    conn.execute(
        "UPDATE jobs SET status = 'applied', updated_at ="
        " strftime('%Y-%m-%dT%H:%M:%SZ','now')"
        " WHERE id = (SELECT job_id FROM applications WHERE id = ?)", (args.app,))
    if args.confirmation:
        conn.execute(
            "UPDATE applications SET metadata = json_set(metadata,"
            " '$.confirmation_url', ?) WHERE id = ?", (args.confirmation, args.app))
    conn.execute(
        "INSERT INTO application_events (application_id, event_type, from_status,"
        " to_status, occurred_at, summary, details) VALUES (?, 'applied', ?,"
        " 'applied', ?, ?, ?)",
        (args.app, row["status"], when, summary, args.details))
    conn.commit()
    print(f"application #{args.app} ({row['company']}): {row['status']} -> applied,"
          f" submitted {when}")
    print(f"  {summary}")
    print("  applied_at set, so the follow-up reminder counts from this date."
          " Anything sent that differs from the bank goes in as an instance:")
    print("  python3 -m db.tools.questions record --key <question>"
          " --answer-given \"<what went out>\" --application-id"
          f" {args.app}")
    return 0


def cmd_resolve(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    row = conn.execute(
        "SELECT id, application_id, scheduled_for, summary FROM application_events"
        " WHERE id = ? AND event_type = 'follow_up'", (args.event,)).fetchone()
    if row is None:
        print(f"no follow-up event #{args.event}")
        return 1
    conn.execute(
        "UPDATE application_events"
        " SET metadata = json_set(coalesce(metadata, '{}'), '$.done', 1,"
        "     '$.done_at', strftime('%Y-%m-%dT%H:%M:%SZ','now'), '$.done_note', ?)"
        " WHERE id = ?", (args.note or "", args.event))
    conn.commit()
    print(f"closed follow-up #{args.event} (application #{row['application_id']}, "
          f"was due {row['scheduled_for']})")
    return 0


def cmd_todo(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    """Add, list or close an open action that has no row of its own.

    The digest's one bit of stored state. Every other line on the page is
    derived from something that exists for its own sake; a `todos` row exists
    only to be remembered, and closing it is the whole lifecycle.
    """
    if args.add:
        cursor = conn.execute(
            "INSERT INTO todos (text, owner, context) VALUES (?, ?, ?)",
            (args.add, args.owner, args.context))
        conn.commit()
        print(f"added todo #{cursor.lastrowid}  ({todo_owner_label(args.owner)})")
        print(f"  {args.add}")
        if args.context:
            print(f"  context: {args.context}")
        return 0

    if args.close is not None:
        row = conn.execute("SELECT id, text, closed_at FROM todos WHERE id = ?",
                           (args.close,)).fetchone()
        if row is None:
            print(f"no todo #{args.close}")
            return 1
        if row["closed_at"]:
            print(f"todo #{args.close} was already closed on {row['closed_at'][:10]}")
            return 1
        conn.execute(
            "UPDATE todos SET closed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            " WHERE id = ?", (args.close,))
        conn.commit()
        print(f"closed todo #{args.close}: {row['text']}")
        return 0

    rows = conn.execute("SELECT id, text, owner, context, created_at"
                        " FROM open_todos").fetchall()
    if not rows:
        print("no open todos")
        return 0
    for row in rows:
        print(f"#{row['id']}  [{row['owner']}]  {row['text']}"
              f"  (added {row['created_at'][:10]})")
        if row["context"]:
            print(f"      {row['context']}")
    return 0


def cmd_selftest() -> int:
    today = "2026-10-18"
    cases = [
        (("ready_to_apply", None, False, None), "submit it"),
        (("applied", 3, False, None), "nothing yet (follow up on day 7)"),
        (("applied", 9, False, None), "consider a follow-up (out 9 days)"),
        (("applied", 12, False, "2026-10-20"), "follow up on 2026-10-20"),
        (("applied", 12, False, "2026-10-10"), "follow up now (was due 2026-10-10)"),
        (("applied", 20, True, None), "no action (a reply is on record)"),
        (("interviewing", 5, True, None), "active, keep it warm (interviewing)"),
        (("rejected", 30, True, None), "closed"),
        (("withdrawn", None, False, None), "closed"),
    ]
    failures = 0
    for (status, days, signal, due), expected in cases:
        got = follow_up_action(status, days, signal, due, today)
        if got != expected:
            failures += 1
            print(f"FAIL  {status} days={days} signal={signal} due={due}\n"
                  f"      expected {expected!r}\n      got      {got!r}")
    # A follow-up already sent is not a follow-up still to send: inside the
    # waiting window the prompt goes quiet, and it comes back once the window
    # passes with still no reply.
    followed_cases = [
        ((9, 2), "followed up 2d ago; nudge after day 7"),
        ((3, 1), "followed up 1d ago; nudge after day 7"),
        ((9, 7), "consider a follow-up (out 9 days)"),
        ((9, 40), "consider a follow-up (out 9 days)"),
    ]
    for (days, followed), expected in followed_cases:
        got = follow_up_action("applied", days, False, None, today, followed)
        if got != expected:
            failures += 1
            print(f"FAIL  followed_up_days={followed} days={days}\n"
                  f"      expected {expected!r}\n      got      {got!r}")
    if follow_up_action("applied", 9, False, None, today, 2) != \
            follow_up_action("applied", 9, False, None, today, 2):
        failures += 1
        print("FAIL  follow-up suppression is not stable")

    # Employer history: every application inside the memory window takes points
    # off, a named weight adds to that, and a negative count is not a credit.
    adjust_cases = [
        ((0, 0), 0),
        ((2, 0), 2 * APPLICATION_WEIGHT),
        ((2, -25), 2 * APPLICATION_WEIGHT - 25),
        ((-3, 0), 0),
    ]
    for (apps, manual_weight), expected in adjust_cases:
        got = employer_adjustment(apps, manual_weight)
        if got != expected:
            failures += 1
            print(f"FAIL  employer_adjustment({apps}, {manual_weight}) = {got}, "
                  f"expected {expected}")

    # Order: a takeable role at 96 outranks a worldwide one at 38 once employer
    # history is applied, and a US-only 99 still sinks below both.
    if not next_role_order(2, 96, 96) < next_role_order(0, 38, 38):
        failures += 1
        print("FAIL  a takeable 96 must outrank a worldwide 38")
    if not next_role_order(0, 20, 20) < next_role_order(4, 99, 99):
        failures += 1
        print("FAIL  a US-only 99 must still sink below a takeable 20")
    if employer_key("  M-KOPA   Nigeria ") != "m-kopa nigeria":
        failures += 1
        print("FAIL  employer_key does not normalise")
    if employer_adjustment(1, 0, 1) != APPLICATION_WEIGHT + REJECTION_WEIGHT:
        failures += 1
        print("FAIL  a rejection does not add its own weight")

    # Relocation: an office abroad is not a remote lead, while a remote posting
    # with a city beside it stays one, and a local office is local work.
    relocation_cases = [
        (("unknown", "Berlin"), True),
        (("unknown", "Oeiras or Krakow or Dublin"), True),
        (("onsite", "Lagos, Nigeria"), False),
        (("hybrid", "Lagos, Nigeria"), False),
        (("remote", "Berlin"), False),
        (("unknown", "Remote - EMEA"), False),
        (("unknown", None), False),
    ]
    for (kind, place), expected in relocation_cases:
        got = is_relocation_role(kind, place)
        if got != expected:
            failures += 1
            print(f"FAIL  is_relocation_role({kind!r}, {place!r}) = {got}, "
                  f"expected {expected}")

    if days_since("2026-10-11T00:00:00Z", date(2026, 10, 18)) != 7:
        failures += 1
        print("FAIL  days_since did not measure 7 days")
    if days_since(None, date(2026, 10, 18)) is not None:
        failures += 1
        print("FAIL  days_since(None) should be None")

    # Where a posting hires: a named region we are in beats "says nothing",
    # which beats a named list that excludes us, and us_only sinks last.
    rank_cases = [
        ("worldwide", "Anywhere", 0),
        ("region_gated", "Remote, EMEA", 1),
        ("region_gated", "Africa", 1),
        ("unknown", None, 2),
        ("region_gated", "Europe, USA, Canada, APAC", 3),
        ("region_gated", "Remote, AMER", 3),
        ("us_only", "Remote, USA", 4),
    ]
    for scope, evidence, expected in rank_cases:
        got = _scope_rank(scope, evidence)
        if got != expected:
            failures += 1
            print(f"FAIL  _scope_rank({scope!r}, {evidence!r}) = {got}, "
                  f"expected {expected}")
    if not (_scope_rank("region_gated", "EMEA") < _scope_rank("unknown", None)
            < _scope_rank("region_gated", "APAC") < _scope_rank("us_only", None)):
        failures += 1
        print("FAIL  scope order is not covering < unknown < excluding < us_only")

    # Recency for the blind-spot table: posted date wins, both timestamp
    # shapes parse, and a row with nothing usable sorts last.
    def _row(**kw):
        base = {"id": 1, "posted_at": None, "bookmarked_at": None,
                "created_at": None}
        return {**base, **kw}

    order_cases = [
        ({"posted_at": "2026-10-16T10:01:36+00:00"},
         {"posted_at": "2026-10-01T00:00:00Z"}, True,
         "a newer posted_at sorts first across offset and Z shapes"),
        ({"posted_at": "2026-01-01T00:00:00Z", "bookmarked_at": "2026-10-18T10:00:00Z"},
         {"created_at": "2026-10-17T00:00:00Z"}, False,
         "posted_at outranks when we saved it, so an old posting still sinks"),
        ({"bookmarked_at": "2026-10-18T10:27:27Z"},
         {"created_at": "2026-10-17T00:00:00Z"}, True,
         "bookmarked_at is the fallback"),
        ({"created_at": "2026-10-18T00:00:00Z"}, {}, True,
         "a row with no timestamps sorts last"),
    ]
    for newer, older, expect_first, why in order_cases:
        got = _posted(_row(**newer)) > _posted(_row(**older))
        if got != expect_first:
            failures += 1
            print(f"FAIL  recency: {why}")

    # Who acts on a todo: the user's own work reads as theirs, and anything else
    # falls to the agent rather than defaulting work onto the user.
    label_cases = [
        ("user", "Yours to do"),
        ("agent", "Agent to do"),
        (None, "Agent to do"),
        ("", "Agent to do"),
        ("someone", "Agent to do"),
    ]
    for owner, expected in label_cases:
        got = todo_owner_label(owner)
        if got != expected:
            failures += 1
            print(f"FAIL  todo_owner_label({owner!r}) = {got!r}, "
                  f"expected {expected!r}")

    # The employer cooldown: two applications inside the week park the rest of
    # that board, and the window clears a week after the most recent one. A
    # single application, an old application, or an unsent draft says nothing.
    cool_cases = [
        ([("Acme", 1), ("Acme", 3)], {"Acme": (2, 6)},
         "two inside the week park the board; six days left on the newest"),
        ([("Acme", 0), ("Acme", 6)], {"Acme": (2, 7)},
         "the window clears a week after the newest application"),
        ([("Acme", 1)], {},
         "one application is not a pattern"),
        ([("Acme", 8), ("Acme", 2)], {},
         "an application outside the window does not count toward it"),
        ([("Acme", 8), ("Acme", 2), ("Acme", 1)], {"Acme": (2, 6)},
         "only the applications inside the window count"),
        ([("Acme", None), ("Acme", 1)], {},
         "an application that was never sent says nothing"),
        ([("", 1), ("Acme", 1)], {},
         "a posting with no employer resolved cannot be parked"),
        ([("Acme", 3), ("Acme", 1), ("Other", 2), ("Other", 4)],
         {"Acme": (2, 6), "Other": (2, 5)},
         "each employer keeps its own window"),
    ]
    for applied, expected, why in cool_cases:
        got = employer_cooldown(applied)
        if got != expected:
            failures += 1
            print(f"FAIL  employer_cooldown: {why}\n"
                  f"      expected {expected!r}\n      got      {got!r}")

    # Skipped countries: the location fields decide first, and the ad text is
    # read only when they say nothing. The text list holds phrasings that
    # declare where the work sits, so a company naming its team or its offices
    # does not hide a worldwide posting.
    india = {"india": {
        "terms": [re.compile(r"\bindia\b", re.I),
                  re.compile(r"(?:^|[,|]\s*)IN\s*(?:[,|]|$)", re.I),
                  re.compile(r"\b(?:bangalore|bengaluru|mumbai|pune)\b", re.I)],
        "text_terms": [
            re.compile(r"\b(?:based|located|office|position)\s+(?:in|at)\s+"
                       r"(?:bangalore|bengaluru)\b", re.I),
            re.compile(r"\b(?:engineer|developer|position|role|candidate)\b"
                       r"[^.\n]{0,40}\bbased in india\b", re.I),
            re.compile(r"\bremote\s*[-–—(]\s*india\b", re.I),
            re.compile(r"\blocation\s*[:\-–—]\s*(?:remote\s*[-–—(]?\s*)?"
                       r"(?:india|bangalore|bengaluru)\b", re.I),
        ],
        "reason": "test",
    }}
    country_cases = [
        ({"location": "India", "region_evidence": "India", "raw_text": ""},
         "india", "the country named as the location"),
        ({"location": "KA, IN | Bengaluru, KA, IN", "region_evidence": "",
          "raw_text": ""}, "india", "a city and the two-letter code"),
        ({"location": "", "region_evidence": "",
          "raw_text": "This is a Fulltime position based in Bangalore ."},
         "india", "an empty location, with the city declared in the text"),
        ({"location": "", "region_evidence": "",
          "raw_text": "We are hiring a Product Engineer based in India who will "
                      "ship features."},
         "india", "a role noun beside 'based in <country>'"),
        ({"location": "", "region_evidence": "",
          "raw_text": "Location - India (Remote) Build the network."},
         "india", "a location line that starts with the country"),
        ({"location": "", "region_evidence": "",
          "raw_text": "Remote - India. Reports to the CTO."},
         "india", "'Remote - <country>' in the text"),
        ({"location": "Philippines", "region_evidence": "",
          "raw_text": "A company with most of our team based in India and the "
                      "Philippines."},
         None, "a team named in the text is not the job's location"),
        ({"location": "Remote, USA", "region_evidence": "Remote, USA",
          "raw_text": "Location: North America, LATAM, or India"},
         None, "a multi-region list is not an India role"),
        ({"location": "", "region_evidence": "",
          "raw_text": "We have offices in Bangalore, Berlin and Austin."},
         None, "an office named in the text is not the job's location"),
        ({"location": "", "region_evidence": "",
          "raw_text": "Our team is based in India."},
         None, "no role noun beside the country, so no match"),
        ({"location": "Remote", "region_evidence": "",
          "raw_text": "This position is based in Bangalore."},
         None, "a stated location is never overridden by the text"),
    ]
    for row, expected, why in country_cases:
        got = _skipped_country_of(row, india)
        if got != expected:
            failures += 1
            print(f"FAIL  skipped country: {why}\n"
                  f"      expected {expected!r}\n      got      {got!r}")
    if _skipped_country_of({"location": "India", "region_evidence": "",
                            "raw_text": ""}, {}) is not None:
        failures += 1
        print("FAIL  no skipped countries must match nothing")

    # What clears the follow-up reminder: employer contact only. Our own notes
    # and our own follow-ups must never count as contact, because the applications
    # most likely to be documented are the ones most likely to go unanswered.
    for ours in ("note", "follow_up", "applied", "status_change", "withdrawal"):
        if ours in SIGNAL_EVENT_TYPES:
            failures += 1
            print(f"FAIL  {ours!r} is our own action and cannot be a signal")
    for theirs in ("interview", "offer", "rejection", "reply"):
        if theirs not in SIGNAL_EVENT_TYPES:
            failures += 1
            print(f"FAIL  {theirs!r} is employer contact and must be a signal")

    total = (len(cases) + 2 + len(followed_cases) + 1 + len(adjust_cases) + 4
             + len(relocation_cases) + len(rank_cases) + 1 + len(order_cases)
             + len(label_cases) + len(cool_cases) + len(country_cases) + 1
             + len(SIGNAL_EVENT_TYPES))
    print(f"{total - failures}/{total} cases pass")
    return 1 if failures else 0


# --- CLI --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m db.tools.review",
        description="The decision queue: follow-ups, applications, next roles.")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("digest", help="rewrite the digest (the default)")
    p.add_argument("--out", default=str(DEFAULT_OUT),
                   help=f"the living file (default: {DEFAULT_OUT})")
    p.add_argument("--stdout", action="store_true", help="print instead of writing")
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("follow-up", help="schedule a follow-up for an application")
    p.add_argument("--app", type=int, required=True, help="application id")
    p.add_argument("--in-days", dest="in_days", type=int, default=1)
    p.add_argument("--note", help="what the follow-up is for")
    p.set_defaults(func=cmd_follow_up)

    p = sub.add_parser("reply", help="record contact from the employer")
    p.add_argument("--app", type=int, required=True, help="application id")
    p.add_argument("--summary", required=True, help="what they said")
    p.add_argument("--details", help="the longer version")
    p.add_argument("--date", help="when it arrived (default: now)")
    p.set_defaults(func=cmd_reply)

    p = sub.add_parser("submitted", help="record that the user sent the application")
    p.add_argument("--app", type=int, required=True, help="application id")
    p.add_argument("--method", choices=("online_form", "email", "referral",
                                        "linkedin", "recruiter", "other"),
                   help="how it went out (default: whatever the row already says)")
    p.add_argument("--confirmation", help="confirmation URL or reference")
    p.add_argument("--note", help="the one line that shows in the digest")
    p.add_argument("--details", help="the longer version")
    p.add_argument("--date", help="when it was sent (default: now)")
    p.set_defaults(func=cmd_submitted)

    p = sub.add_parser("resolve", help="mark a scheduled follow-up as done")
    p.add_argument("--event", type=int, required=True, help="application_events id")
    p.add_argument("--note", help="how it went")
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("dismiss", help="archive a lead with a reason")
    p.add_argument("--job", type=int, required=True, help="jobs id")
    p.add_argument("--reason", required=True, help="why it is out of the pool")
    p.set_defaults(func=cmd_dismiss)

    p = sub.add_parser("todo",
                       help="your own open actions, which have no row behind them")
    p.add_argument("--add", metavar="TEXT", help="remember an action")
    p.add_argument("--owner", choices=("user", "agent"), default="user",
                   help="who acts on it (default: user)")
    p.add_argument("--context", help="where it came from, why it is wanted")
    p.add_argument("--close", type=int, metavar="ID", help="close a todo by id")
    p.set_defaults(func=cmd_todo)

    p = sub.add_parser("employer",
                       help="set, list or remove an employer score weight")
    p.add_argument("--set", metavar="COMPANY",
                   help="employer name to weight")
    p.add_argument("--weight", type=int,
                   help="points added to each of their postings (negative demotes)")
    p.add_argument("--reason", help="why, in one line")
    p.add_argument("--remove", metavar="COMPANY", help="drop the weight")
    p.set_defaults(func=cmd_employer)

    p = sub.add_parser("country",
                       help="set, list or remove a country to skip")
    p.add_argument("--add", metavar="COUNTRY", help="country key to skip")
    p.add_argument("--term", action="append", metavar="REGEX",
                   help="case-insensitive regex matched against location and"
                        " region_evidence (repeatable)")
    p.add_argument("--text-term", action="append", metavar="REGEX",
                   help="case-insensitive regex matched against the posting"
                        " text, used only when the location is empty"
                        " (repeatable)")
    p.add_argument("--reason", help="why, in one line")
    p.add_argument("--remove", metavar="COUNTRY", help="drop the country")
    p.set_defaults(func=cmd_country)

    p = sub.add_parser("selftest", help="check the decision logic on fixed cases")
    p.set_defaults(func=lambda conn, args: cmd_selftest())

    return parser


def main(argv: list[str] | None = None) -> int:
    incoming = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(incoming or ["digest"])
    conn = connect()
    try:
        return args.func(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
