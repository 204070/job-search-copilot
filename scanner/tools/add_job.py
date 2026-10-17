"""Add a job by hand — leads that didn't come from a board scan.

    python3 -m scanner.tools.add_job --title "Senior Backend Eng" \\
        --url https://boards.example.com/job/123 --company Acme \\
        [--board Manual] [--location Berlin] [--workplace remote] \\
        [--note "referred by Jane"] [--salary-min 90000 --salary-max 120000]

The job is scored like any scanned job (terms from scanner/keywords.jsonc) and stored on the
named board; unknown board names are created on the fly with
scan_strategy='manual' so scanners never touch them.

Source of any row = jobs.board_id -> boards; browse it via the
jobs_with_source view:  SELECT id, title, source FROM jobs_with_source;
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # repo root

from db import connect  # noqa: E402
from scanner.keywords import Matcher  # noqa: E402
from scanner.store import upsert_job  # noqa: E402


def ensure_board(conn: sqlite3.Connection, name: str) -> int:
    """Board id for `name`, creating it (hand-managed, never scanned) if new."""
    row = conn.execute("SELECT id FROM boards WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO boards (name, kind, enabled, notes, scan_strategy, scan_config) "
        "VALUES (?, 'other', 1, 'Created by scanner.tools.add_job; hand-managed.', "
        "'manual', '{}')",
        (name,),
    )
    assert cur.lastrowid
    return int(cur.lastrowid)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Add a job by hand.")
    p.add_argument("--title", required=True)
    p.add_argument("--url", help="posting URL; also the global dedupe key")
    p.add_argument("--company", default=None)
    p.add_argument("--board", default="Manual",
                   help="source board name (default: Manual; created if new)")
    p.add_argument("--location")
    p.add_argument("--workplace", default="unknown",
                   choices=["remote", "hybrid", "onsite", "unknown"])
    p.add_argument("--note", help="free-form note; also the scoring description")
    p.add_argument("--salary-min", type=int)
    p.add_argument("--salary-max", type=int)
    p.add_argument("--salary-currency", default=None,
                   help="only stored when a salary bound is given")
    args = p.parse_args(argv)
    if args.url is None and args.note is None:
        p.error("give at least --url or --note, or there is nothing to judge the lead by")

    conn = connect()
    conn.row_factory = sqlite3.Row
    board_id = ensure_board(conn, args.board)

    score, matched = Matcher().score(args.title, args.note or "")
    status, job_id = upsert_job(conn, board_id, {
        "title": args.title,
        "company": args.company,
        "url": args.url,
        "location": args.location,
        "workplace_type": args.workplace,
        "description": args.note,
        "salary_min": args.salary_min,
        "salary_max": args.salary_max,
        "salary_currency": (
            args.salary_currency
            if (args.salary_min is not None or args.salary_max is not None) else None
        ),
        "metadata": {"via": "manual", **({"note": args.note} if args.note else {})},
        "match_score": score,
    })
    conn.commit()

    hits = f" — matched: {', '.join(matched)}" if matched else ""
    print(f"{status}: #{job_id} [{args.board}] score {score}{hits}")
    if args.url:
        print(args.url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
