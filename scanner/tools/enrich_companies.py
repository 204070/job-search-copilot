"""Recover the employer that a feed left inside the title.

    python3 -m scanner.tools.enrich_companies              # all 'Unknown' rows
    python3 -m scanner.tools.enrich_companies --dry-run
    python3 -m scanner.tools.enrich_companies --board "Real Work From Anywhere"
    python3 -m scanner.tools.enrich_companies --limit 50

Real Work From Anywhere and We Work Remotely publish no employer tag — the
company rides in the title ("Backend Engineer, Core APIs at Northwind",
"acmecorp: Fullstack Web3 Engineer"). Stored as `Unknown`, those rows are
invisible to any board that looks a lead up by company, which is most of them.

This reads the two title shapes `fetchers.split_company` handles and fills the
company in. A row whose title yields no employer is left untouched and counted,
so the remaining `Unknown` rows are a known quantity rather than a mystery.

Re-running is safe: only `Unknown` rows are considered, and the extracted
employer is stripped out of the title, so a second pass finds nothing to do.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # repo root

from db import connect  # noqa: E402
from scanner.fetchers import split_company  # noqa: E402
from scanner.keywords import Matcher  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fill in companies hidden in titles.")
    p.add_argument("--board", help="limit to this board name")
    p.add_argument("--dry-run", action="store_true", help="report, write nothing")
    p.add_argument("--limit", type=int, default=0, help="max rows to process")
    args = p.parse_args(argv)

    conn = connect()
    conn.row_factory = sqlite3.Row
    matcher = Matcher()

    sql = ("SELECT id, title, raw_text, match_score FROM jobs "
           "WHERE company = 'Unknown' OR company IS NULL OR company = ''")
    params: list = []
    if args.board:
        board = conn.execute(
            "SELECT id FROM boards WHERE name = ?", (args.board,)
        ).fetchone()
        if board is None:
            p.error(f"no board named {args.board!r}")
        sql += " AND board_id = ?"
        params.append(board["id"])
    rows = conn.execute(sql + " ORDER BY id", params).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    filled = unresolved = 0
    by_company: dict[str, int] = {}
    for row in rows:
        company, clean_title = split_company(row["title"] or "")
        if not company:
            unresolved += 1
            continue
        filled += 1
        by_company[company] = by_company.get(company, 0) + 1
        score, _matched = matcher.score(clean_title, row["raw_text"])
        print(f"#{row['id']:<5} {company[:26]:<26} {(row['title'] or '')[:46]}")
        if not args.dry_run:
            conn.execute(
                "UPDATE jobs SET company = ?, title = ?, match_score = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ?",
                (company, clean_title[:160], score, row["id"]),
            )

    if not args.dry_run:
        conn.commit()
    print(f"\n{len(rows)} unnamed rows | {filled} recovered | {unresolved} still unknown"
          + (" [dry run]" if args.dry_run else ""))
    if by_company:
        top = sorted(by_company.items(), key=lambda kv: -kv[1])[:10]
        print("busiest employers: " + ", ".join(f"{c} ({n})" for c, n in top))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
