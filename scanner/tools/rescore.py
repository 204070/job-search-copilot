"""Re-score stored jobs after the keyword config changed.

    python3 -m scanner.tools.rescore                 # all jobs, show the spread
    python3 -m scanner.tools.rescore --dry-run       # report, write nothing
    python3 -m scanner.tools.rescore --top 15        # what the new ranking puts first
    python3 -m scanner.tools.rescore --only-below 15 # cheap pass over the low end
    python3 -m scanner.tools.rescore --board RemoteOK

`match_score` is written at insert time and never refreshed, because a
re-discovered job keeps its original row (`upsert_job` only touches
`last_seen_at`). So a change to `scanner/keywords.jsonc` applies to new
postings only until this runs. It is idempotent, and safe to run any time.

`--top` is the part worth eyeballing: a scoring change is only an improvement
if the postings it promotes are ones you would actually open.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # repo root

from db import connect  # noqa: E402
from scanner.keywords import Matcher, min_score  # noqa: E402
from scanner.store import SCORE_BANDS, rescore_stored_jobs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Re-derive match scores from stored text.")
    p.add_argument("--board", help="limit to this board name")
    p.add_argument("--only-below", type=int, metavar="N",
                   help="only rows currently scoring below N")
    p.add_argument("--dry-run", action="store_true", help="report, write nothing")
    p.add_argument("--top", type=int, default=0,
                   help="after scoring, show the N highest postings")
    args = p.parse_args(argv)

    conn = connect()
    conn.row_factory = sqlite3.Row

    board_id = None
    if args.board:
        row = conn.execute(
            "SELECT id FROM boards WHERE name = ?", (args.board,)
        ).fetchone()
        if row is None:
            p.error(f"no board named {args.board!r}")
        board_id = row["id"]

    matcher = Matcher()
    counts, changed = rescore_stored_jobs(
        conn, board_id=board_id, only_below=args.only_below, dry_run=args.dry_run
    )

    total = sum(counts.values())
    where = f"board={args.board}" if args.board else "all boards"
    if args.only_below is not None:
        where += f", was below {args.only_below}"
    print(f"match_score over {total} jobs ({where})"
          + (" [dry run]" if args.dry_run else ""))
    print(f"  threshold {min_score()}   target weight {matcher.target_weight}")
    lead = min_score()
    for lo, hi, label in SCORE_BANDS:
        n = counts.get(label, 0)
        mark = "  <- leads" if hi >= lead >= lo else ""
        print(f"  {label:<6} {n:>4}{mark}")
    verb = "would change" if args.dry_run else "changed"
    print(f"{verb}: {changed}")

    if args.top:
        sql = "SELECT id, company, title, raw_text, match_score, region_scope FROM jobs"
        if board_id is not None:
            sql += " WHERE board_id = ?"
            params = [board_id]
        else:
            params = []
        # Scored here rather than read back, so a dry run and an --only-below
        # pass both rank by the new scores instead of the stored ones.
        scored = []
        for r in conn.execute(sql, params).fetchall():
            title_only, _ = matcher.score(r["title"], None)
            scored.append((matcher.score(r["title"], r["raw_text"])[0], title_only, r))
        scored.sort(key=lambda t: (-t[0], t[2]["id"]))
        print()
        print(f"--- top {args.top} by score")
        for score, title_only, r in scored[:args.top]:
            note = "" if title_only == score else f"  (title alone: {title_only})"
            print(f"  {score:>3} [{r['region_scope'] or '?':<12}] "
                  f"{(r['company'] or '?')[:20]:<20} {(r['title'] or '')[:44]}{note}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
