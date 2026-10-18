"""Review digest: the decisions waiting on a human, in one page.

The scanner writes leads, the application runbook files applications, and the
question bank accumulates answers. None of that tells you what needs a decision
this week. This tool reads the database and produces that page:

    python3 -m db.tools.review                    # rewrite artifacts/review.md
    python3 -m db.tools.review follow-up --app 3 --in-days 7
    python3 -m db.tools.review resolve --event 4
    python3 -m db.tools.review dismiss --job 616 --reason "posting closed"

One living file, rewritten in place, not a dated log. There is nothing to
accumulate: the digest holds no state, and a stale item leaves the page by
being resolved in the database (a chase closed, a lead archived, an answer
retired), not by being edited out of the text. Hand edits would be lost on
the next rewrite, which is why every actionable line carries the command that
closes it. The database is the memory; this page is a view.

The file is private (gitignored, via `artifacts/`): it names employers, and
this repo is public.

Sections are ordered by what is most likely to be expensive to miss:

1. Since you last looked   what changed since the previous rewrite
2. Needs you now           follow-ups due, applications filled but not sent
3. Applications            every application with its age and next action
4. Next roles              bookmarked postings, best-ranked first
5. Pipeline health         counts that say whether the ranking can be trusted
6. Question bank           answers still awaiting a human read

Section 1 is the one that makes reading this "from time to time" cheap: it is
computed against the `Refreshed:` line this file carried last time, so it needs
no extra bookkeeping and cannot drift.

The follow-up clock is `FOLLOW_UP_AFTER_DAYS`: an application that has been out
that long with no reply on record is worth chasing. The digest only suggests
that; scheduling is an explicit command so the signal stays yours.
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

#: Days after submission with no reply on record before a chase is suggested.
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

#: Below this score a posting is only listed when its title plainly names one of
#: our roles. Matches the scanner's own MATCH_MIN_SCORE default; a literal
#: rather than a read, because this module only needs the scanner's gate
#: (`_matcher`) and must still render when that import fails.
RELEVANT_FLOOR = 15

#: How many postings one employer may contribute to the shortlist.
MAX_PER_EMPLOYER = 2

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


def follow_up_action(
    status: str,
    applied_days: int | None,
    has_signal: bool,
    due_on: str | None,
    today: str,
) -> str:
    """What (if anything) this application needs, as a short phrase.

    `due_on` is an explicit scheduled follow-up date; it outranks the age clock,
    because a scheduled date is a decision already made.
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
    if applied_days is None:
        return "no action (no submission date)"
    if applied_days >= FOLLOW_UP_AFTER_DAYS:
        return f"consider a follow-up (out {applied_days} days)"
    return f"let it breathe (chase on day {FOLLOW_UP_AFTER_DAYS})"


# --- queries ----------------------------------------------------------------


APPLICATION_SQL = """
SELECT a.id AS app_id, a.job_id, a.status AS app_status, a.applied_at,
       a.method, a.resume_variant, a.updated_at,
       j.title, j.company, j.region_scope, j.url, j.status AS job_status,
       (SELECT MAX(e.occurred_at) FROM application_events e
         WHERE e.application_id = a.id
           AND e.event_type IN ('interview', 'offer', 'rejection', 'note',
                                'follow_up')) AS last_signal,
       (SELECT MIN(e.scheduled_for) FROM application_events e
         WHERE e.application_id = a.id AND e.event_type = 'follow_up'
           AND e.scheduled_for IS NOT NULL
           AND json_extract(e.metadata, '$.done') IS NULL) AS due_follow_up,
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
        "SELECT e.application_id, e.event_type, e.to_status, e.summary,"
        "       e.occurred_at, j.company, j.title"
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
        out.append(f"- **Application #{e['application_id']}** ({e['company']}): "
                   f"{e['event_type']} -> {e['to_status'] or '-'}{note}")
    for r in left_pool:
        out.append(f"- **Left the pool**: {r['company']} - {r['title']} "
                   f"(`{r['status']}`)")
    out.append("")
    return out


def section_needs_you(conn, apps, today: date) -> list[str]:
    """Section 2: anything with a date attached or a decision outstanding."""
    out = ["## 2. Needs you now", ""]
    items: list[str] = []

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
            if days is not None and days >= FOLLOW_UP_AFTER_DAYS and not row["last_signal"] and not due:
                items.append(
                    f"- [ ] **Consider chasing**: application #{row['app_id']} "
                    f"({row['company']}) has been out {days} days with no reply "
                    f"on record. Schedule it with "
                    f"`python3 -m db.tools.review follow-up --app {row['app_id']} --in-days 1`.")

    revised = conn.execute(
        "SELECT COUNT(*) AS n FROM questions_with_frequency WHERE state = 'revised'"
    ).fetchone()["n"]
    if revised:
        items.append(
            f"- [ ] **Read back {revised} bank answer(s)**: the stored text has "
            f"changed since a form received it, so the current wording has not "
            f"been read in this form. "
            f"`python3 -m db.tools.questions lookup \"<wording>\"` shows it beside "
            f"what was sent.")

    out += items or ["(nothing needs a decision today)"]
    out.append("")
    return out


def section_applications(apps, today: date) -> list[str]:
    """Section 3: every application, oldest decision first."""
    out = ["## 3. Applications", "",
           "`age` is days since submission; `last signal` is the most recent "
           "reply, interview or note on record (not the submission itself).", ""]
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
                             row["due_follow_up"], today.isoformat()),
        ])
    out += _table(["app", "employer", "role", "status", "age", "last signal",
                   "next action"], rows)
    out.append("")
    return out


def section_next_roles(conn) -> list[str]:
    """Section 4: bookmarked postings worth a look, and what the gate leaves out."""
    out = ["## 4. Next roles", ""]
    ranked = conn.execute(
        "SELECT id, title, company, region_scope, region_evidence, match_score"
        " FROM jobs WHERE status = 'bookmarked'"
        "   AND id NOT IN (SELECT job_id FROM applications)").fetchall()
    matcher = _matcher()
    # Coverage-aware order from the classifier: a posting that names a region
    # we are in (EMEA, Africa) is better information than one that says
    # nothing, so it ranks above `unknown` rather than below it. Score breaks
    # the tie, so a worldwide posting is never buried under a US-only one.
    ranked.sort(key=lambda r: (_scope_rank(r["region_scope"], r["region_evidence"]),
                               -(r["match_score"] or 0)))
    # Drop the score-0 junk the feeds carry (writers, sales, assistants) while
    # keeping a score-0 posting whose title the gate admits, since "right kind
    # of role, nothing we recognise in the text" is a judgement for a human.
    top: list = []
    per_employer: dict[str, int] = {}
    for row in ranked:
        if (row["match_score"] or 0) < RELEVANT_FLOOR and not _admits(
                matcher, row["title"]):
            continue
        if per_employer.get(row["company"], 0) >= MAX_PER_EMPLOYER:
            continue
        per_employer[row["company"]] = per_employer.get(row["company"], 0) + 1
        top.append(row)
        if len(top) >= NEXT_ROLE_LIMIT:
            break

    out += ["Ordered by where the posting hires first, then by score: "
            "worldwide, then a named region that includes you (EMEA, Africa), "
            "then unknown, then a named list that excludes you, then US-only. "
            f"At most {MAX_PER_EMPLOYER} per employer, so one company cannot "
            "fill the page:", ""]
    out += _table(["job", "role", "employer", "scope", "score"],
                  [[f"#{r['id']}", (r['title'] or '')[:42], r['company'],
                    r['region_scope'], r['match_score']] for r in top])

    total, empty, samples = _blind_spot(conn, exclude_ids={r["id"] for r in top})
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
        "python3 -m db.tools.review follow-up --app 4 --in-days 7  # schedule a chase",
        "python3 -m db.tools.review resolve --event 12             # close a chase",
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
    lines += section_next_roles(conn)
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
                                today.isoformat()).startswith(("submit", "consider",
                                                                "follow up"))]
    moved = "since " + since.replace("T", " ").replace("Z", " UTC") if since else "first run"
    print(f"rewrote {path}  ({len(apps)} application(s), {len(wait)} needing action, {moved})")
    for row in wait:
        print(f"  #{row['app_id']} {row['company']}: {row['title']}")
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


def cmd_selftest() -> int:
    today = "2026-10-18"
    cases = [
        (("ready_to_apply", None, False, None), "submit it"),
        (("applied", 3, False, None), "let it breathe (chase on day 7)"),
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

    total = len(cases) + 2 + len(rank_cases) + 1 + len(order_cases)
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

    p = sub.add_parser("follow-up", help="schedule a chase for an application")
    p.add_argument("--app", type=int, required=True, help="application id")
    p.add_argument("--in-days", dest="in_days", type=int, default=1)
    p.add_argument("--note", help="what the chase is for")
    p.set_defaults(func=cmd_follow_up)

    p = sub.add_parser("resolve", help="mark a scheduled follow-up as done")
    p.add_argument("--event", type=int, required=True, help="application_events id")
    p.add_argument("--note", help="how it went")
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("dismiss", help="archive a lead with a reason")
    p.add_argument("--job", type=int, required=True, help="jobs id")
    p.add_argument("--reason", required=True, help="why it is out of the pool")
    p.set_defaults(func=cmd_dismiss)

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
