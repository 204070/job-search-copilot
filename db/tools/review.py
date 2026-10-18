"""Review digest: the decisions waiting on a human, in one page.

The scanner writes leads, the application runbook files applications, and the
question bank accumulates answers. None of that tells you what needs a decision
this week. This tool reads the database and produces that page:

    python3 -m db.tools.review                 # write logs/reviews/<date>.md
    python3 -m db.tools.review follow-up --app 3 --in-days 7
    python3 -m db.tools.review resolve --event 4

`logs/` is gitignored, deliberately: the digest names employers, and this repo
is public. The digest is a private working document, regenerated whenever it is
wanted, never a source of truth. Everything in it is derived from `db/jobs.db`.

Sections are ordered by what is most likely to be expensive to miss:

1. Needs you now      follow-ups due, applications filled but not sent
2. Applications       every application with its age and next action
3. Next roles         bookmarked postings, best-ranked first
4. Pipeline health    counts that say whether the ranking can be trusted
5. Question bank      answers still awaiting a human read

The follow-up clock is `FOLLOW_UP_AFTER_DAYS`: an application that has been out
that long with no reply on record is worth chasing. The digest only suggests
that; scheduling is an explicit command so the signal stays yours.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from db.connection import connect

#: Days after submission with no reply on record before a chase is suggested.
FOLLOW_UP_AFTER_DAYS = 7

#: Where digests are written (gitignored via the `logs/` rule).
DEFAULT_OUT_DIR = Path("logs/reviews")

#: Sort key for where a posting hires. `unknown` stays visible on purpose.
SCOPE_RANK = {"worldwide": 0, "unknown": 1, "region_gated": 2, "us_only": 3}

#: Titles that look like this workspace's target roles even at score 0. Used to
#: measure the scorer's blind spot, never to rank (see `_blind_spot`).
ENGINEERING_TITLE = re.compile(
    r"(?i)\b(engineer|developer|programmer|sre|devops|architect)\b")

#: Statuses that mean the application is over.
CLOSED_STATUSES = ("rejected", "withdrawn", "archived")

#: Below this score a posting is only listed when its title plainly names one of
#: our roles. Matches the scanner's own MATCH_MIN_SCORE default, kept as a
#: literal so this module does not import the scanner.
RELEVANT_FLOOR = 15

#: How many postings one employer may contribute to the shortlist.
MAX_PER_EMPLOYER = 2

#: How many postings the shortlist shows.
NEXT_ROLE_LIMIT = 12

HISTORY_LIMIT = 3


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


def _blind_spot(conn: sqlite3.Connection, exclude_ids: set[int] | None = None,
                limit: int = 12) -> tuple[int, list]:
    """Bookmarked postings whose title reads like a target role but scored 0.

    The scorer's title gate is a fixed list of phrasings, so whole families
    ("Frontend Engineer", "Security Engineer", "SDK Engineer") fall to 0 and sink
    out of any score-ordered shortlist. This reports the size of that hole. It
    does not rank, because score 0 carries no ordering information.
    """
    rows = conn.execute(
        "SELECT id, title, company, region_scope, match_score, url FROM jobs"
        " WHERE status = 'bookmarked' AND coalesce(match_score, 0) = 0"
    ).fetchall()
    skip = exclude_ids or set()
    hits = [r for r in rows
            if r["id"] not in skip and ENGINEERING_TITLE.search(r["title"] or "")]
    return len(hits), hits[:limit]


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


def section_needs_you(conn, apps, today: date) -> list[str]:
    """Section 1: anything with a date attached or a decision outstanding."""
    out = ["## 1. Needs you now", ""]
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

    pending = _count(conn, "SELECT COUNT(*) FROM questions WHERE status = 'draft'")
    if pending:
        items.append(
            f"- [ ] **Review the question bank**: {pending} answer(s) still "
            f"marked draft, so none has been read back to you.")

    out += items or ["(nothing needs a decision today)"]
    out.append("")
    return out


def section_applications(apps, today: date) -> list[str]:
    """Section 2: every application, oldest decision first."""
    out = ["## 2. Applications", "",
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
    """Section 3: bookmarked postings worth a look, and the scorer's blind spot."""
    out = ["## 3. Next roles", ""]
    ranked = conn.execute(
        "SELECT id, title, company, region_scope, region_evidence, match_score"
        " FROM jobs WHERE status = 'bookmarked'"
        "   AND id NOT IN (SELECT job_id FROM applications)").fetchall()
    # Same precedence the scanner report uses: where it hires outranks how well
    # it scores, so a worldwide posting is never buried under a US-only one.
    ranked.sort(key=lambda r: (SCOPE_RANK.get(r["region_scope"], 9),
                               -(r["match_score"] or 0)))
    # Drop the score-0 junk the feeds carry (writers, sales, assistants) while
    # keeping score-0 postings whose title is plainly one of our roles, since
    # those are exactly what the gate is failing to see.
    top: list = []
    per_employer: dict[str, int] = {}
    for row in ranked:
        if (row["match_score"] or 0) < RELEVANT_FLOOR and not ENGINEERING_TITLE.search(
                row["title"] or ""):
            continue
        if per_employer.get(row["company"], 0) >= MAX_PER_EMPLOYER:
            continue
        per_employer[row["company"]] = per_employer.get(row["company"], 0) + 1
        top.append(row)
        if len(top) >= NEXT_ROLE_LIMIT:
            break

    out += ["Ordered by where the posting hires first, then by score "
            "(worldwide, unknown, region-gated, US-only). At most "
            f"{MAX_PER_EMPLOYER} per employer, so one company cannot fill the "
            "page:", ""]
    out += _table(["job", "role", "employer", "scope", "score"],
                  [[f"#{r['id']}", (r['title'] or '')[:42], r['company'],
                    r['region_scope'], r['match_score']] for r in top])

    total, samples = _blind_spot(conn, exclude_ids={r["id"] for r in top})
    out += ["", f"**Scorer blind spot: {total} bookmarked postings read like a "
            "target role but score 0.** The gate accepts a fixed list of "
            "phrasings, so these are invisible to a score-ordered shortlist. "
            "Read them by title until the gate is fixed:", ""]
    out += _table(
        ["job", "role", "employer", "scope"],
        [[f"#{r['id']}", (r['title'] or '')[:48], r['company'], r['region_scope']]
         for r in samples])
    out.append("")
    return out


def section_health(conn) -> list[str]:
    """Section 4: counts that decide whether section 3 can be trusted."""
    out = ["## 4. Pipeline health", ""]
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
    """Section 5: what the bank knows, and what it still needs from you."""
    out = ["## 5. Question bank", ""]
    total = _count(conn, "SELECT COUNT(*) FROM questions")
    asked_twice = _count(
        conn, "SELECT COUNT(*) FROM questions_with_frequency WHERE times_asked >= 2")
    out.append(f"{total} question(s) recorded; {asked_twice} asked more than once "
               "(those are the ones worth stabilising).")
    out.append("")
    rows = conn.execute(
        "SELECT id, question_key, kind, times_asked, status,"
        "       substr(canonical_text, 1, 58) q"
        " FROM questions_with_frequency WHERE status <> 'retired'"
        " ORDER BY times_asked DESC, id LIMIT 20").fetchall()
    out += _table(["id", "key", "kind", "asked", "status", "question"],
                  [[r["id"], f"`{r['question_key']}`", r["kind"], r["times_asked"],
                    r["status"], r["q"]] for r in rows])
    out.append("")
    return out


def build_digest(conn: sqlite3.Connection, today: date | None = None) -> str:
    """The whole digest as markdown."""
    today = today or datetime.now(timezone.utc).date()
    apps = _applications(conn)
    today_name = f"{today.isoformat()}.md"
    previous = sorted(p for p in DEFAULT_OUT_DIR.glob("*.md")
                      if p.name != today_name) if DEFAULT_OUT_DIR.exists() else []

    lines = [
        f"# Review digest, {today.isoformat()}",
        "",
        "Private working document (generated into gitignored `logs/`). Employer",
        "names belong here and never in a committed file.",
        "",
        f"Regenerate: `python3 -m db.tools.review`  |  "
        f"Schedule a chase: `python3 -m db.tools.review follow-up --app <id> --in-days <n>`",
    ]
    if previous:
        lines.append(f"Earlier digests: {', '.join(p.name for p in previous[-HISTORY_LIMIT:])}")
    lines += ["", f"{len(apps)} application(s) on file." if apps
              else "No applications on file yet.", ""]

    lines += section_needs_you(conn, apps, today)
    lines += section_applications(apps, today)
    lines += section_next_roles(conn)
    lines += section_health(conn)
    lines += section_questions(conn)
    return "\n".join(lines)


# --- commands ---------------------------------------------------------------


def cmd_digest(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    today = datetime.now(timezone.utc).date()
    text = build_digest(conn, today)
    if args.stdout:
        print(text)
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{today.isoformat()}.md"
    path.write_text(text, encoding="utf-8")

    apps = _applications(conn)
    wait = [r for r in apps
            if follow_up_action(r["app_status"],
                                days_since(r["applied_at"], today),
                                bool(r["last_signal"]), r["due_follow_up"],
                                today.isoformat()).startswith(("submit", "consider",
                                                                "follow up"))]
    print(f"wrote {path}  ({len(apps)} application(s), {len(wait)} needing action)")
    for row in wait:
        print(f"  #{row['app_id']} {row['company']}: {row['title']}")
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
    total = len(cases) + 2
    print(f"{total - failures}/{total} cases pass")
    return 1 if failures else 0


# --- CLI --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m db.tools.review",
        description="The decision queue: follow-ups, applications, next roles.")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("digest", help="write the digest (the default)")
    p.add_argument("--out-dir", dest="out_dir", default=str(DEFAULT_OUT_DIR))
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
