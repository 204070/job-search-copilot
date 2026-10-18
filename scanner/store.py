"""Persist fetched jobs with dedupe, and tag where each posting is open.

Dedupe relies on the two unique indexes:
  - ux_jobs_url:           the same posting URL is the same job, globally
  - ux_jobs_board_source_ref: a board's own id/guid, per board.

A re-discovered job gets its last_seen_at refreshed instead of a new row. That
is why `classify_stored_jobs` exists as a separate pass: an existing row keeps
its original text, so a tag derived at insert time would freeze. Re-deriving
over the stored rows keeps `region_scope` current as the classifier improves.
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
            "SELECT id FROM jobs WHERE lower(url) = lower(?)", (job["url"],)
        ).fetchone()
    if existing is None and job.get("source_ref"):
        existing = conn.execute(
            "SELECT id FROM jobs WHERE board_id = ? AND source_ref = ?",
            (board_id, job["source_ref"]),
        ).fetchone()

    if existing is not None:
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
