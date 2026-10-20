"""Persist fetched jobs with dedupe, and tag where each posting is open.

Dedupe relies on the two unique indexes:
  - ux_jobs_url:           the same posting URL is the same job, globally
  - ux_jobs_board_source_ref: a board's own id/guid, per board.

A re-discovered job gets its last_seen_at refreshed instead of a new row, and
keeps the text and score it was stored with. The one addition it accepts is a
description it never had, which is how a board that states the advert on the
posting's own page (rather than on the card the scan reads first) ends up with
one; the score that description earns is written with it. That is also why
`classify_stored_jobs` exists as a separate pass: an existing row keeps its
original text, so a tag derived at insert time would freeze. Re-deriving over
the stored rows keeps `region_scope` current as the classifier improves.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def upsert_job(conn: sqlite3.Connection, board_id: int, job: dict) -> tuple[str, int]:
    """Insert or touch one fetched job. Returns (status, job_id).

    status: 'new' when the row was created, 'seen' when it already existed.
    `job` keys: title, company, url, source_ref, description, location,
    workplace_type, salary_min, salary_max, salary_currency, posted_at,
    metadata (dict), match_score (int).
    """
    ts = now_iso()
    # Intent flag: set by fetchers that read the user's own X bookmarks. Kept
    # even when the URL is already known from another board (migration 0010).
    bookmarked = bool((job.get("metadata") or {}).get("bookmarked"))
    existing = None
    if job.get("url"):
        existing = conn.execute(
            "SELECT id, raw_text FROM jobs WHERE lower(url) = lower(?)", (job["url"],)
        ).fetchone()
    if existing is None and job.get("source_ref"):
        existing = conn.execute(
            "SELECT id, raw_text FROM jobs WHERE board_id = ? AND source_ref = ?",
            (board_id, job["source_ref"]),
        ).fetchone()

    if existing is not None:
        text = (job.get("description") or "").strip()
        if text and not (existing["raw_text"] or "").strip():
            # The one thing a re-discovered row accepts: a description it never
            # had, plus the score that description earns. Boards that keep the
            # advert on the posting's own page store the card first and the text
            # on a later run, so without this the text would be fetched on every
            # run and thrown away. Text already stored is never replaced.
            conn.execute(
                "UPDATE jobs SET last_seen_at = ?, raw_text = ?, match_score = ?, "
                "bookmarked_at = COALESCE(bookmarked_at, ?) WHERE id = ?",
                (ts, text, job.get("match_score", 0),
                 ts if bookmarked else None, existing["id"]),
            )
        else:
            conn.execute(
                "UPDATE jobs SET last_seen_at = ?, "
                "bookmarked_at = COALESCE(bookmarked_at, ?) WHERE id = ?",
                (ts, ts if bookmarked else None, existing["id"]),
            )
        return "seen", existing["id"]

    try:
        cur = conn.execute(
            """INSERT INTO jobs
               (board_id, source_ref, title, company, url, location,
                workplace_type, raw_text, salary_min, salary_max,
                salary_currency, posted_at, status, match_score,
                last_seen_at, metadata, bookmarked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'bookmarked', ?, ?, ?,
                       ?)""",
            (
                board_id,
                job.get("source_ref"),
                job.get("title"),
                (job.get("company") or "").strip() or "Unknown",
                job.get("url"),
                job.get("location"),
                job.get("workplace_type", "unknown"),
                job.get("description"),
                job.get("salary_min"),
                job.get("salary_max"),
                job.get("salary_currency"),
                job.get("posted_at"),
                job.get("match_score", 0),
                ts,
                json.dumps(job.get("metadata") or {}),
                ts if bookmarked else None,
            ),
        )
        return "new", cur.lastrowid
    except sqlite3.IntegrityError:
        # Lost a race with a concurrent writer, or a url/source_ref variant we
        # did not check above: treat as already known.
        row = conn.execute(
            "SELECT id FROM jobs WHERE board_id = ? AND source_ref = ?",
            (board_id, job.get("source_ref")),
        ).fetchone()
        if row is None:
            raise
        conn.execute("UPDATE jobs SET last_seen_at = ? WHERE id = ?", (ts, row["id"]))
        return "seen", row["id"]


def classify_stored_jobs(
    conn: sqlite3.Connection,
    *,
    board_id: int | None = None,
    only_missing: bool = False,
    dry_run: bool = False,
) -> tuple[Counter, int]:
    """Re-derive `region_scope`/`region_evidence` for stored jobs.

    Returns (counts by scope, rows changed). Re-runnable and idempotent, so it
    can run after every scan and by hand whenever the classifier improves.
    `only_missing` limits the pass to rows never tagged (scope unknown and no
    evidence), for a cheap incremental run. `dry_run` counts what would change
    without writing it.
    """
    from scanner.eligibility import classify

    sql = "SELECT id, location, raw_text, region_scope, region_evidence FROM jobs"
    params: list = []
    if board_id is not None:
        sql += " WHERE board_id = ?"
        params.append(board_id)

    counts: Counter = Counter()
    changed = 0
    for row in conn.execute(sql, params).fetchall():
        if only_missing and not (
            row["region_scope"] == "unknown" and row["region_evidence"] is None
        ):
            continue
        scope, evidence = classify(row["location"], row["raw_text"])
        counts[scope] += 1
        if scope != row["region_scope"] or evidence != row["region_evidence"]:
            changed += 1
            if not dry_run:
                conn.execute(
                    "UPDATE jobs SET region_scope = ?, region_evidence = ? WHERE id = ?",
                    (scope, evidence, row["id"]),
                )
    if not dry_run:
        conn.commit()
    return counts, changed


# Score bands for reporting. The first band is the honest "nothing on the list
# is named in this posting" bucket, which is not the same as "not our kind of
# role" — see Matcher.admits() for that question.
SCORE_BANDS: tuple[tuple[int, int, str], ...] = (
    (0, 0, "0"),
    (1, 14, "1-14"),
    (15, 29, "15-29"),
    (30, 49, "30-49"),
    (50, 99, "50+"),
)


def score_band(score: int | None) -> str:
    """Label a match score with its reporting band."""
    s = score or 0
    for lo, hi, label in SCORE_BANDS:
        if lo <= s <= hi:
            return label
    return SCORE_BANDS[-1][2]


def rescore_stored_jobs(
    conn: sqlite3.Connection,
    *,
    board_id: int | None = None,
    only_below: int | None = None,
    dry_run: bool = False,
) -> tuple[Counter, int]:
    """Re-derive `match_score` for stored jobs from their stored text.

    Returns (counts by score band, rows changed). Separate from the scan for
    the same reason as `classify_stored_jobs`: a re-discovered job keeps its
    row, and `upsert_job` only refreshes `last_seen_at`, so a score written at
    insert time never refreshes. Re-running after the keyword config changes is
    the whole point, so this is idempotent.

    `only_below` limits the pass to rows scoring below a number, for a cheap
    second look after the config improves. `dry_run` reports what would change
    without writing it.
    """
    from scanner.keywords import Matcher

    matcher = Matcher()
    sql = "SELECT id, company, title, raw_text, match_score FROM jobs"
    params: list = []
    if board_id is not None:
        sql += " WHERE board_id = ?"
        params.append(board_id)

    counts: Counter = Counter()
    changed = 0
    for row in conn.execute(sql, params).fetchall():
        if only_below is not None and (row["match_score"] or 0) >= only_below:
            continue
        if matcher.bans(row["company"]):
            # A banned employer cannot lead, even if the row predates the ban.
            score = 0
        else:
            score, _ = matcher.score(row["title"], row["raw_text"])
        counts[score_band(score)] += 1
        if score != (row["match_score"] or 0):
            changed += 1
            if not dry_run:
                conn.execute(
                    "UPDATE jobs SET match_score = ? WHERE id = ?", (score, row["id"])
                )
    if not dry_run:
        conn.commit()
    return counts, changed


def _self_test() -> int:
    """`python3 -m scanner.store` — what a re-discovered row is allowed to change.

    On a throwaway database, because the rule under test is what `upsert_job`
    writes to a row it already holds. The HTML list boards depend on it: they
    store the card first and read the posting's own page for the advert on a
    later run, and that text only reaches the row through this path.
    """
    import tempfile
    from pathlib import Path

    from db import connect
    from db.migrate import run_migrations

    path = Path(tempfile.mkdtemp()) / "store-selftest.db"
    run_migrations(db_path=path)
    conn = connect(path)
    board = conn.execute(
        "INSERT INTO boards (name, kind, scan_strategy, enabled) "
        "VALUES ('Selftest', 'job_board', 'rss', 1)"
    ).lastrowid
    total = failures = 0

    def check(label: str, got, want) -> None:
        nonlocal total, failures
        total += 1
        ok = got == want
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))

    def stored(job_id: int) -> tuple:
        row = conn.execute(
            "SELECT raw_text, match_score FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return row["raw_text"], row["match_score"]

    card = {"title": "Senior Engineer", "company": "Northwind",
            "url": "https://example.invalid/1", "description": None,
            "match_score": 20, "posted_at": "2026-10-19"}

    status, job_id = upsert_job(conn, board, card)
    check("a card-only posting is stored without text", (status, stored(job_id)),
          ("new", (None, 20)))

    status, _ = upsert_job(conn, board, {**card, "description": "TypeScript and React.",
                                         "match_score": 88})
    check("the advert arrives later: adopted with its score",
          (status, stored(job_id)), ("seen", ("TypeScript and React.", 88)))

    status, _ = upsert_job(conn, board, {**card, "description": "A different advert.",
                                         "match_score": 5})
    check("  text already held is never replaced", stored(job_id),
          ("TypeScript and React.", 88))

    _, textless = upsert_job(conn, board, {**card, "url": "https://example.invalid/2"})
    status, _ = upsert_job(conn, board, {**card, "url": "https://example.invalid/2",
                                         "match_score": 30})
    check("  a posting that still has no text keeps its score",
          (status, stored(textless)), ("seen", (None, 20)))

    print(f"\n{total - failures}/{total} cases pass")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
