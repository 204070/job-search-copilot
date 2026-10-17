"""Persist fetched jobs with dedupe.

Dedupe relies on the two unique indexes from migration 0004:
  - ux_jobs_url:           the same posting URL is the same job, globally
  - ux_jobs_board_source_ref: a board's own id/guid, per board.

A re-discovered job gets its last_seen_at refreshed instead of a new row.
"""
from __future__ import annotations

import json
import sqlite3
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
