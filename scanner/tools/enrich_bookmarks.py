"""Re-read the X bookmarks already stored, and pull the job out of each.

    python3 -m scanner.tools.enrich_bookmarks             # the X Bookmarks board
    python3 -m scanner.tools.enrich_bookmarks --dry-run    # show what would change
    python3 -m scanner.tools.enrich_bookmarks --board "X Bookmarks" --force
    python3 -m scanner.tools.enrich_bookmarks [SQL]        # limit to a job id/db

Why this exists rather than a re-scan: a bookmark row is written once and a
re-scan only refreshes `last_seen_at`, so the 50 rows stored as "Unknown" with
the whole tweet as a title would never pick up the extractor. This rewrites
title/company/location/workplace_type from the stored tweet text, re-scores
against the recovered title, and marks the row `job_like` so a board can tell
a posting from a saved link.

Rows are only rewritten when `metadata.via` is `x_bookmarks` — a hand-edited
row is left alone. Already-enriched rows are skipped unless --force, so a
second run is a no-op.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # repo root

from db import connect  # noqa: E402
from scanner import bookmarks  # noqa: E402
from scanner.keywords import Matcher  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Enrich stored X-bookmark rows.")
    p.add_argument("--board", default="X Bookmarks",
                   help="board holding the bookmark rows (default: X Bookmarks)")
    p.add_argument("--dry-run", action="store_true", help="report, write nothing")
    p.add_argument("--force", action="store_true",
                   help="re-enrich rows that were already enriched")
    p.add_argument("--limit", type=int, default=0, help="max rows to process")
    args = p.parse_args(argv)

    conn = connect()
    conn.row_factory = sqlite3.Row
    matcher = Matcher()

    board = conn.execute(
        "SELECT id FROM boards WHERE name = ?", (args.board,)
    ).fetchone()
    if board is None:
        p.error(f"no board named {args.board!r}")

    sql = ("SELECT id, title, company, location, raw_text, url, metadata "
           "FROM jobs WHERE board_id = ? ORDER BY id")
    rows = conn.execute(sql, (board["id"],)).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    changed = job_like = skipped = 0
    for row in rows:
        try:
            meta = json.loads(row["metadata"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        if meta.get("via") != "x_bookmarks":
            continue  # hand-added or from another board: not ours to rewrite
        if meta.get("job_like") is not None and not args.force:
            skipped += 1
            continue

        text = row["raw_text"] or row["title"] or ""
        info = bookmarks.enrich(text, row["url"])
        score, _matched = matcher.score(info["title"] or row["title"], text)

        before = (row["title"], row["company"], row["location"], meta.get("job_like"))
        after = (info["title"] or row["title"], info["company"] or "Unknown",
                 info["location"], int(info["job_like"]))
        meta["job_like"] = int(info["job_like"])
        if info["title"]:
            meta["tweet_title"] = re.sub(r"\s+", " ", text)[:200]

        if after != before:
            changed += 1
        job_like += int(info["job_like"])
        print(f"#{row['id']:<5} job_like={int(info['job_like'])} "
              f"score={score}  {(after[1] or '?')[:24]:<24} {(after[0] or '')[:44]}")
        if info["location"]:
            print(f"        location={info['location']!r}")
        if not args.dry_run:
            conn.execute(
                "UPDATE jobs SET title = ?, company = ?, location = ?, "
                "workplace_type = ?, match_score = ?, metadata = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
                (after[0][:160], after[1], after[2],
                 bookmarks.workplace_type(after[2]), score, json.dumps(meta),
                 row["id"]),
            )

    if not args.dry_run:
        conn.commit()
    print(f"\n{len(rows)} rows on board {args.board!r} | {job_like} read as postings "
          f"| {changed} rewritten | {skipped} already enriched"
          + (" [dry run]" if args.dry_run else ""))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
